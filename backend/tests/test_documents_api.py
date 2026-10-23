"""Тесты API документов и заглушки /feed."""
import io
import uuid

import pytest
from sqlalchemy import select

from app.auth.security import create_access_token
from app.config import get_settings
from app.enums import ApplicationStatus, DocType, LegalForm, Role
from app.models.tables import Application, Company, Document, User
from tests.conftest import _make_user, auth_headers


@pytest.fixture
def client_with_company(db_session, client_user):
    comp = Company(
        id=uuid.uuid4(),
        owner_id=client_user.id,
        inn="7707083893",
        name="ООО Документ Сервис",
        legal_form=LegalForm.OOO.value,
    )
    db_session.add(comp)
    db_session.commit()
    db_session.refresh(comp)
    return client_user, comp


@pytest.fixture
def other_client_with_company(db_session):
    other_user = _make_user(db_session, "other_client@example.com", Role.CLIENT.value, "Чужой Клиент")
    comp = Company(
        id=uuid.uuid4(),
        owner_id=other_user.id,
        inn="7707083894",
        name="ООО Другая Компания",
        legal_form=LegalForm.OOO.value,
    )
    db_session.add(comp)
    db_session.commit()
    db_session.refresh(comp)
    return other_user, comp


@pytest.fixture
def admin_user(db_session):
    return _make_user(db_session, "admin@example.com", Role.ADMIN.value, "Администратор")


@pytest.fixture
def draft_application(db_session, client_with_company, seed_products):
    user, company = client_with_company
    app = Application(
        id=uuid.uuid4(),
        company_id=company.id,
        created_by=user.id,
        product_code="WORKING_CAPITAL",
        amount_rub=2_000_000,
        term_months=12,
        purpose="Пополнение оборотных средств",
        status=ApplicationStatus.DRAFT.value,
        version=1,
    )
    db_session.add(app)
    db_session.commit()
    db_session.refresh(app)
    return app


def test_feed_endpoint(api_client, client_user, operator_user):
    # 1. 401 для неавторизованного
    resp = api_client.get("/api/v1/feed")
    assert resp.status_code == 401

    # 2. 403 для оператора
    resp = api_client.get("/api/v1/feed", headers=auth_headers(operator_user))
    assert resp.status_code == 403

    # 3. 200 [] для клиента
    resp = api_client.get("/api/v1/feed", headers=auth_headers(client_user))
    assert resp.status_code == 200
    assert resp.json() == []


def test_upload_document_success_and_traversal_protection(api_client, client_user, draft_application, db_session):
    # Валидный PDF с попыткой path traversal в имени файла
    pdf_content = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"
    files = {
        "file": ("../../../../etc/passwd", io.BytesIO(pdf_content), "application/pdf"),
    }
    data = {
        "doc_type": DocType.FINANCIAL_STATEMENT.value,
    }

    resp = api_client.post(
        f"/api/v1/applications/{draft_application.id}/documents",
        data=data,
        files=files,
        headers=auth_headers(client_user),
    )
    assert resp.status_code == 201
    doc_data = resp.json()
    assert doc_data["doc_type"] == DocType.FINANCIAL_STATEMENT.value
    # Имя файла очищено от ../
    assert doc_data["filename"] == "passwd"
    assert doc_data["size_bytes"] == len(pdf_content)

    # Проверяем запись в БД и файл на диске
    db_doc = db_session.scalar(select(Document).where(Document.id == uuid.UUID(doc_data["id"])))
    assert db_doc is not None
    assert db_doc.filename == "passwd"
    assert ".." not in db_doc.storage_path
    assert f"{draft_application.id}" in db_doc.storage_path

    with open(db_doc.storage_path, "rb") as f:
        assert f.read() == pdf_content


def test_upload_document_validates_mime_and_magic_bytes(api_client, client_user, draft_application):
    # 1. Неразрешённый MIME-тип
    resp = api_client.post(
        f"/api/v1/applications/{draft_application.id}/documents",
        data={"doc_type": DocType.SUPPLIER_INVOICE.value},
        files={"file": ("invoice.txt", io.BytesIO(b"simple text"), "text/plain")},
        headers=auth_headers(client_user),
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    # 2. MIME application/pdf, но битые магические байты
    resp = api_client.post(
        f"/api/v1/applications/{draft_application.id}/documents",
        data={"doc_type": DocType.FINANCIAL_STATEMENT.value},
        files={"file": ("fake.pdf", io.BytesIO(b"NOT_A_PDF_CONTENT"), "application/pdf")},
        headers=auth_headers(client_user),
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    # 3. MIME image/png, но не PNG
    resp = api_client.post(
        f"/api/v1/applications/{draft_application.id}/documents",
        data={"doc_type": DocType.OTHER.value},
        files={"file": ("fake.png", io.BytesIO(b"NOT_A_PNG"), "image/png")},
        headers=auth_headers(client_user),
    )
    assert resp.status_code == 422

    # 4. Пустой файл (0 байт)
    resp = api_client.post(
        f"/api/v1/applications/{draft_application.id}/documents",
        data={"doc_type": DocType.OTHER.value},
        files={"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")},
        headers=auth_headers(client_user),
    )
    assert resp.status_code == 422

    # 5. Неизвестный doc_type
    resp = api_client.post(
        f"/api/v1/applications/{draft_application.id}/documents",
        data={"doc_type": "UNKNOWN_TYPE"},
        files={"file": ("test.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
        headers=auth_headers(client_user),
    )
    assert resp.status_code == 422


def test_upload_document_status_restriction(api_client, client_user, draft_application, db_session):
    # Переводим заявку в статус SUBMITTED
    draft_application.status = ApplicationStatus.SUBMITTED.value
    db_session.commit()

    resp = api_client.post(
        f"/api/v1/applications/{draft_application.id}/documents",
        data={"doc_type": DocType.FINANCIAL_STATEMENT.value},
        files={"file": ("fin.pdf", io.BytesIO(b"%PDF-1.4 sample"), "application/pdf")},
        headers=auth_headers(client_user),
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "INVALID_TRANSITION"

    # Разрешено в NEEDS_INFO
    draft_application.status = ApplicationStatus.NEEDS_INFO.value
    db_session.commit()

    resp = api_client.post(
        f"/api/v1/applications/{draft_application.id}/documents",
        data={"doc_type": DocType.FINANCIAL_STATEMENT.value},
        files={"file": ("fin.pdf", io.BytesIO(b"%PDF-1.4 sample"), "application/pdf")},
        headers=auth_headers(client_user),
    )
    assert resp.status_code == 201


def test_upload_document_size_limit(api_client, client_user, draft_application, monkeypatch):
    # Имитируем лимит 1 МБ
    settings = get_settings()
    monkeypatch.setattr(settings, "doc_max_size_mb", 1)

    large_content = b"%PDF-" + b"0" * (1024 * 1024 + 100)
    resp = api_client.post(
        f"/api/v1/applications/{draft_application.id}/documents",
        data={"doc_type": DocType.FINANCIAL_STATEMENT.value},
        files={"file": ("large.pdf", io.BytesIO(large_content), "application/pdf")},
        headers=auth_headers(client_user),
    )
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_list_and_download_documents_and_404_isolation(
    api_client, client_user, other_client_with_company, operator_user, admin_user, draft_application
):
    other_user, _ = other_client_with_company

    # Загружаем валидный PNG
    png_content = b"\x89PNG\r\n\x1a\n" + b"sample png data"
    upload_resp = api_client.post(
        f"/api/v1/applications/{draft_application.id}/documents",
        data={"doc_type": DocType.OTHER.value},
        files={"file": ("scan.png", io.BytesIO(png_content), "image/png")},
        headers=auth_headers(client_user),
    )
    assert upload_resp.status_code == 201
    doc_id = upload_resp.json()["id"]

    # 1. Список документов владельцем
    list_resp = api_client.get(
        f"/api/v1/applications/{draft_application.id}/documents",
        headers=auth_headers(client_user),
    )
    assert list_resp.status_code == 200
    docs = list_resp.json()
    assert len(docs) == 1
    assert docs[0]["id"] == doc_id

    # 2. Чужой клиент получает 404 на список документов
    other_list_resp = api_client.get(
        f"/api/v1/applications/{draft_application.id}/documents",
        headers=auth_headers(other_user),
    )
    assert other_list_resp.status_code == 404
    assert other_list_resp.json()["error"]["code"] == "NOT_FOUND"

    # 3. Скачивание владельцем
    dl_resp = api_client.get(
        f"/api/v1/applications/{draft_application.id}/documents/{doc_id}/download",
        headers=auth_headers(client_user),
    )
    assert dl_resp.status_code == 200
    assert dl_resp.content == png_content

    # 4. Скачивание оператором и админом разрешено
    op_dl_resp = api_client.get(
        f"/api/v1/applications/{draft_application.id}/documents/{doc_id}/download",
        headers=auth_headers(operator_user),
    )
    assert op_dl_resp.status_code == 200
    assert op_dl_resp.content == png_content

    admin_dl_resp = api_client.get(
        f"/api/v1/applications/{draft_application.id}/documents/{doc_id}/download",
        headers=auth_headers(admin_user),
    )
    assert admin_dl_resp.status_code == 200
    assert admin_dl_resp.content == png_content

    # 5. Чужой клиент получает строго 404 (без 403) на скачивание
    other_dl_resp = api_client.get(
        f"/api/v1/applications/{draft_application.id}/documents/{doc_id}/download",
        headers=auth_headers(other_user),
    )
    assert other_dl_resp.status_code == 404
    assert other_dl_resp.json()["error"]["code"] == "NOT_FOUND"

    # 6. Несуществующий doc_id -> 404
    fake_doc_id = uuid.uuid4()
    not_found_resp = api_client.get(
        f"/api/v1/applications/{draft_application.id}/documents/{fake_doc_id}/download",
        headers=auth_headers(client_user),
    )
    assert not_found_resp.status_code == 404
