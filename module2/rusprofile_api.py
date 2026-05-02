"""
module2/rusprofile_api.py — получение данных об организации через Rusprofile.

Заменяет VBScript-парсер (innRequest.vbs, 2019) полноценной Python-реализацией.

Алгоритм (повторяет логику VBScript):
  1. GET https://www.rusprofile.ru/search?query={INN}   — страница поиска
  2. Извлечь canonical URL из <link rel="canonical">    — адрес страницы компании
  3. GET {canonical_url}?print=1                        — версия для печати с данными
  4. Разобрать HTML регулярными выражениями
"""

from __future__ import annotations

import html as html_module
import re
from datetime import date, datetime
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

_SEARCH_URL = "https://www.rusprofile.ru/search?query={query}"
_TIMEOUT    = 30  # секунды

_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:62.0) Gecko/20100101 Firefox/62.0",
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3",
    "Connection":      "keep-alive",
}

# Нормализация статусов: ищем стем в нижнем регистре, порядок важен.
# Более специфичные строки ("недействующ") идут перед общими ("действующ").
_STATUS_STEMS: list[tuple[str, str]] = [
    ("в процессе ликвидации", "liquidating"),
    ("ликвидируется",         "liquidating"),
    ("ликвидаци",             "liquidating"),  # ликвидация / ликвидации
    ("прекращен",             "liquidated"),   # прекращена/о деятельность
    ("недействующ",           "liquidated"),   # раньше "действующ"
    ("ликвидир",              "liquidated"),   # ликвидировано/а/н
    ("исключ",                "liquidated"),   # исключено/а из реестра
    ("реорганиза",            "reorganizing"),
    ("действующ",             "active"),       # действующий / действующая / действующее
]

# Русские месяцы в родительном падеже (как в Rusprofile: "16 августа 2002 г.")
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
            name          (str | None)  — наименование
            status        (str)         — 'active' | 'liquidated' | 'liquidating' | ...
            reg_date      (date | None) — дата регистрации
            address       (str | None)  — юридический адрес
            mass_address  (bool)        — False (Rusprofile не предоставляет)
            mass_director (bool)        — False (Rusprofile не предоставляет)
            capital       (float | None)— уставный капитал, руб.
            ogrn          (str | None)  — ОГРН / ОГРНИП
            entity_type   (str)         — 'ul' | 'ip'

    Raises:
        Exception: при ошибке. Сообщение на русском языке.
    """
    kv = _fetch_from_rusprofile(inn)
    return _parse_rusprofile(kv, inn)


# ---------------------------------------------------------------------------
# Загрузка HTML через Python requests (заменяет innRequest.vbs)
# ---------------------------------------------------------------------------

def _fetch_from_rusprofile(inn: str) -> dict[str, str]:
    """
    Два HTTP-запроса к Rusprofile (аналог логики VBScript innRequest.vbs):
      1. Поисковая страница → canonical URL компании
      2. {canonical_url}?print=1 → HTML с реквизитами

    Raises:
        Exception: ИНН не найден, таймаут, HTTP-ошибка.
    """
    search_url = _SEARCH_URL.format(query=inn)

    try:
        resp = requests.get(search_url, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
    except requests.Timeout:
        raise Exception(
            f"Rusprofile не ответил за {_TIMEOUT} секунд. Попробуйте позже."
        )
    except requests.HTTPError as e:
        raise Exception(f"Ошибка HTTP при обращении к Rusprofile: {e.response.status_code}")
    except requests.RequestException as e:
        raise Exception(f"Ошибка сети при обращении к Rusprofile: {e}")

    # Ищем canonical URL — адрес страницы конкретной компании
    canonical_url = _extract_canonical(resp.text)
    if not canonical_url:
        raise Exception(
            f"ИНН {inn} не найден на Rusprofile. Проверьте правильность ИНН."
        )

    # Запрашиваем версию для печати — она содержит полные реквизиты
    print_url = canonical_url.rstrip("/") + "?print=1"
    try:
        resp2 = requests.get(print_url, headers=_HEADERS, timeout=_TIMEOUT)
        resp2.raise_for_status()
    except requests.Timeout:
        raise Exception(
            f"Rusprofile не ответил за {_TIMEOUT} секунд. Попробуйте позже."
        )
    except requests.HTTPError as e:
        raise Exception(f"Ошибка HTTP при загрузке страницы компании: {e.response.status_code}")
    except requests.RequestException as e:
        raise Exception(f"Ошибка сети при загрузке страницы компании: {e}")

    kv = _parse_html_text(resp2.text, inn)

    if not kv.get("orgShortName") and not kv.get("orgFullName"):
        raise Exception(
            f"ИНН {inn} не найден на Rusprofile. Проверьте правильность ИНН."
        )

    return kv


def _extract_canonical(html_text: str) -> str | None:
    """
    Извлечь href из <link rel="canonical" href="...">.

    Rusprofile возвращает canonical URL страницы компании на поисковой выдаче.
    Если ИНН не найден — canonical ведёт на страницу поиска, не на компанию.
    """
    # Обе возможные последовательности атрибутов
    patterns = [
        r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']',
        r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']canonical["\']',
    ]
    for pat in patterns:
        m = re.search(pat, html_text, re.IGNORECASE)
        if m:
            url = m.group(1).strip()
            # Страница компании содержит /id/, /ip/ или числовой идентификатор
            # Поисковая выдача содержит /search или /find — ИНН не найден
            if "/search" in url or "/find" in url or url.endswith("rusprofile.ru/"):
                return None
            return url
    return None


# ---------------------------------------------------------------------------
# Парсинг HTML (текущая структура Rusprofile)
# ---------------------------------------------------------------------------

def _parse_html_text(text: str, inn: str) -> dict[str, str]:
    """
    Разобрать HTML-страницу Rusprofile (формат ?print=1).

    Текущая структура (2024–2025):
      <div class="company-name"><a>Краткое наименование</a></div>
      <div class="company-block">
        <table>
          <tr>
            <td class="dt"><div class="dt-text">Поле</div></td>
            <td>Значение</td>
          </tr>
        </table>
      </div>
    """
    result: dict[str, str] = {}

    # Краткое наименование
    m = re.search(
        r'class="company-name"[^>]*>.*?<a[^>]*>\s*(.*?)\s*</a>',
        text, re.DOTALL
    )
    if m:
        result["orgShortName"] = _clean_text(m.group(1))

    # Пары "Поле" → "Значение" из таблиц dt/td
    pairs = re.findall(
        r'<div class="dt-text">(.*?)</div>\s*</td>\s*<td[^>]*>(.*?)</td>',
        text, re.DOTALL,
    )

    seen: set[str] = set()
    for k_raw, v_raw in pairs:
        k = _clean_text(k_raw).strip()
        v = _clean_text(v_raw).strip()
        if not k or not v:
            continue
        _map_field(k, v, result, seen)

    # Тип субъекта из длины ИНН (надёжнее, чем из HTML)
    result.setdefault(
        "type",
        "Индивидуальный предприниматель" if len(inn) == 12 else "Организация",
    )

    return result


def _map_field(k: str, v: str, result: dict, seen: set) -> None:
    """Сопоставить поле из dt-text с ключом внутреннего словаря."""
    k_lo = k.lower()

    def _once(key: str, value: str) -> None:
        """Записать значение только один раз (первое вхождение)."""
        if key not in seen:
            seen.add(key)
            result[key] = value

    if "полное наименование" in k_lo or "наименование" == k_lo:
        _once("orgFullName", v)

    elif k_lo == "статус":
        _once("orgStatus", v)

    elif "юридический адрес" in k_lo or "адрес регистрации" in k_lo:
        _once("orgAddress", v)

    elif "уставный капитал" in k_lo:
        # "67 760 844 000,00 р." → "67760844000"
        cap = re.sub(r"[^\d,]", "", v).replace(",", ".")
        cap = re.sub(r"\.00$", "", cap)
        _once("commonBaseFunds", cap)

    elif k_lo == "огрн":
        _once("commonOGRN", v)

    elif k_lo == "огрнип":
        _once("commonOGRNIP", v)
        result["type"] = "Индивидуальный предприниматель"

    elif "дата регистрации" in k_lo:
        _once("commonRegDate", _russian_date_to_dmy(v))

    elif k_lo in ("фио", "фио индивидуального предпринимателя", "имя"):
        if "orgFullName" not in seen:
            seen.add("orgFullName")
            result["orgFullName"] = v

    elif "основной вид деятельности" in k_lo:
        _once("okved", v)


def _clean_text(raw: str) -> str:
    """Убрать HTML-теги и декодировать HTML-сущности."""
    no_tags = re.sub(r"<[^>]+>", " ", raw)
    decoded  = html_module.unescape(no_tags)
    return " ".join(decoded.split())


def _russian_date_to_dmy(s: str) -> str:
    """Преобразовать '16 августа 2002 г.' → '16.08.2002'. При ошибке — оригинал."""
    m = re.match(r"(\d{1,2})\s+(\S+)\s+(\d{4})", s.strip())
    if not m:
        return s
    day, month_ru, year = m.groups()
    month = _MONTHS_RU.get(month_ru.lower())
    if not month:
        return s
    return f"{int(day):02d}.{month}.{year}"


# ---------------------------------------------------------------------------
# Нормализация полей
# ---------------------------------------------------------------------------

def _parse_rusprofile(kv: dict[str, str], inn: str) -> dict:
    """Нормализовать поля KV-словаря из HTML → стандартный dict контрагента."""
    name = _str_or_none(kv.get("orgShortName")) or _str_or_none(kv.get("orgFullName"))

    status_raw = kv.get("orgStatus", "").strip()
    status = _normalize_status(status_raw) if status_raw else "active"

    ogrn = _str_or_none(kv.get("commonOGRN")) or _str_or_none(kv.get("commonOGRNIP"))

    type_raw = kv.get("type", "").lower()
    if "индивидуальный" in type_raw or len(inn) == 12:
        entity_type = "ip"
    else:
        entity_type = "ul"

    capital: float | None = None
    capital_raw = kv.get("commonBaseFunds", "").strip()
    if capital_raw:
        try:
            capital = float(capital_raw.replace(" ", ""))
        except ValueError:
            pass

    return {
        "name":          name,
        "status":        status,
        "reg_date":      _parse_date(kv.get("commonRegDate", "")),
        "address":       _str_or_none(kv.get("orgAddress")),
        "ogrn":          ogrn,
        "entity_type":   entity_type,
        "mass_address":  False,
        "mass_director": False,
        "capital":       capital,
    }


# ---------------------------------------------------------------------------
# Вспомогательные функции (используются в тестах напрямую)
# ---------------------------------------------------------------------------

def _normalize_status(raw: str) -> str:
    """Нормализовать русский статус к внутреннему коду (stem-matching)."""
    key = raw.lower().strip()
    for stem, code in _STATUS_STEMS:
        if stem in key:
            return code
    return raw or "unknown"


def _parse_date(raw: str) -> date | None:
    """Разбирает dd.mm.yyyy или yyyy-mm-dd → date."""
    raw = raw.strip()
    if not raw:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _str_or_none(value: Any) -> str | None:
    s = (value or "").strip() if isinstance(value, str) else ""
    return s or None
