# Backend (Участник 2)

## Локальный запуск без Docker
```bash
cd backend
uv sync                      # ставит зависимости, создаёт uv.lock (закоммитить!)
export DATABASE_URL=postgresql+psycopg://credit:credit@localhost:5432/credit
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```
Swagger UI: http://localhost:8000/docs · health: `/health/live`, `/health/ready`.

## Тесты
```bash
cd backend && uv run pytest
```

## Зависимости для THIRD_PARTY_NOTICES.md (передать Участнику 1)
fastapi, uvicorn, sqlalchemy, alembic, psycopg (binary), pydantic, pydantic-settings, pyyaml, python-multipart; dev: pytest, httpx.
Добавлено в задаче 3 (auth): `bcrypt>=4.0,<5` (Apache-2.0), `python-jose[cryptography]>=3.3,<4` (MIT), `email-validator>=2.1,<3` (MIT/BSD).
Транзитивные зависимости python-jose: `cryptography` (Apache-2.0/BSD), `ecdsa` (MIT), `pyasn1` (BSD), `rsa` (Apache-2.0), `six` (MIT).
Образы: python:3.12.8-slim-bookworm, ghcr.io/astral-sh/uv:0.5.11.
