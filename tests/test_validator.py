"""
tests/test_validator.py — тесты валидации ИНН (module2/validator.py).
"""

import pytest
from module2.validator import validate_inn, get_inn_type

# ---------------------------------------------------------------------------
# 10 валидных ИНН
# ---------------------------------------------------------------------------

# 8 валидных 10-значных (юрлица): 5 реальных компаний + 3 вычисленных
VALID_10 = [
    "7707083893",   # Сбербанк
    "7736207543",   # Яндекс
    "7702070139",   # ВТБ
    "7710474375",   # Лукойл
    "7740000076",   # МТС
    "1234567894",   # вычисленный
    "9876543210",   # вычисленный
    "7707000008",   # вычисленный
]

# 2 валидных 12-значных (ИП / физлица)
VALID_12 = [
    "500100732259",
    "123456789047",
]

VALID_ALL = VALID_10 + VALID_12  # всего 10


@pytest.mark.parametrize("inn", VALID_ALL)
def test_validate_inn_valid(inn):
    assert validate_inn(inn) is True, f"Expected valid: {inn}"


# ---------------------------------------------------------------------------
# 5 невалидных ИНН
# ---------------------------------------------------------------------------

INVALID_INNS = [
    "7707083890",   # неверная контрольная цифра (Сбербанк с +7 → 0)
    "1234567890",   # неверная контрольная цифра
    "123456789",    # 9 цифр — слишком короткий
    "12345678901",  # 11 цифр — неподдерживаемая длина
    "abcdefghij",   # не цифры
]


@pytest.mark.parametrize("inn", INVALID_INNS)
def test_validate_inn_invalid(inn):
    assert validate_inn(inn) is False, f"Expected invalid: {inn}"


# ---------------------------------------------------------------------------
# get_inn_type
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("inn", VALID_10)
def test_get_inn_type_ul(inn):
    assert get_inn_type(inn) == "ul"


@pytest.mark.parametrize("inn", VALID_12)
def test_get_inn_type_ip(inn):
    assert get_inn_type(inn) == "ip"


def test_get_inn_type_raises_on_bad_length():
    with pytest.raises(ValueError):
        get_inn_type("123456789")      # 9 цифр

    with pytest.raises(ValueError):
        get_inn_type("12345678901")    # 11 цифр


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_validate_inn_none():
    assert validate_inn(None) is False  # type: ignore[arg-type]


def test_validate_inn_empty():
    assert validate_inn("") is False


def test_validate_inn_with_spaces():
    assert validate_inn(" 7707083893") is False
    assert validate_inn("7707083893 ") is False
