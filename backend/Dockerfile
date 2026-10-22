# Контекст сборки — корень репозитория: docker build -f backend/Dockerfile .
FROM python:3.12.8-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /srv/backend

# зависимости по lock-файлу (слой кэшируется)
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/ ./
COPY docs/api /srv/docs/api
RUN chmod +x entrypoint.sh && useradd -r -u 10001 app && mkdir -p /data/uploads && chown -R app /data /srv
USER app
ENV PATH="/srv/backend/.venv/bin:$PATH"
EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
CMD ["api"]
