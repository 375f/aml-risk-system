"""
module1/parser.py — чтение банковских выписок CSV/XLSX с автомаппингом колонок.

Поддерживаемые форматы:
  Формат А:     Дата | Назначение | Дебет | Кредит | Контрагент | ИНН
  Формат Б:     Дата | Сумма | Тип операции | Описание | Контрагент
  Формат Альфа: Альфа-Банк CSV (d_c, sum_rur, text70, plat_*/pol_*)

Возвращает DataFrame с колонками: date, amount, type, description, counterparty, inn
"""

import io
import re
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# Исключения
# ---------------------------------------------------------------------------

class ParseError(Exception):
    """Ошибка парсинга банковской выписки."""


class ColumnMappingError(ParseError):
    """Не удалось определить обязательные колонки файла."""


# ---------------------------------------------------------------------------
# Словарь синонимов заголовков (canonical → list[alias])
# Учитывает вариации заголовков разных банков (Сбер, Тинькофф, ВТБ, Альфа…)
# ---------------------------------------------------------------------------

_ALIASES: dict[str, list[str]] = {
    "date": [
        "дата", "date", "дата операции", "дата проводки", "дата транзакции",
        "дата платежа", "дата поступления", "дата списания", "дата выписки",
        "дата расчета", "дата документа", "дата совершения",
    ],
    "amount": [
        "сумма", "amount", "сумма операции", "сумма платежа", "sum",
        "сумма транзакции", "оборот", "итого", "сумма (руб.)", "сумма руб",
        "сумма в валюте счёта",
    ],
    "debit": [
        "дебет", "debit", "расход", "списание", "сумма расхода",
        "сумма списания", "дебетовый оборот", "дебет (руб.)",
        "расходы", "дт", "дт.", "сумма дебет",
    ],
    "credit": [
        "кредит", "credit", "приход", "поступление", "сумма прихода",
        "сумма поступления", "кредитовый оборот", "кредит (руб.)",
        "поступления", "кт", "кт.", "сумма кредит",
    ],
    "type": [
        "тип", "type", "тип операции", "вид операции", "тип транзакции",
        "направление", "категория", "вид", "операция",
    ],
    "description": [
        "назначение", "description", "назначение платежа", "описание",
        "описание операции", "примечание", "комментарий", "memo",
        "наименование операции", "основание", "сведения о платеже",
        "детали операции", "детали платежа", "информация о платеже",
    ],
    "counterparty": [
        "контрагент", "counterparty", "получатель", "плательщик",
        "наименование контрагента", "наименование получателя",
        "наименование плательщика", "отправитель", "корреспондент",
        "партнёр", "организация", "клиент",
    ],
    "inn": [
        "инн", "inn", "инн контрагента", "инн получателя",
        "инн плательщика", "инн/кпп", "иннкпп", "инн контр.", "tin",
    ],
}

# Маркеры типа операции в текстовых значениях
_DEBIT_MARKERS = frozenset(
    {"расход", "списание", "debit", "дебет", "out", "расходы",
     "дт", "-", "outgoing", "дебетовая", "вычет", "расх", "d"}
)
_CREDIT_MARKERS = frozenset(
    {"приход", "поступление", "credit", "кредит", "in", "поступления",
     "кт", "+", "incoming", "кредитовая", "зачисление", "прих", "c"}
)

# Сигнатурные колонки формата Альфа-Банка
_ALFABANK_SIGNATURE = frozenset({"d_c", "sum_rur", "text70"})

# Форматы дат, с которыми чаще всего приходят выписки
_DATE_FORMATS = [
    "%d.%m.%Y",
    "%d/%m/%Y",
    "%Y-%m-%d",
    "%d.%m.%Y %H:%M",
    "%d.%m.%Y %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
    "%Y%m%d",
]


# ---------------------------------------------------------------------------
# Публичный интерфейс
# ---------------------------------------------------------------------------

def parse_statement(file) -> tuple[pd.DataFrame, date | None, date | None]:
    """
    Разобрать банковскую выписку.

    Args:
        file: путь к файлу (str/Path) или file-like объект (Streamlit UploadedFile)

    Returns:
        (df, date_from, date_to)
        df — DataFrame с колонками: date, amount, type, description, counterparty, inn
        date_from / date_to — период выписки (None если дату не удалось определить)

    Raises:
        ParseError: пустой файл, неверный формат, не удалось разобрать
        ColumnMappingError: обязательные колонки не найдены
    """
    raw = _read_raw(file)

    if raw.empty or len(raw.columns) < 2:
        raise ParseError("Файл не содержит данных или имеет менее двух колонок.")

    raw = _drop_empty_rows(raw)

    # Специализированный путь для Альфа-Банка (d_c / sum_rur / text70)
    if _is_alfabank_format(raw):
        df = _parse_alfabank(raw)
    else:
        col_map = _map_columns(list(raw.columns))
        _validate_mapping(col_map)
        df = _build_canonical(raw, col_map)

    df = _clean(df)

    if df.empty:
        raise ParseError(
            "После фильтрации не осталось корректных транзакций. "
            "Проверьте формат файла."
        )

    valid_dates = df["date"].dropna()
    date_from = valid_dates.min().date() if not valid_dates.empty else None
    date_to = valid_dates.max().date() if not valid_dates.empty else None

    return df, date_from, date_to


# ---------------------------------------------------------------------------
# Формат Альфа-Банка
# ---------------------------------------------------------------------------

def _is_alfabank_format(df: pd.DataFrame) -> bool:
    """Проверить, что DataFrame — выписка Альфа-Банка по наличию сигнатурных колонок."""
    cols_lower = {c.lower() for c in df.columns}
    return _ALFABANK_SIGNATURE.issubset(cols_lower)


def _parse_alfabank(raw: pd.DataFrame) -> pd.DataFrame:
    """
    Специализированный парсер формата Альфа-Банка.

    Структура файла:
      Строка 1: английские технические имена (d_c, sum_rur, text70, …)
      Строка 2: русские описания колонок — пропускается
      Строки 3+: данные транзакций

    Логика определения контрагента:
      d_c == 'D' (расход): получатель = pol_name / Pol_inn
      d_c == 'C' (приход): плательщик = plat_name / plat_inn
    """
    # Нечувствительный к регистру словарь реальных имён колонок
    col = {c.lower(): c for c in raw.columns}

    # Пропускаем вторую строку-заголовок (содержит русские описания, а не данные).
    # Признак: sum_rur у первой строки не является числом.
    sum_raw_col = col.get("sum_rur")
    if sum_raw_col and len(raw) > 0:
        first_val = str(raw.iloc[0][sum_raw_col]).strip()
        if first_val and first_val not in ("nan", "0", "") and not _is_numeric_str(first_val):
            raw = raw.iloc[1:].reset_index(drop=True)

    # Даты
    date_col = col.get("date") or col.get("date_oper")
    dates = _parse_dates(raw[date_col]) if date_col else pd.Series(
        pd.NaT, index=raw.index
    )

    # Суммы
    amounts = _parse_amount(raw[sum_raw_col]) if sum_raw_col else pd.Series(
        0.0, index=raw.index
    )

    # Тип операции: D → debit, C → credit
    dc_col = col.get("d_c")
    dc = (
        raw[dc_col].astype(str).str.strip().str.upper()
        if dc_col else pd.Series("C", index=raw.index)
    )
    types = dc.map({"D": "debit", "C": "credit"}).fillna("credit")

    # Назначение платежа
    desc_col = col.get("text70")
    desc = (
        raw[desc_col].fillna("").astype(str).str.strip()
        if desc_col else pd.Series("", index=raw.index)
    )

    # Контрагент и ИНН — зависит от направления операции
    pol_name_col  = col.get("pol_name")
    pol_inn_col   = col.get("pol_inn")
    plat_name_col = col.get("plat_name")
    plat_inn_col  = col.get("plat_inn")

    _empty = pd.Series("", index=raw.index, dtype=str)

    pol_name  = raw[pol_name_col].fillna("").astype(str)  if pol_name_col  else _empty
    pol_inn   = raw[pol_inn_col].fillna("").astype(str)   if pol_inn_col   else _empty
    plat_name = raw[plat_name_col].fillna("").astype(str) if plat_name_col else _empty
    plat_inn  = raw[plat_inn_col].fillna("").astype(str)  if plat_inn_col  else _empty

    is_debit = dc == "D"
    counterparty = pol_name.where(is_debit, plat_name).str.strip()
    inn_raw      = pol_inn.where(is_debit, plat_inn).str.strip()
    inn          = inn_raw.apply(_clean_inn_value)

    return pd.DataFrame({
        "date":         dates,
        "amount":       amounts,
        "type":         types,
        "description":  desc,
        "counterparty": counterparty,
        "inn":          inn,
    })


def _clean_inn_value(val: object) -> str:
    """Очистить одно значение ИНН (вынесено для использования в Альфа-парсере)."""
    if pd.isna(val):
        return ""
    s = str(val).strip()
    if "." in s and s.endswith(".0"):
        s = s[:-2]
    digits = re.sub(r"\D", "", s.split("/")[0])
    return digits if len(digits) in (10, 12) else ""


# ---------------------------------------------------------------------------
# Чтение файла
# ---------------------------------------------------------------------------

def _read_raw(file) -> pd.DataFrame:
    name = getattr(file, "name", str(file))
    ext = Path(name).suffix.lower()

    if ext in (".xlsx", ".xls"):
        return _read_excel(file)
    if ext == ".csv":
        return _read_csv(file)

    # Формат не определён по расширению — пробуем оба
    try:
        return _read_excel(file)
    except Exception:
        pass
    if hasattr(file, "seek"):
        file.seek(0)
    try:
        return _read_csv(file)
    except Exception:
        pass

    raise ParseError(
        f"Не удалось определить формат файла «{name}». "
        "Поддерживаются CSV и XLSX."
    )


def _read_excel(file) -> pd.DataFrame:
    xl = pd.ExcelFile(file, engine="openpyxl")

    # Выбираем лист с наибольшим числом строк
    best_sheet, best_rows = xl.sheet_names[0], 0
    for sheet in xl.sheet_names:
        try:
            n = len(xl.parse(sheet, header=None))
            if n > best_rows:
                best_rows, best_sheet = n, sheet
        except Exception:
            continue

    raw_no_header = xl.parse(best_sheet, header=None)
    header_row = _detect_header_row(raw_no_header)

    df = xl.parse(best_sheet, header=header_row, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _detect_header_row(df: pd.DataFrame, max_scan: int = 15) -> int:
    """Найти строку-заголовок: та, где больше всего непустых строковых ячеек."""
    best_row, best_score = 0, 0
    for i in range(min(max_scan, len(df))):
        row = df.iloc[i]
        score = sum(
            1 for v in row
            if isinstance(v, str) and len(v.strip()) > 1 and not _is_numeric_str(v)
        )
        if score > best_score:
            best_score, best_row = score, i
    return best_row


def _is_numeric_str(s: str) -> bool:
    try:
        float(s.replace(",", ".").replace(" ", ""))
        return True
    except ValueError:
        return False


def _read_csv(file) -> pd.DataFrame:
    content = _read_bytes(file)

    encodings = ["utf-8-sig", "utf-8", "cp1251", "latin-1"]
    separators = [";", ",", "\t", "|"]

    for enc in encodings:
        for sep in separators:
            try:
                df = pd.read_csv(
                    io.BytesIO(content),
                    sep=sep,
                    encoding=enc,
                    dtype=str,
                    skip_blank_lines=True,
                    on_bad_lines="skip",  # пропускать строки с неверным числом полей
                )
                if len(df.columns) >= 2 and len(df) > 0:
                    df.columns = [str(c).strip() for c in df.columns]
                    return df
            except Exception:
                continue

    raise ParseError(
        "Не удалось прочитать CSV-файл. "
        "Проверьте кодировку (UTF-8 или CP1251) и разделитель (';' или ',')."
    )


def _read_bytes(file) -> bytes:
    if hasattr(file, "read"):
        content = file.read()
        return content.encode("utf-8") if isinstance(content, str) else content
    with open(file, "rb") as f:
        return f.read()


def _drop_empty_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Удалить строки, где все ячейки пустые или NaN."""
    return df.dropna(how="all").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Маппинг колонок
# ---------------------------------------------------------------------------

def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _score_header(header: str, aliases: list[str]) -> float:
    """Максимальный score заголовка относительно списка синонимов."""
    h = header.lower().strip()
    best = 0.0
    for alias in aliases:
        a = alias.lower().strip()
        if h == a:
            return 1.0
        # Substring: одно содержит другое → высокий балл
        if a in h or h in a:
            best = max(best, 0.90)
            continue
        best = max(best, _similarity(h, a))
    return best


def _map_columns(raw_cols: list[str], cutoff: float = 0.60) -> dict[str, str]:
    """
    Сопоставить сырые заголовки с каноническими именами.

    Returns:
        {raw_col_name: canonical_name}
    """
    # Собрать все варианты с оценкой (score, raw, canonical)
    candidates: list[tuple[float, str, str]] = []
    for raw in raw_cols:
        for canonical, aliases in _ALIASES.items():
            score = _score_header(raw, aliases)
            if score >= cutoff:
                candidates.append((score, raw, canonical))

    # Жадное назначение: от лучшего к худшему
    candidates.sort(key=lambda x: x[0], reverse=True)
    mapping: dict[str, str] = {}
    used_canonical: set[str] = set()
    used_raw: set[str] = set()

    for score, raw, canonical in candidates:
        if raw not in used_raw and canonical not in used_canonical:
            mapping[raw] = canonical
            used_raw.add(raw)
            used_canonical.add(canonical)

    return mapping


def _validate_mapping(col_map: dict[str, str]) -> None:
    """Проверить, что найдены минимально необходимые колонки."""
    found = set(col_map.values())

    if "date" not in found:
        raise ColumnMappingError(
            "Не найдена колонка с датой операции. "
            "Ожидаемые заголовки: «Дата», «Дата операции», «Date»."
        )

    if "description" not in found:
        raise ColumnMappingError(
            "Не найдена колонка с назначением платежа. "
            "Ожидаемые заголовки: «Назначение», «Назначение платежа», «Описание»."
        )

    has_split = "debit" in found and "credit" in found
    has_combined = "amount" in found
    if not has_split and not has_combined:
        raise ColumnMappingError(
            "Не найдены колонки с суммами транзакций. "
            "Ожидается пара «Дебет»/«Кредит» или колонка «Сумма»."
        )


# ---------------------------------------------------------------------------
# Построение канонического DataFrame
# ---------------------------------------------------------------------------

def _build_canonical(df: pd.DataFrame, col_map: dict[str, str]) -> pd.DataFrame:
    """Построить DataFrame с каноническими колонками из сырого + маппинга."""
    rev = {v: k for k, v in col_map.items()}  # canonical → raw

    found = set(rev.keys())
    has_split = "debit" in found and "credit" in found
    has_amount = "amount" in found
    has_type = "type" in found

    if has_split and not has_amount:
        return _from_split_columns(df, rev)

    if has_amount and has_type:
        return _from_amount_type(df, rev)

    if has_amount:
        # Сумма без типа — определяем по знаку числа
        return _from_amount_signed(df, rev)

    raise ColumnMappingError("Не удалось определить структуру суммовых колонок.")


def _from_split_columns(df: pd.DataFrame, rev: dict[str, str]) -> pd.DataFrame:
    """Формат А: отдельные колонки Дебет и Кредит."""
    debit_col = rev["debit"]
    credit_col = rev["credit"]

    df_d = df.copy()
    df_d["_amount"] = _parse_amount(df[debit_col])
    df_d["_type"] = "debit"
    df_d = df_d[df_d["_amount"].fillna(0) > 0].copy()

    df_c = df.copy()
    df_c["_amount"] = _parse_amount(df[credit_col])
    df_c["_type"] = "credit"
    df_c = df_c[df_c["_amount"].fillna(0) > 0].copy()

    combined = pd.concat([df_d, df_c], ignore_index=True)

    result = pd.DataFrame()
    result["date"] = _parse_dates(combined[rev["date"]])
    result["amount"] = combined["_amount"]
    result["type"] = combined["_type"]
    result["description"] = _extract_text(combined, rev, "description")
    result["counterparty"] = _extract_text(combined, rev, "counterparty")
    result["inn"] = _extract_inn(combined, rev)

    return result.sort_values("date").reset_index(drop=True)


def _from_amount_type(df: pd.DataFrame, rev: dict[str, str]) -> pd.DataFrame:
    """Формат Б: колонки Сумма + Тип операции."""
    result = pd.DataFrame()
    result["date"] = _parse_dates(df[rev["date"]])
    result["amount"] = _parse_amount(df[rev["amount"]])
    result["type"] = _classify_type(df[rev["type"]])
    result["description"] = _extract_text(df, rev, "description")
    result["counterparty"] = _extract_text(df, rev, "counterparty")
    result["inn"] = _extract_inn(df, rev)
    return result.reset_index(drop=True)


def _from_amount_signed(df: pd.DataFrame, rev: dict[str, str]) -> pd.DataFrame:
    """Только колонка Сумма без типа: минус → дебет, плюс → кредит."""
    raw_amounts = (
        df[rev["amount"]]
        .astype(str)
        .str.replace(r"[^\d,.\-]", "", regex=True)
        .str.replace(",", ".", regex=False)
    )
    amounts = pd.to_numeric(raw_amounts, errors="coerce")

    result = pd.DataFrame()
    result["date"] = _parse_dates(df[rev["date"]])
    result["amount"] = amounts.abs()
    result["type"] = amounts.apply(
        lambda x: "debit" if pd.notna(x) and x < 0 else "credit"
    )
    result["description"] = _extract_text(df, rev, "description")
    result["counterparty"] = _extract_text(df, rev, "counterparty")
    result["inn"] = _extract_inn(df, rev)
    return result.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Нормализация отдельных полей
# ---------------------------------------------------------------------------

def _parse_amount(series: pd.Series) -> pd.Series:
    """Разобрать сумму: убрать пробелы, валюту, перевести запятую в точку."""
    cleaned = (
        series.astype(str)
        .str.strip()
        .str.replace(r"\s", "", regex=True)        # пробелы внутри числа
        .str.replace(r"[^\d,.\-]", "", regex=True)  # не-числовые символы
        .str.replace(",", ".", regex=False)          # десятичная запятая
        .replace({"": None, "nan": None, "None": None, ".": None})
    )
    return pd.to_numeric(cleaned, errors="coerce").abs()


def _parse_dates(series: pd.Series) -> pd.Series:
    """Разобрать даты, перебирая известные форматы."""
    for fmt in _DATE_FORMATS:
        try:
            parsed = pd.to_datetime(series, format=fmt, errors="coerce")
            if parsed.notna().mean() > 0.5:
                return parsed
        except Exception:
            continue
    # Последний шанс — pandas угадывает формат сам
    return pd.to_datetime(series, errors="coerce")


def _classify_type(series: pd.Series) -> pd.Series:
    """Нормализовать текстовый тип операции к 'debit' / 'credit'."""
    def _classify(val: object) -> str:
        v = str(val).lower().strip()
        if any(m in v for m in _DEBIT_MARKERS):
            return "debit"
        if any(m in v for m in _CREDIT_MARKERS):
            return "credit"
        return "debit"  # безопасный fallback

    return series.apply(_classify)


def _extract_text(df: pd.DataFrame, rev: dict[str, str], canonical: str) -> pd.Series:
    """Извлечь текстовую колонку, вернуть пустые строки если отсутствует."""
    raw = rev.get(canonical)
    if raw and raw in df.columns:
        return df[raw].fillna("").astype(str).str.strip()
    return pd.Series("", index=df.index, dtype=str)


def _extract_inn(df: pd.DataFrame, rev: dict[str, str]) -> pd.Series:
    """Извлечь ИНН: оставить только цифры, убрать КПП если слитно."""
    raw = rev.get("inn")
    if not raw or raw not in df.columns:
        return pd.Series("", index=df.index, dtype=str)
    return df[raw].apply(_clean_inn_value)


# ---------------------------------------------------------------------------
# Финальная очистка
# ---------------------------------------------------------------------------

def _clean(df: pd.DataFrame) -> pd.DataFrame:
    """Удалить строки с некорректными обязательными полями."""
    df = df.copy()

    # Убираем строки без даты или суммы
    df = df.dropna(subset=["date", "amount"])
    df = df[df["amount"] > 0]

    # Сбрасываем индекс после фильтрации
    return df.reset_index(drop=True)
