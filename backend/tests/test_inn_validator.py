"""Тесты валидации ИНН (алгоритм ФНС РФ и проверка форматов)."""
import pytest

from app.services.inn_validator import (
    is_valid_inn,
    is_valid_inn_checksum,
    is_valid_inn_format,
)

# Все 7 синтетических ИНН из docs/SCORING.md
SCORING_TEST_INNS_10 = [
    "0000001011",
    "0000002022",
    "0000003033",
    "0000004044",
    "0000005055",
    "0000006066",
]
SCORING_TEST_INNS_12 = [
    "000000070777",
]


@pytest.mark.parametrize("inn", SCORING_TEST_INNS_10)
def test_valid_10_digit_inns_from_scoring_doc(inn):
    assert is_valid_inn_format(inn, "OOO") is True
    assert is_valid_inn_checksum(inn) is True
    assert is_valid_inn(inn, "OOO") is True


@pytest.mark.parametrize("inn", SCORING_TEST_INNS_12)
def test_valid_12_digit_inns_from_scoring_doc(inn):
    assert is_valid_inn_format(inn, "IP") is True
    assert is_valid_inn_checksum(inn) is True
    assert is_valid_inn(inn, "IP") is True


@pytest.mark.parametrize(
    "bad_inn",
    [
        "0000001012",  # неверный 10-й разряд (должен быть 1)
        "0000002020",  # неверный 10-й разряд (должен быть 2)
        "000000070778",  # неверный 12-й разряд
        "000000070787",  # неверный 11-й разряд
        "1234567890",
        "7707083894",  # Сбербанк (настоящий, но здесь мы проверяем математику)
    ],
)
def test_invalid_checksums(bad_inn):
    # Если это настоящий ИНН Сбера 7707083893, то 7707083894 имеет неверную контрольную сумму
    if bad_inn == "7707083894":
        assert is_valid_inn_checksum(bad_inn) is False
    elif bad_inn.startswith("000000"):
        assert is_valid_inn_checksum(bad_inn) is False


def test_inn_format_without_checksum():
    # Для PUT /company проверяется только формат, чтобы воркер мог обнаружить INVALID_INN
    bad_checksum_inn = "0000001019"
    assert is_valid_inn_format(bad_checksum_inn, "OOO") is True
    assert is_valid_inn_checksum(bad_checksum_inn) is False
    assert is_valid_inn(bad_checksum_inn, "OOO") is False


@pytest.mark.parametrize(
    "invalid_format",
    [
        "12345",
        "123456789",  # 9 цифр
        "12345678901",  # 11 цифр
        "1234567890123",  # 13 цифр
        "000000101a",  # буквы
        "abcdefghij",
        "",
        None,
    ],
)
def test_invalid_formats(invalid_format):
    assert is_valid_inn_format(invalid_format) is False
    assert is_valid_inn_checksum(invalid_format) is False
    assert is_valid_inn(invalid_format) is False


def test_legal_form_mismatches():
    inn_10 = "0000001011"
    inn_12 = "000000070777"
    # 10 цифр для ИП недопустимо
    assert is_valid_inn_format(inn_10, "IP") is False
    assert is_valid_inn(inn_10, "IP") is False
    # 12 цифр для ООО недопустимо
    assert is_valid_inn_format(inn_12, "OOO") is False
    assert is_valid_inn(inn_12, "OOO") is False
