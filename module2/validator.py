"""
module2/validator.py — валидация ИНН по алгоритму контрольной суммы ФНС.

Алгоритм (Приказ ФНС России):
  10-значный (юрлицо): контрольная цифра — d[9]
    n = (2·d0 + 4·d1 + 10·d2 + 3·d3 + 5·d4 + 9·d5 + 4·d6 + 6·d7 + 8·d8) mod 11 mod 10
    valid: n == d[9]

  12-значный (ИП/физлицо): две контрольных цифры — d[10] и d[11]
    n11 = (7·d0 + 2·d1 + 4·d2 + 10·d3 + 3·d4 + 5·d5 + 9·d6 + 4·d7 + 6·d8 + 8·d9) mod 11 mod 10
    n12 = (3·d0 + 7·d1 + 2·d2 + 4·d3 + 10·d4 + 3·d5 + 5·d6 + 9·d7 + 4·d8 + 6·d9 + 8·d10) mod 11 mod 10
    valid: n11 == d[10] and n12 == d[11]
"""

from __future__ import annotations

_W10  = [2, 4, 10, 3, 5, 9, 4, 6, 8]
_W11  = [7, 2,  4, 10, 3, 5, 9, 4, 6, 8]
_W12  = [3, 7,  2,  4, 10, 3, 5, 9, 4, 6, 8]


def validate_inn(inn: str) -> bool:
    """
    Проверить корректность ИНН по контрольной сумме.

    Args:
        inn: строка — ИНН (10 или 12 цифр).

    Returns:
        True если ИНН синтаксически корректен и контрольная сумма верна.
    """
    if not isinstance(inn, str) or not inn.isdigit():
        return False

    if len(inn) == 10:
        return _check_10(inn)
    if len(inn) == 12:
        return _check_12(inn)
    return False


def get_inn_type(inn: str) -> str:
    """
    Определить тип субъекта по длине ИНН.

    Args:
        inn: строка — валидный ИНН.

    Returns:
        'ul' — юридическое лицо (10 цифр).
        'ip' — ИП / физическое лицо (12 цифр).

    Raises:
        ValueError: если длина ИНН не 10 и не 12.
    """
    if len(inn) == 10:
        return "ul"
    if len(inn) == 12:
        return "ip"
    raise ValueError(f"Недопустимая длина ИНН: {len(inn)}")


# ---------------------------------------------------------------------------
# Внутренние функции
# ---------------------------------------------------------------------------

def _check_10(inn: str) -> bool:
    d = [int(c) for c in inn]
    n = sum(_W10[i] * d[i] for i in range(9)) % 11 % 10
    return n == d[9]


def _check_12(inn: str) -> bool:
    d = [int(c) for c in inn]
    n11 = sum(_W11[i] * d[i] for i in range(10)) % 11 % 10
    if n11 != d[10]:
        return False
    n12 = sum(_W12[i] * d[i] for i in range(11)) % 11 % 10
    return n12 == d[11]
