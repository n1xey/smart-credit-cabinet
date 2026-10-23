"""API загрузки и скачивания документов по кредитным заявкам."""
import hashlib
import re
import urllib.parse
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas.documents import DocumentResponse
from app.auth.deps import TokenData, get_current_user, require_role
from app.config import Settings, get_settings
from app.db import get_db
from app.enums import ApplicationStatus, DocType, ErrorCode, Role
from app.errors import ApiError
from app.models.tables import Application, Document

router = APIRouter(prefix="/applications", tags=["Documents"])

_SIGNATURES: dict[str, bytes] = {
    "application/pdf": b"%PDF-",
    "image/png": b"\x89PNG\r\n\x1a\n",
    "image/jpeg": b"\xff\xd8\xff",
    "image/jpg": b"\xff\xd8\xff",
}


def sanitize_filename(filename: str | None) -> str:
    """Очищает имя файла от path traversal, управляющих символов, кавычек и переводов строк."""
    if not filename:
        return "document"
    # 1. Извлекаем только базовое имя (защита от path traversal ../)
    base = Path(filename).name
    # 2. Заменяем переводы строк, \0, кавычки и слэши на подчеркивание
    cleaned = re.sub(r'[\r\n\0"\'\\]', "_", base)
    # 3. Оставляем только печатные символы
    cleaned = "".join(ch for ch in cleaned if ord(ch) >= 32 and ord(ch) != 127).strip()
    if not cleaned or cleaned in (".", ".."):
        return "document"
    # 4. Ограничиваем длину 255 символами с сохранением расширения
    if len(cleaned) > 255:
        parts = cleaned.rsplit(".", 1)
        if len(parts) == 2 and len(parts[1]) <= 10:
            ext = "." + parts[1]
            cleaned = parts[0][: 255 - len(ext)] + ext
        else:
            cleaned = cleaned[:255]
    return cleaned


def format_content_disposition(filename: str) -> str:
    """Формирует безопасный заголовок Content-Disposition по RFC 6266 и RFC 5987."""
    clean_name = sanitize_filename(filename)
    # ASCII fallback без пробелов, кавычек и спецсимволов
    ascii_name = re.sub(r"[^a-zA-Z0-9._-]", "_", clean_name)
    if not ascii_name:
        ascii_name = "document"
    # RFC 5987 UTF-8 кодирование для поддержки любых языков и символов
    encoded_name = urllib.parse.quote(clean_name, encoding="utf-8")
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded_name}'



def _get_client_application(db: Session, app_id: uuid.UUID, user_id: uuid.UUID) -> Application:
    """Возвращает заявку текущего клиента или 404 NOT_FOUND (защита приватности данных)."""
    app = db.scalar(select(Application).where(Application.id == app_id))
    if app is None or app.created_by != user_id:
        raise ApiError(
            status_code=404,
            code=ErrorCode.NOT_FOUND,
            message="Заявка не найдена",
        )
    return app


def _verify_magic_bytes(content_type: str, chunk: bytes) -> None:
    expected_sig = _SIGNATURES.get(content_type)
    if expected_sig and not chunk.startswith(expected_sig):
        raise ApiError(
            status_code=422,
            code=ErrorCode.VALIDATION_ERROR,
            message=f"Сигнатура файла не соответствует заявленному MIME-типу ({content_type})",
            details=[{"field": "file", "message": "Неверная сигнатура (magic bytes) файла"}],
        )


@router.get("/{id}/documents", response_model=list[DocumentResponse])
def get_documents(
    id: uuid.UUID,
    current_user: TokenData = Depends(require_role(Role.CLIENT)),
    db: Session = Depends(get_db),
) -> list[DocumentResponse]:
    """Список документов по заявке клиента."""
    app = _get_client_application(db, id, current_user.user_id)
    docs = db.scalars(
        select(Document).where(Document.application_id == app.id).order_by(Document.uploaded_at.asc())
    ).all()
    return [DocumentResponse.model_validate(d) for d in docs]


@router.post("/{id}/documents", status_code=status.HTTP_201_CREATED, response_model=DocumentResponse)
def upload_document(
    id: uuid.UUID,
    doc_type: str = Form(...),
    file: UploadFile = File(...),
    current_user: TokenData = Depends(require_role(Role.CLIENT)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DocumentResponse:
    """Загрузить документ (только в статусах DRAFT и NEEDS_INFO; иначе 409 INVALID_TRANSITION)."""
    app = _get_client_application(db, id, current_user.user_id)

    # 1. Проверка допустимости статуса
    if app.status not in (ApplicationStatus.DRAFT.value, ApplicationStatus.NEEDS_INFO.value):
        raise ApiError(
            status_code=409,
            code=ErrorCode.INVALID_TRANSITION,
            message=f"Загрузка документов запрещена в статусе {app.status}. Разрешена только в DRAFT и NEEDS_INFO",
        )

    # 2. Валидация doc_type
    try:
        dtype = DocType(doc_type)
    except ValueError:
        raise ApiError(
            status_code=422,
            code=ErrorCode.VALIDATION_ERROR,
            message=f"Недопустимый тип документа: {doc_type}",
            details=[{"field": "doc_type", "message": f"Допустимые типы: {[e.value for e in DocType]}"}],
        )

    # 3. Валидация MIME-типа
    allowed_mimes = [m.strip().lower() for m in settings.doc_allowed_mime.split(",") if m.strip()]
    content_type = (file.content_type or "").lower()
    if content_type not in allowed_mimes:
        raise ApiError(
            status_code=422,
            code=ErrorCode.VALIDATION_ERROR,
            message=f"MIME-тип '{file.content_type}' не разрешён. Допустимые типы: {', '.join(allowed_mimes)}",
            details=[{"field": "file", "message": "Недопустимый MIME-тип"}],
        )

    # 4. Защита от Path Traversal, инъекций заголовков и небезопасных символов
    safe_filename = sanitize_filename(file.filename)


    doc_id = uuid.uuid4()
    app_upload_dir = settings.uploads_dir / str(app.id)
    app_upload_dir.mkdir(parents=True, exist_ok=True)
    target_file_path = app_upload_dir / str(doc_id)

    # 5. Потоковая запись с контролем размера, сигнатуры и sha256
    max_bytes = settings.doc_max_size_mb * 1024 * 1024
    total_bytes = 0
    hasher = hashlib.sha256()
    chunk_size = 64 * 1024
    first_chunk = True

    try:
        with open(target_file_path, "wb") as f_out:
            while True:
                chunk = file.file.read(chunk_size)
                if not chunk:
                    break

                if first_chunk:
                    first_chunk = False
                    _verify_magic_bytes(content_type, chunk)

                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    f_out.close()
                    target_file_path.unlink(missing_ok=True)
                    raise ApiError(
                        status_code=413,
                        code=ErrorCode.PAYLOAD_TOO_LARGE,
                        message=f"Размер файла превышает допустимый максимум {settings.doc_max_size_mb} МБ",
                    )

                hasher.update(chunk)
                f_out.write(chunk)

        if total_bytes == 0:
            target_file_path.unlink(missing_ok=True)
            raise ApiError(
                status_code=422,
                code=ErrorCode.VALIDATION_ERROR,
                message="Файл не может быть пустым",
                details=[{"field": "file", "message": "Файл пуст"}],
            )
    except ApiError:
        target_file_path.unlink(missing_ok=True)
        raise
    except Exception as e:
        target_file_path.unlink(missing_ok=True)
        raise ApiError(
            status_code=500,
            code=ErrorCode.INTERNAL_ERROR,
            message="Ошибка при сохранении файла документа",
        ) from e

    # 6. Сохранение в БД с компенсацией (удалением файла с диска при ошибке commit)
    doc = Document(
        id=doc_id,
        application_id=app.id,
        doc_type=dtype.value,
        filename=safe_filename,
        storage_path=str(target_file_path),
        size_bytes=total_bytes,
        sha256=hasher.hexdigest(),
        mime_type=content_type,
    )
    try:
        db.add(doc)
        db.commit()
        db.refresh(doc)
    except Exception as e:
        db.rollback()
        target_file_path.unlink(missing_ok=True)
        raise ApiError(
            status_code=500,
            code=ErrorCode.INTERNAL_ERROR,
            message="Ошибка при сохранении документа в базе данных",
        ) from e

    return DocumentResponse.model_validate(doc)


@router.get("/{id}/documents/{doc_id}/download")
def download_document(
    id: uuid.UUID,
    doc_id: uuid.UUID,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Скачать документ (владелец заявки или OPERATOR/ADMIN)."""
    app = db.scalar(select(Application).where(Application.id == id))
    if app is None:
        raise ApiError(status_code=404, code=ErrorCode.NOT_FOUND, message="Заявка не найдена")

    # Чужой клиент получает строго 404 NOT_FOUND (без 403)
    if current_user.role == Role.CLIENT.value:
        if app.created_by != current_user.user_id:
            raise ApiError(status_code=404, code=ErrorCode.NOT_FOUND, message="Заявка не найдена")
    elif current_user.role not in (Role.OPERATOR.value, Role.ADMIN.value):
        raise ApiError(status_code=403, code=ErrorCode.FORBIDDEN, message="Недостаточно прав")

    doc = db.scalar(select(Document).where(Document.id == doc_id, Document.application_id == app.id))
    if doc is None:
        raise ApiError(status_code=404, code=ErrorCode.NOT_FOUND, message="Документ не найден")

    file_path = Path(doc.storage_path)
    if not file_path.is_file():
        raise ApiError(status_code=404, code=ErrorCode.NOT_FOUND, message="Файл документа не найден на диске")

    def file_streamer():
        with open(file_path, "rb") as f:
            while chunk := f.read(64 * 1024):
                yield chunk

    return StreamingResponse(
        file_streamer(),
        media_type=doc.mime_type or "application/octet-stream",
        headers={
            "Content-Disposition": format_content_disposition(doc.filename),
            "Content-Length": str(doc.size_bytes),
        },
    )

