"""
module2/rusprofile_api.py — получение данных об организации / ИП по ИНН через Rusprofile.

Алгоритм:
  1. GET https://www.rusprofile.ru/search?query={INN} с allow_redirects=True
     Rusprofile автоматически редиректит на страницу компании.
     resp.url содержит финальный URL — используем его вместо canonical-тега.
     (canonical отсутствует у юрлиц, что и было причиной бага)
  2. GET {final_url}?print=1 — версия для печати с реквизитами
  3. Парсинг HTML: ключ в <div class="dt-text">, значение во втором <td> той же <tr>
"""

from __future__ import annotations

import html as html_module
import re
from datetime import date
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

_TIMEOUT = 30

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

_STATUS_STEMS: list[tuple[str, str]] = [
    ("в процессе ликвидации", "liquidating"),
    ("ликвидируется",         "liquidating"),
    ("ликвидаци",             "liquidating"),
    ("прекращен",             "liquidated"),
    ("недействующ",           "liquidated"),
    ("ликвидир",              "liquidated"),
    ("исключ",                "liquidated"),
    ("реорганиза",            "reorganizing"),
    ("действующ",             "active"),
]

_MONTHS_RU: dict[str, str] = {
    "января":   "01", "февраля":  "02", "марта":    "03",
    "апреля":   "04", "мая":      "05", "июня":     "06",
    "июля":     "07", "августа":  "08", "сентября": "09",
    "октября":  "10", "ноября":   "11", "декабря":  "12",
}

# ---------------------------------------------------------------------------
# Публичный API
# ---------------------------------------------------------------------------

def get_entity_by_inn(inn: str) -> dict:
    """
    Получить сведения об организации / ИП по ИНН через Rusprofile.

    Returns:
        dict с ключами:
            name         (str | None)   — наименование / ФИО ИП
            status       (str)          — 'active' | 'liquidated' | 'liquidating' | ...
            reg_date     (date | None)  — дата регистрации
            address      (str | None)   — юридический адрес
            mass_address (bool)         — False (Rusprofile не предоставляет)
            mass_director(bool)         — False (Rusprofile не предоставляет)
            capital      (float | None) — уставный капитал, руб.
            ogrn         (str | None)   — ОГРН / ОГРНИП
            entity_type  (str)          — 'ul' | 'ip'

    Raises:
        Exception: ИНН не найден, таймаут, HTTP-ошибка.
    """
    entity_type, kv = _fetch_from_rusprofile(inn)
    return _build_result(kv, entity_type)


# ---------------------------------------------------------------------------
# Загрузка HTML
# ---------------------------------------------------------------------------

def _fetch_from_rusprofile(inn: str) -> tuple[str, dict[str, str]]:
    """
    Два HTTP-запроса к Rusprofile:
      1. Поисковая страница → resp.url (финальный URL после редиректа)
      2. {final_url}?print=1 → HTML с реквизитами

    Возвращает (entity_type, kv).
    """
    search_url = f"https://www.rusprofile.ru/search?query={inn.strip()}"

    try:
        resp = requests.get(
            search_url, headers=_HEADERS, timeout=_TIMEOUT, allow_redirects=True
        )
        resp.raise_for_status()
    except requests.Timeout:
        raise Exception(f"Rusprofile не ответил за {_TIMEOUT} секунд. Попробуйте позже.")
    except requests.HTTPError as e:
        raise Exception(f"Ошибка HTTP при обращении к Rusprofile: {e.response.status_code}")
    except requests.RequestException as e:
        raise Exception(f"Ошибка сети при обращении к Rusprofile: {e}")

    final_url = resp.url

    # Если редирект не произошёл — остались на странице поиска, ИНН не найден
    if (
        "/search" in final_url
        or "/find" in final_url
        or final_url.rstrip("/").endswith("rusprofile.ru")
    ):
        raise Exception(f"ИНН {inn} не найден на Rusprofile. Проверьте правильность ИНН.")

    # Тип сущности по URL: /ip/ — ИП, /id/ — юрлицо
    entity_type = "ip" if "/ip/" in final_url else "ul"

    # Запрашиваем версию для печати — полные реквизиты в таблице
    print_url = final_url.rstrip("/") + "?print=1"

    try:
        resp2 = requests.get(print_url, headers=_HEADERS, timeout=_TIMEOUT)
        resp2.raise_for_status()
    except requests.Timeout:
        raise Exception(f"Rusprofile не ответил за {_TIMEOUT} секунд. Попробуйте позже.")
    except requests.HTTPError as e:
        raise Exception(f"Ошибка HTTP при загрузке страницы компании: {e.response.status_code}")
    except requests.RequestException as e:
        raise Exception(f"Ошибка сети при загрузке страницы компании: {e}")

    kv = _parse_table(resp2.text)
    if not kv:
        raise Exception(f"ИНН {inn} не найден на Rusprofile. Проверьте правильность ИНН.")

    return entity_type, kv


# ---------------------------------------------------------------------------
# Парсинг HTML-таблицы реквизитов
# ---------------------------------------------------------------------------

def _strip_tags(s: str) -> str:
    """Удалить HTML-теги и decode HTML-entities."""
    return html_module.unescape(re.sub(r'<[^>]+>', '', s)).strip()


def _parse_table(html_text: str) -> dict[str, str]:
    """
    Разобрать HTML страницы ?print=1.

    Rusprofile хранит реквизиты в строках <tr>:
      - ключ находится внутри <div class="dt-text">...</div>
      - значение находится во втором <td> (без класса dt) той же строки

    Возвращает словарь {ключ_в_нижнем_регистре: значение}.
    """
    kv: dict[str, str] = {}
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html_text, re.DOTALL | re.IGNORECASE)

    for row in rows:
        key_m = re.search(
            r'class=["\']dt-text["\'][^>]*>(.*?)</div>', row, re.DOTALL | re.IGNORECASE
        )
        # Значение — первый <td> без класса 'dt'
        val_tds = re.findall(
            r'<td(?![^>]*class=["\'][^"\']*\bdt\b)[^>]*>(.*?)</td>',
            row, re.DOTALL | re.IGNORECASE
        )
        if key_m and val_tds:
            key = _strip_tags(key_m.group(1)).lower().rstrip(":")
            val = _strip_tags(val_tds[0])
            if key and val:
                kv[key] = val

    return kv


# ---------------------------------------------------------------------------
# Формирование результата
# ---------------------------------------------------------------------------

def _build_result(kv: dict[str, str], entity_type: str) -> dict:
    """
    Преобразовать словарь kv из таблицы Rusprofile в единый формат системы.
    """
    # --- Наименование ---
    if entity_type == "ip":
        fio = kv.get("фио")
        name = f"ИП {fio}" if fio else None
    else:
        name = (
            kv.get("краткое наименование")
            or kv.get("полное наименование")
            or kv.get("наименование")
        )

    # --- Статус ---
    status_raw = (kv.get("статус") or "").lower()
    status = "active"
    for stem, normalized in _STATUS_STEMS:
        if stem in status_raw:
            status = normalized
            break

    # --- Дата регистрации ---
    reg_str = kv.get("дата регистрации") or ""
    reg_date = _parse_date_ru(reg_str)

    # --- Адрес ---
    address = (
        kv.get("юридический адрес")
        or kv.get("адрес")
        or kv.get("место нахождения")
        or None
    )

    # --- Уставный капитал (только для юрлиц) ---
    capital: float | None = None
    if entity_type == "ul":
        capital = _parse_capital(kv.get("уставный капитал") or "")

    # --- ОГРН / ОГРНИП ---
    ogrn = kv.get("огрнип") or kv.get("огрн") or None

    return {
        "name":           name,
        "status":         status,
        "reg_date":       reg_date,
        "address":        address,
        "mass_address":   False,
        "mass_director":  False,
        "capital":        capital,
        "ogrn":           ogrn,
        "entity_type":    entity_type,
    }


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _parse_date_ru(date_str: str) -> date | None:
    """Разобрать дату вида '13 октября 2025 г.' или '16 августа 2002 г.'"""
    date_str = date_str.strip().rstrip(".").rstrip("г").strip()
    parts = date_str.split()
    if len(parts) == 3:
        day, month_ru, year = parts
        month = _MONTHS_RU.get(month_ru.lower())
        if month:
            try:
                return date(int(year), int(month), int(day))
            except ValueError:
                pass
    # Запасной вариант: DD.MM.YYYY
    m = re.search(r'(\d{2})\.(\d{2})\.(\d{4})', date_str)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass
    return None


def _parse_capital(capital_str: str) -> float | None:
    """Разобрать '67 760 844 000,00 р.' → 67760844000.0"""
    if not capital_str:
        return None
    # Убираем всё кроме цифр, запятой и точки
    cleaned = re.sub(r'[^\d,.]', '', capital_str).replace(',', '.')
    # Если несколько точек — оставляем только последнюю как десятичный разделитель
    parts = cleaned.split('.')
    if len(parts) > 2:
        cleaned = ''.join(parts[:-1]) + '.' + parts[-1]
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None
