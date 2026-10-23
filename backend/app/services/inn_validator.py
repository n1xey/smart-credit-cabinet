"""Валидация ИНН (алгоритм Федеральной налоговой службы РФ).

Используется воркером конвейера на этапе DATA_CHECK для выявления стоп-фактора INVALID_INN.
В API (PUT /company) проверяется только длина и базовый синтаксис (ООО: 10 цифр, ИП: 12 цифр),
чтобы не блокировать тестовые сценарии отказа по невалидному ИНН.
"""
import re

_INN_REGEX = re.compile(r"^\d{10}(\d{2})?$")
_W10 = (2, 4, 10, 3, 5, 9, 4, 6, 8)
_W11 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
_W12 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)


def is_valid_inn_format(inn: str, legal_form: str | None = None) -> bool:
    """Проверяет синтаксический формат ИНН (цифры, длина 10 или 12) и соответствие legal_form."""
    if not isinstance(inn, str) or not _INN_REGEX.match(inn):
        return False
    if legal_form == "OOO" and len(inn) != 10:
        return False
    if legal_form == "IP" and len(inn) != 12:
        return False
    return True


def is_valid_inn_checksum(inn: str) -> bool:
    """Проверяет контрольные суммы ИНН по алгоритму ФНС РФ.

    - Для 10-значного ИНН (ЮЛ): контрольный 10-й разряд.
    - Для 12-значного ИНН (ФЛ/ИП): контрольные 11-й и 12-й разряды.
    """
    if not isinstance(inn, str) or not inn.isdigit():
        return False

    digits = [int(c) for c in inn]

    if len(digits) == 10:
        checksum = sum(d * w for d, w in zip(digits[:9], _W10)) % 11 % 10
        return checksum == digits[9]

    if len(digits) == 12:
        checksum11 = sum(d * w for d, w in zip(digits[:10], _W11)) % 11 % 10
        if checksum11 != digits[10]:
            return False
        checksum12 = sum(d * w for d, w in zip(digits[:11], _W12)) % 11 % 10
        return checksum12 == digits[11]

    return False


def is_valid_inn(inn: str, legal_form: str | None = None) -> bool:
    """Полная валидация ИНН: синтаксис, соответствие форме и контрольная сумма ФНС."""
    if not is_valid_inn_format(inn, legal_form):
        return False
    return is_valid_inn_checksum(inn)
