"""Эндпоинты профиля компании клиента: GET /company, PUT /company, GET /company/lookup."""
import logging
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.schemas.company import CompanyInput, CompanyResponse
from app.auth.deps import TokenData, require_role
from app.db import get_db
from app.enums import ErrorCode, LegalForm, Role
from app.errors import ApiError
from app.models.tables import Company
from app.services.egrul_port import EgrulClientProtocol, get_egrul_client
from app.services.inn_validator import is_valid_inn_format

log = logging.getLogger("app.api.company")
router = APIRouter(prefix="/company", tags=["Company"])


@router.get("", response_model=CompanyResponse)
def get_my_company(
    current_user: TokenData = Depends(require_role(Role.CLIENT)),
    db: Session = Depends(get_db),
) -> Company:
    """Получить профиль компании текущего пользователя."""
    stmt = select(Company).where(Company.owner_id == current_user.user_id)
    company = db.scalar(stmt)
    if company is None:
        raise ApiError(
            status_code=404,
            code=ErrorCode.NOT_FOUND,
            message="Профиль компании ещё не создан",
        )
    return company


@router.put("", response_model=CompanyResponse)
def upsert_my_company(
    body: CompanyInput,
    current_user: TokenData = Depends(require_role(Role.CLIENT)),
    db: Session = Depends(get_db),
) -> Company:
    """Создать или обновить профиль компании текущего пользователя."""
    # 1. Валидация соответствия длины ИНН организационно-правовой форме
    if body.legal_form == LegalForm.OOO and len(body.inn) != 10:
        raise ApiError(
            status_code=422,
            code=ErrorCode.VALIDATION_ERROR,
            message="Для ООО ИНН должен состоять из 10 цифр",
            details=[{"field": "inn", "message": "Длина ИНН для ООО должна быть 10 цифр"}],
        )
    if body.legal_form == LegalForm.IP and len(body.inn) != 12:
        raise ApiError(
            status_code=422,
            code=ErrorCode.VALIDATION_ERROR,
            message="Для ИП ИНН должен состоять из 12 цифр",
            details=[{"field": "inn", "message": "Длина ИНН для ИП должна быть 12 цифр"}],
        )

    # 2. Проверка уникальности ИНН среди других пользователей
    dup_stmt = select(Company).where(
        Company.inn == body.inn,
        Company.owner_id != current_user.user_id,
    )
    if db.scalar(dup_stmt) is not None:
        raise ApiError(
            status_code=409,
            code=ErrorCode.CONFLICT,
            message="ИНН уже закреплён за другим пользователем",
        )

    # 3. Поиск существующей компании пользователя
    stmt = select(Company).where(Company.owner_id == current_user.user_id)
    company = db.scalar(stmt)

    if company is None:
        company = Company(
            id=uuid.uuid4(),
            owner_id=current_user.user_id,
            inn=body.inn,
            name=body.name,
            legal_form=body.legal_form.value,
            registration_date=body.registration_date,
            okved=body.okved,
            address=body.address,
        )
        db.add(company)
    else:
        company.inn = body.inn
        company.name = body.name
        company.legal_form = body.legal_form.value
        company.registration_date = body.registration_date
        company.okved = body.okved
        company.address = body.address

    try:
        db.commit()
        db.refresh(company)
    except IntegrityError:
        db.rollback()
        raise ApiError(
            status_code=409,
            code=ErrorCode.CONFLICT,
            message="Конфликт уникальности ИНН (уже зарегистрирован другим пользователем)",
        )
    return company


@router.get("/lookup", response_model=CompanyInput)
def lookup_company_by_inn(
    inn: str = Query(..., pattern=r"^\d{10}(\d{2})?$"),
    current_user: TokenData = Depends(require_role(Role.CLIENT)),
    egrul_client: EgrulClientProtocol = Depends(get_egrul_client),
) -> CompanyInput:
    """Поиск данных компании по ИНН в ЕГРЮЛ/ЕГРИП."""
    if not is_valid_inn_format(inn):
        raise ApiError(
            status_code=422,
            code=ErrorCode.VALIDATION_ERROR,
            message="ИНН неверной длины или формата",
            details=[{"field": "inn", "message": "Некорректный формат ИНН"}],
        )

    company_data = egrul_client.lookup(inn)
    if company_data is None:
        raise ApiError(
            status_code=404,
            code=ErrorCode.NOT_FOUND,
            message="ИНН не найден в реестре (мок ЕГРЮЛ)",
        )
    return company_data
