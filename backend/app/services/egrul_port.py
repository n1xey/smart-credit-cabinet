"""Интерфейс-порт и тестовая заглушка для интеграции с ЕГРЮЛ/ЕГРИП.

Согласно CLAUDE.md модуль backend/app/integrations принадлежит Участнику 4.
Участник 2 определяет Protocol для вызова ЕГРЮЛ и заглушку для тестов.
"""
from typing import Protocol

from app.api.schemas.company import CompanyInput


class EgrulClientProtocol(Protocol):
    """Протокол взаимодействия с сервисом ЕГРЮЛ/ЕГРИП."""

    def lookup(self, inn: str) -> CompanyInput | None:
        """Поиск компании по ИНН. Возвращает CompanyInput или None, если запись не найдена."""
        ...


class StubEgrulClient:
    """Тестовая заглушка реестра ЕГРЮЛ без подмены реального сбоя выдуманными данными."""

    def __init__(self, registry: dict[str, CompanyInput] | None = None) -> None:
        self._registry: dict[str, CompanyInput] = registry or {}

    def register(self, inn: str, data: CompanyInput) -> None:
        self._registry[inn] = data

    def lookup(self, inn: str) -> CompanyInput | None:
        return self._registry.get(inn)


_default_egrul_client = StubEgrulClient()


def get_egrul_client() -> EgrulClientProtocol:
    """FastAPI dependency для получения клиента ЕГРЮЛ."""
    return _default_egrul_client
