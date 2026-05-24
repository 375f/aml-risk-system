"""
module1/pdf_report.py — формирование PDF-отчёта по анализу выписки.

Не импортирует Streamlit. Вызывается из module1/ui.py.
Кириллица через системный шрифт Arial (Windows) или DejaVuSans (Linux).
"""

from __future__ import annotations

import os
from datetime import datetime

from fpdf import FPDF

# ---------------------------------------------------------------------------
# Цветовая палитра
# ---------------------------------------------------------------------------

_RISK_RGB: dict[str, tuple[int, int, int]] = {
    "low":    (0,   200, 83),   # #00C853 зелёный
    "medium": (204, 153, 0),    # золотой (вместо #FFE000 — плохо видно на белом)
    "high":   (220, 50,  40),   # #DC3228 красный
}
_RISK_BG: dict[str, tuple[int, int, int]] = {
    "low":    (232, 248, 237),  # светло-зелёный
    "medium": (255, 250, 220),  # светло-жёлтый
    "high":   (255, 235, 233),  # светло-красный
}
_RISK_RU = {"low": "Низкий риск", "medium": "Средний риск", "high": "Высокий риск"}

_BLACK  = (30,  30,  30)
_GRAY   = (100, 100, 100)
_LGRAY  = (220, 220, 220)
_WHITE  = (255, 255, 255)
_ACCENT = (255, 200, 0)   # жёлтый акцент для triggered-карточек

_PW   = 210   # A4 ширина, мм
_PH   = 297   # A4 высота, мм
_M    = 15    # поля


# ---------------------------------------------------------------------------
# Шрифты с поддержкой кириллицы
# ---------------------------------------------------------------------------

def _locate_font(*candidates: str) -> str:
    """Найти первый существующий файл шрифта из списка кандидатов."""
    # 1. Windows system fonts
    win_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    for name in candidates:
        path = os.path.join(win_dir, name)
        if os.path.exists(path):
            return path

    # 2. Linux / macOS system paths
    system_dirs = [
        "/usr/share/fonts/truetype/dejavu",
        "/usr/share/fonts/truetype/liberation",
        "/usr/share/fonts/TTF",
        "/System/Library/Fonts",
        "/Library/Fonts",
    ]
    for d in system_dirs:
        for name in candidates:
            path = os.path.join(d, name)
            if os.path.exists(path):
                return path

    raise FileNotFoundError(
        f"Не найден шрифт с поддержкой кириллицы. Проверьте наличие: {candidates}"
    )


# ---------------------------------------------------------------------------
# Класс отчёта
# ---------------------------------------------------------------------------

class _AMLReport(FPDF):
    """FPDF-наследник с автоматической шапкой и колонтитулом."""

    def __init__(self, doc_filename: str, risk_level: str) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self._doc_filename = doc_filename
        self._risk_level   = risk_level
        self._fonts_ready  = False

    # -- Регистрация шрифтов ------------------------------------------------

    def setup_fonts(self) -> None:
        regular = _locate_font("arial.ttf",   "Arial.ttf",   "DejaVuSans.ttf",          "LiberationSans-Regular.ttf")
        bold    = _locate_font("arialbd.ttf",  "ArialBD.TTF", "DejaVuSans-Bold.ttf",     "LiberationSans-Bold.ttf")
        italic  = _locate_font("ariali.ttf",   "Arial-Italic.ttf", "DejaVuSans-Oblique.ttf", regular)

        self.add_font("F", style="",  fname=regular)
        self.add_font("F", style="B", fname=bold)
        self.add_font("F", style="I", fname=italic)
        self._fonts_ready = True

    # -- Автоматическая шапка (страница 2+) ---------------------------------

    def header(self) -> None:
        if self.page_no() == 1:
            return
        self.set_font("F", style="I", size=8)
        self.set_text_color(*_GRAY)
        self.cell(0, 5, f"АМЛ-анализ: {self._doc_filename}", align="L")
        self.ln(0.5)
        self.set_draw_color(*_LGRAY)
        self.line(_M, self.get_y(), _PW - _M, self.get_y())
        self.ln(4)
        self.set_text_color(*_BLACK)

    # -- Колонтитул ---------------------------------------------------------

    def footer(self) -> None:
        self.set_y(-13)
        self.set_draw_color(*_LGRAY)
        self.line(_M, self.get_y(), _PW - _M, self.get_y())
        self.ln(1)
        self.set_font("F", style="I", size=8)
        self.set_text_color(*_GRAY)
        date_str = datetime.now().strftime("%d.%m.%Y")
        self.cell(
            0, 5,
            f"Сформировано системой АМЛ-анализа  ·  {date_str}  "
            f"·  Конфиденциально  ·  Стр. {self.page_no()}",
            align="C",
        )


# ---------------------------------------------------------------------------
# Публичный API
# ---------------------------------------------------------------------------

def generate_pdf(
    filename: str,
    risk_level: str,
    risk_proba: float,
    described: list[dict],
    okved_codes: list[str],
    okved_report: dict,
) -> bytes:
    """
    Сформировать PDF-отчёт и вернуть байты.

    Args:
        filename:     имя файла выписки
        risk_level:   'low' | 'medium' | 'high'
        risk_proba:   вероятность предсказанного класса (0..1)
        described:    список dict из describe_features() — 10 признаков
        okved_codes:  коды ОКВЭД (может быть пустым)
        okved_report: результат check_okved_compliance() (может быть {})
    """
    pdf = _AMLReport(doc_filename=filename, risk_level=risk_level)
    pdf.setup_fonts()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(_M, 15, _M)

    _page_cover(pdf, filename, risk_level, risk_proba, described)
    _page_features_table(pdf, described)
    _page_triggered_details(pdf, described)

    if okved_codes and okved_report:
        _page_okved(pdf, okved_codes, okved_report)

    return bytes(pdf.output())


# ---------------------------------------------------------------------------
# Страница 1 — Обложка и итог
# ---------------------------------------------------------------------------

def _page_cover(
    pdf: _AMLReport,
    filename: str,
    risk_level: str,
    risk_proba: float,
    described: list[dict],
) -> None:
    pdf.add_page()

    # ── Заголовок ──────────────────────────────────────────────────────────
    pdf.set_y(28)
    pdf.set_font("F", style="B", size=22)
    pdf.set_text_color(*_BLACK)
    pdf.cell(0, 12, "АМЛ-анализ банковской выписки", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("F", size=10)
    pdf.set_text_color(*_GRAY)
    date_str = datetime.now().strftime("%d.%m.%Y  %H:%M")
    pdf.cell(0, 7, f"Файл: {filename}   ·   Сформирован: {date_str}", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(6)
    _hline(pdf)
    pdf.ln(10)

    # ── Карточка вердикта ──────────────────────────────────────────────────
    r, g, b    = _RISK_RGB[risk_level]
    br, bg, bb = _RISK_BG[risk_level]
    label      = _RISK_RU[risk_level]

    card_x = _M
    card_w = _PW - 2 * _M
    card_y = pdf.get_y()
    card_h = 38

    # Левая цветная полоса
    pdf.set_fill_color(r, g, b)
    pdf.rect(card_x, card_y, 4, card_h, style="F")

    # Фон карточки
    pdf.set_fill_color(br, bg, bb)
    pdf.rect(card_x + 4, card_y, card_w - 4, card_h, style="F")

    # Тонкая рамка
    pdf.set_draw_color(r, g, b)
    pdf.rect(card_x + 4, card_y, card_w - 4, card_h, style="D")

    # Текст вердикта
    pdf.set_xy(card_x + 10, card_y + 7)
    pdf.set_font("F", style="B", size=18)
    pdf.set_text_color(r, g, b)
    pdf.cell(0, 9, label, new_x="LMARGIN", new_y="NEXT")

    pdf.set_x(card_x + 10)
    pdf.set_font("F", size=10)
    pdf.set_text_color(*_BLACK)

    triggered_count = sum(1 for d in described if d["is_triggered"])
    total_count     = len(described)
    pdf.cell(
        0, 7,
        f"Уверенность модели: {risk_proba * 100:.1f}%    ·    "
        f"Сработавших признаков: {triggered_count} из {total_count}",
        new_x="LMARGIN", new_y="NEXT",
    )

    pdf.set_y(card_y + card_h + 10)

    # ── Нормативная база ───────────────────────────────────────────────────
    _hline(pdf)
    pdf.ln(5)
    pdf.set_font("F", size=9)
    pdf.set_text_color(*_GRAY)
    pdf.multi_cell(
        0, 5,
        "Анализ выполнен в соответствии с методическими рекомендациями ЦБ РФ 18-МР и 19-МР "
        "от 21.07.2017 и требованиями Федерального закона № 115-ФЗ «О противодействии "
        "легализации (отмыванию) доходов, полученных преступным путём, и финансированию терроризма».",
        align="J",
    )


# ---------------------------------------------------------------------------
# Страница 2 — Таблица признаков
# ---------------------------------------------------------------------------

def _page_features_table(pdf: _AMLReport, described: list[dict]) -> None:
    pdf.add_page()

    _section_title(pdf, "Значения признаков риска")

    col_w   = [76, 30, 30, 24]
    headers = ["Признак", "Значение", "Порог", "Статус"]

    # Заголовок таблицы
    pdf.set_fill_color(*_LGRAY)
    pdf.set_font("F", style="B", size=9)
    pdf.set_text_color(*_BLACK)
    for w, h in zip(col_w, headers):
        pdf.cell(w, 7, h, border=0, fill=True, align="C")
    pdf.ln()

    # Строки признаков
    for idx, d in enumerate(described):
        triggered = d["is_triggered"]

        # Чередование фона строк
        if triggered:
            pdf.set_fill_color(255, 235, 233)   # светло-красный
        elif idx % 2 == 0:
            pdf.set_fill_color(248, 248, 248)
        else:
            pdf.set_fill_color(*_WHITE)

        val_str = d["display_value"] if d["unit"] else f"{d['value']:.3f}"
        thr_str = (
            f"{d['threshold'] * d['scale']:.1f} {d['unit']}".strip()
            if d["unit"] else f"{d['threshold']:.3f}"
        )
        status_str = "Риск" if triggered else "Норма"

        # Ячейка «Признак»
        pdf.set_font("F", size=9)
        pdf.set_text_color(*_BLACK)
        pdf.cell(col_w[0], 6.5, d["label"], border=0, fill=True, align="L")

        # Ячейка «Значение»
        if triggered:
            pdf.set_text_color(200, 30, 20)
        pdf.cell(col_w[1], 6.5, val_str, border=0, fill=True, align="C")

        # Ячейка «Порог»
        pdf.set_text_color(*_GRAY)
        pdf.cell(col_w[2], 6.5, thr_str, border=0, fill=True, align="C")

        # Ячейка «Статус»
        if triggered:
            pdf.set_text_color(200, 30, 20)
            pdf.set_font("F", style="B", size=9)
        else:
            pdf.set_text_color(0, 160, 60)
            pdf.set_font("F", style="B", size=9)
        pdf.cell(col_w[3], 6.5, status_str, border=0, fill=True, align="C")
        pdf.ln()

        # Разделитель
        pdf.set_draw_color(*_LGRAY)
        pdf.line(_M, pdf.get_y(), _PW - _M, pdf.get_y())

    pdf.ln(5)
    pdf.set_font("F", style="I", size=8)
    pdf.set_text_color(*_GRAY)
    pdf.multi_cell(
        0, 5,
        "* Пороги установлены согласно методическим рекомендациям ЦБ РФ 18-МР, 19-МР "
        "от 21.07.2017 и требованиям 115-ФЗ.",
    )


# ---------------------------------------------------------------------------
# Страница 3 — Детали сработавших факторов
# ---------------------------------------------------------------------------

def _page_triggered_details(pdf: _AMLReport, described: list[dict]) -> None:
    pdf.add_page()

    triggered = [d for d in described if d["is_triggered"]]
    _section_title(pdf, "Выявленные факторы риска")

    if not triggered:
        pdf.set_font("F", size=11)
        pdf.set_text_color(0, 160, 60)
        pdf.cell(
            0, 10,
            "Нарушений не выявлено. Ни один из контрольных признаков не превысил пороговых значений.",
            new_x="LMARGIN", new_y="NEXT",
        )
        return

    for d in triggered:
        _factor_card(pdf, d)
        pdf.ln(4)


def _factor_card(pdf: _AMLReport, d: dict) -> None:
    """Карточка одного сработавшего признака с левой жёлтой полосой."""
    card_x = _M
    card_w = _PW - 2 * _M

    # Оценка нужной высоты (многострочное описание)
    desc_lines = max(1, len(d["risk_description"]) // 82 + 1)
    card_h = 9 + 6 + desc_lines * 5 + 6   # заголовок + значение + описание + отступы

    # Новая страница если не помещается
    if pdf.get_y() + card_h > _PH - 20:
        pdf.add_page()

    cy = pdf.get_y()

    # Левая жёлтая полоса
    pdf.set_fill_color(204, 153, 0)
    pdf.rect(card_x, cy, 3.5, card_h, style="F")

    # Фон карточки
    pdf.set_fill_color(255, 253, 240)
    pdf.rect(card_x + 3.5, cy, card_w - 3.5, card_h, style="F")

    # Тонкая рамка
    pdf.set_draw_color(204, 153, 0)
    pdf.rect(card_x + 3.5, cy, card_w - 3.5, card_h, style="D")

    # Название признака
    pdf.set_xy(card_x + 8, cy + 4)
    pdf.set_font("F", style="B", size=10)
    pdf.set_text_color(*_BLACK)
    pdf.cell(card_w - 12, 7, d["label"], new_x="LMARGIN", new_y="NEXT")

    # Значение | Порог | Источник
    pdf.set_x(card_x + 8)
    pdf.set_font("F", size=8)
    pdf.set_text_color(*_GRAY)
    val_str = d["display_value"] if d["unit"] else f"{d['value']:.3f}"
    thr_str = (
        f"{d['threshold'] * d['scale']:.1f} {d['unit']}".strip()
        if d["unit"] else f"{d['threshold']:.3f}"
    )
    pdf.cell(card_w - 12, 5.5,
             f"Значение: {val_str}   |   Порог: {thr_str}   |   Источник: {d['source']}",
             new_x="LMARGIN", new_y="NEXT")

    # Описание риска
    pdf.set_x(card_x + 8)
    pdf.set_font("F", size=9)
    pdf.set_text_color(*_BLACK)
    pdf.multi_cell(card_w - 12, 5, d["risk_description"])

    pdf.set_y(cy + card_h)


# ---------------------------------------------------------------------------
# Страница 4 — Соответствие ОКВЭД (только если коды переданы)
# ---------------------------------------------------------------------------

def _page_okved(
    pdf: _AMLReport,
    okved_codes: list[str],
    okved_report: dict,
) -> None:
    pdf.add_page()
    _section_title(pdf, "Проверка соответствия ОКВЭД")

    mismatch   = okved_report.get("okved_mismatch_ratio", 0.0)
    suspicious = okved_report.get("suspicious_transactions", [])
    total_amt  = okved_report.get("total_suspicious_amount", 0.0)
    codes_str  = ", ".join(okved_codes)

    # Сводная информация
    pdf.set_font("F", size=10)
    pdf.set_text_color(*_BLACK)
    pdf.cell(0, 7, f"Проверяемые коды ОКВЭД: {codes_str}", new_x="LMARGIN", new_y="NEXT")

    pct   = mismatch * 100
    r, g, b = (200, 30, 20) if pct >= 60 else ((204, 153, 0) if pct >= 30 else (0, 160, 60))
    pdf.set_font("F", style="B", size=10)
    pdf.set_text_color(r, g, b)
    pdf.cell(0, 7, f"Доля несоответствия: {pct:.1f}%", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("F", size=10)
    pdf.set_text_color(*_BLACK)
    pdf.cell(
        0, 7,
        f"Подозрительных транзакций: {len(suspicious)}    ·    "
        f"Сумма: {total_amt:,.0f} руб.".replace(",", " "),
        new_x="LMARGIN", new_y="NEXT",
    )

    pdf.ln(4)

    if not suspicious:
        pdf.set_font("F", size=11)
        pdf.set_text_color(0, 160, 60)
        pdf.cell(0, 8, "Все входящие платежи соответствуют заявленным кодам ОКВЭД.", new_x="LMARGIN", new_y="NEXT")
        return

    # Таблица подозрительных транзакций
    _section_title(pdf, "Подозрительные входящие транзакции", size=11)

    col_w2  = [24, 90, 38, 28]
    headers = ["Дата", "Назначение платежа", "Сумма, руб.", "Контрагент"]

    pdf.set_fill_color(*_LGRAY)
    pdf.set_font("F", style="B", size=8)
    pdf.set_text_color(*_BLACK)
    for w, h in zip(col_w2, headers):
        pdf.cell(w, 7, h, border=0, fill=True, align="C")
    pdf.ln()

    pdf.set_font("F", size=8)
    for idx, tx in enumerate(suspicious[:25]):
        pdf.set_fill_color(255, 245, 245) if idx % 2 == 0 else pdf.set_fill_color(*_WHITE)
        pdf.set_text_color(*_BLACK)

        desc  = str(tx.get("description", ""))[:60]
        cp    = str(tx.get("counterparty", ""))[:22]
        amt   = f"{tx.get('amount', 0):,.0f}".replace(",", " ")
        row   = [tx.get("date", "—"), desc, amt, cp]
        aligns= ["C", "L", "C", "L"]

        for w, text, align in zip(col_w2, row, aligns):
            pdf.cell(w, 6, text, border=0, fill=True, align=align)
        pdf.ln()
        pdf.set_draw_color(*_LGRAY)
        pdf.line(_M, pdf.get_y(), _PW - _M, pdf.get_y())

    if len(suspicious) > 25:
        pdf.ln(3)
        pdf.set_font("F", style="I", size=8)
        pdf.set_text_color(*_GRAY)
        pdf.cell(0, 6, f"... и ещё {len(suspicious) - 25} транзакций. Показаны первые 25.", new_x="LMARGIN", new_y="NEXT")


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _section_title(pdf: _AMLReport, text: str, size: int = 13) -> None:
    pdf.set_font("F", style="B", size=size)
    pdf.set_text_color(*_BLACK)
    pdf.cell(0, 9, text, new_x="LMARGIN", new_y="NEXT")
    _hline(pdf)
    pdf.ln(4)


def _hline(pdf: _AMLReport) -> None:
    pdf.set_draw_color(*_LGRAY)
    pdf.line(_M, pdf.get_y(), _PW - _M, pdf.get_y())
    pdf.ln(2)
