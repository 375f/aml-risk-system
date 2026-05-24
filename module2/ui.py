"""
module2/ui.py — Streamlit-компонент вкладки «Проверка контрагента».

Вызывается из app.py:
    from module2.ui import render
    with tab2:
        render()
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import streamlit as st

from config import CONTRACTOR_CACHE_TTL_HOURS
from db.connection import SessionLocal
from db.crud import get_contractor_cache, get_recent_contractors, save_contractor
from module2.rusprofile_api import get_entity_by_inn
from module2.scorer import score_contractor
from module2.validator import get_inn_type, validate_inn

# ---------------------------------------------------------------------------
# Палитра T-Bank
# ---------------------------------------------------------------------------

_VERDICT_ICON  = {"safe": "🟢", "caution": "🟡", "high_risk": "🔴"}
_VERDICT_LABEL = {"safe": "Безопасно", "caution": "Осторожно", "high_risk": "Высокий риск"}
_VERDICT_COLOR = {"safe": "#00C853", "caution": "#FFE000", "high_risk": "#FF3B30"}

_STATUS_RU = {
    "active":       "Действующее",
    "liquidated":   "Ликвидировано",
    "liquidating":  "В процессе ликвидации",
    "reorganizing": "Реорганизация",
    "unknown":      "Неизвестно",
}
_ENTITY_RU = {"ul": "Юридическое лицо", "ip": "ИП / физическое лицо"}


# ---------------------------------------------------------------------------
# Общие UI-компоненты
# ---------------------------------------------------------------------------

def _verdict_card(verdict: str, score: int, name: str | None, from_cache: bool) -> None:
    """Карточка вердикта с левой цветной полосой (стиль Т-Банка)."""
    color = _VERDICT_COLOR[verdict]
    label = _VERDICT_LABEL[verdict]
    icon  = _VERDICT_ICON[verdict]
    cache_note = (
        '<span style="color:#8C8C8C;font-size:12px;margin-left:12px;">· из кэша</span>'
        if from_cache else ""
    )
    st.markdown(
        f"""
        <div style="
            border-left: 4px solid {color};
            background: #242424;
            border-radius: 12px;
            padding: 20px 24px;
            margin-bottom: 16px;
            border-top: 1px solid #333333;
            border-right: 1px solid #333333;
            border-bottom: 1px solid #333333;
        ">
            <div style="font-size:22px;font-weight:700;color:{color};">
                {icon}&nbsp; {label}{cache_note}
            </div>
            <div style="color:#8C8C8C;font-size:13px;margin-top:6px;">
                Балл риска:&nbsp;<strong style="color:#FFFFFF;">{score} / 100</strong>
                &nbsp;·&nbsp;
                <span style="color:#8C8C8C;">{name or "—"}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _status_badge(status_raw: str) -> str:
    """Цветной бейдж статуса организации."""
    label = _STATUS_RU.get(status_raw, status_raw)
    if status_raw == "active":
        color, bg = "#00C853", "#003314"
    elif status_raw in ("liquidated", "liquidating"):
        color, bg = "#FF3B30", "#330800"
    else:
        color, bg = "#8C8C8C", "#2E2E2E"
    return (
        f'<span style="display:inline-block;background:{bg};color:{color};'
        f'border:1px solid {color};border-radius:6px;'
        f'padding:2px 10px;font-size:12px;font-weight:600;">{label}</span>'
    )


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------

def render() -> None:
    """Отрендерить всю вкладку «Проверка контрагента»."""
    st.subheader("Проверка контрагента по ИНН")
    _section_input()

    if "contractor_result" in st.session_state:
        st.divider()
        _section_result()

    st.divider()
    _section_history()


# ---------------------------------------------------------------------------
# Секция 1 — ввод и валидация ИНН
# ---------------------------------------------------------------------------

def _section_input() -> None:
    st.markdown(
        "<div style='color:#8C8C8C;font-size:13px;margin-bottom:12px;'>"
        "Введите ИНН контрагента для получения сведений из ЕГРЮЛ/ЕГРИП "
        "и автоматической оценки риска по критериям 115-ФЗ."
        "</div>",
        unsafe_allow_html=True,
    )

    inn = st.text_input(
        "ИНН контрагента",
        placeholder="10 цифр — юрлицо, 12 цифр — ИП",
        max_chars=12,
        key="inn_input",
    ).strip()

    if inn:
        _show_inn_validation(inn)

    inn_valid = validate_inn(inn) if inn else False

    col_btn, col_clear = st.columns([3, 1])
    with col_btn:
        check_clicked = st.button(
            "🔍 Проверить контрагента",
            type="primary",
            width="stretch",
            disabled=not inn_valid,
        )
    with col_clear:
        if st.button("✖ Сбросить", width="stretch"):
            st.session_state.pop("contractor_result", None)
            st.rerun()

    if check_clicked and inn_valid:
        _run_check(inn)


def _show_inn_validation(inn: str) -> None:
    """Показать индикатор валидности ИНН в реальном времени."""
    is_valid = validate_inn(inn)

    if not inn.isdigit():
        st.markdown(
            "<div style='color:#FF3B30;font-size:13px;'>🔴&nbsp; ИНН должен содержать только цифры.</div>",
            unsafe_allow_html=True,
        )
        return

    if len(inn) not in (10, 12) and len(inn) > 0:
        remaining_10 = 10 - len(inn)
        remaining_12 = 12 - len(inn)
        if len(inn) < 10:
            st.markdown(
                f"<div style='color:#8C8C8C;font-size:13px;'>⏳&nbsp; Введите ещё "
                f"<strong style='color:#FFFFFF;'>{remaining_10}</strong> цифр (юрлицо) "
                f"или <strong style='color:#FFFFFF;'>{remaining_12}</strong> (ИП).</div>",
                unsafe_allow_html=True,
            )
        elif len(inn) == 11:
            st.markdown(
                "<div style='color:#8C8C8C;font-size:13px;'>⏳&nbsp; Введите ещё "
                "<strong style='color:#FFFFFF;'>1</strong> цифру (ИП) или удалите последнюю (юрлицо).</div>",
                unsafe_allow_html=True,
            )
        return

    if is_valid:
        try:
            entity_type = get_inn_type(inn)
            type_label  = _ENTITY_RU.get(entity_type, entity_type)
        except ValueError:
            type_label = "неизвестный тип"
        st.markdown(
            f"<div style='color:#00C853;font-size:13px;'>🟢&nbsp; ИНН корректен — "
            f"<strong>{type_label}</strong></div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            "<div style='color:#FF3B30;font-size:13px;'>🔴&nbsp; Неверная контрольная сумма ИНН.</div>",
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Запуск проверки
# ---------------------------------------------------------------------------

def _run_check(inn: str) -> None:
    try:
        session = SessionLocal()
        cached = get_contractor_cache(session, inn)
        session.close()
    except Exception:
        cached = None

    if cached is not None:
        st.session_state["contractor_result"] = _contractor_to_result(cached)
        st.session_state["contractor_result"]["from_cache"] = True
        st.rerun()
        return

    with st.spinner("Запрашиваю данные ЕГРЮЛ/ЕГРИП…"):
        try:
            entity = get_entity_by_inn(inn)
        except Exception as exc:
            st.error(f"❌ {exc}")
            return

    score, verdict, triggered = score_contractor(entity)

    expires = datetime.now(timezone.utc) + timedelta(hours=CONTRACTOR_CACHE_TTL_HOURS)
    try:
        session = SessionLocal()
        save_contractor(session, {
            "inn":           inn,
            "name":          entity.get("name"),
            "ogrn":          entity.get("ogrn"),
            "entity_type":   entity.get("entity_type"),
            "status":        entity.get("status"),
            "reg_date":      entity.get("reg_date"),
            "address":       entity.get("address"),
            "mass_address":  entity.get("mass_address", False),
            "mass_director": entity.get("mass_director", False),
            "capital":       entity.get("capital"),
            "risk_score":    score,
            "verdict":       verdict,
            "expires_at":    expires,
            "raw_json":      entity,
        })
        session.close()
    except Exception:
        pass

    st.session_state["contractor_result"] = {
        "inn":           inn,
        "name":          entity.get("name"),
        "ogrn":          entity.get("ogrn"),
        "entity_type":   entity.get("entity_type"),
        "status":        entity.get("status"),
        "reg_date":      entity.get("reg_date"),
        "address":       entity.get("address"),
        "mass_address":  entity.get("mass_address", False),
        "mass_director": entity.get("mass_director", False),
        "capital":       entity.get("capital"),
        "score":         score,
        "verdict":       verdict,
        "triggered":     triggered,
        "from_cache":    False,
    }
    st.rerun()


def _contractor_to_result(c) -> dict:
    score, verdict, triggered = score_contractor({
        "status":        c.status,
        "reg_date":      c.reg_date,
        "mass_address":  c.mass_address,
        "mass_director": c.mass_director,
        "capital":       float(c.capital) if c.capital is not None else None,
    })
    return {
        "inn":           c.inn,
        "name":          c.name,
        "ogrn":          c.ogrn,
        "entity_type":   c.entity_type,
        "status":        c.status,
        "reg_date":      c.reg_date,
        "address":       c.address,
        "mass_address":  c.mass_address,
        "mass_director": c.mass_director,
        "capital":       float(c.capital) if c.capital is not None else None,
        "score":         score,
        "verdict":       verdict,
        "triggered":     triggered,
    }


# ---------------------------------------------------------------------------
# Секция 2 — результат проверки
# ---------------------------------------------------------------------------

def _section_result() -> None:
    r       = st.session_state["contractor_result"]
    verdict = r["verdict"]
    score   = r["score"]

    _verdict_card(verdict, score, r.get("name"), r.get("from_cache", False))

    st.progress(min(score / 100, 1.0))

    col_card, col_risk = st.columns([1, 1], gap="large")

    # --- Карточка контрагента ---
    with col_card:
        st.markdown(
            "<div style='font-size:14px;font-weight:600;color:#8C8C8C;margin-bottom:8px;'>"
            "Сведения из ЕГРЮЛ/ЕГРИП</div>",
            unsafe_allow_html=True,
        )

        status_raw   = r.get("status") or "unknown"
        entity_label = _ENTITY_RU.get(r.get("entity_type", ""), "—")
        reg_date     = r.get("reg_date")
        reg_str      = reg_date.strftime("%d.%m.%Y") if reg_date else "—"
        capital      = r.get("capital")
        cap_str      = f"{capital:,.0f} руб.".replace(",", " ") if capital else "—"

        def _row(label: str, value: str, is_html: bool = False, border: bool = True) -> str:
            border_style = "border-bottom:1px solid #333333;" if border else ""
            val_html = value if is_html else f'<span style="color:#FFFFFF;">{value}</span>'
            return (
                f'<div style="display:flex;justify-content:space-between;align-items:center;'
                f'padding:10px 0;{border_style}">'
                f'<span style="color:#8C8C8C;font-size:13px;">{label}</span>'
                f'<span style="font-size:13px;text-align:right;max-width:60%;">{val_html}</span>'
                f'</div>'
            )

        st.markdown(
            f"""
            <div style="
                background:#242424;border-radius:12px;padding:16px 20px;
                border:1px solid #333333;
            ">
                <div style="font-size:18px;font-weight:700;color:#FFFFFF;margin-bottom:12px;">
                    {r.get("name") or "—"}
                </div>
                {_row("ИНН", r.get("inn") or "—")}
                {_row("ОГРН", r.get("ogrn") or "—")}
                {_row("Тип", entity_label)}
                {_row("Статус", _status_badge(status_raw), is_html=True)}
                {_row("Дата регистрации", reg_str)}
                {_row("Уставный капитал", cap_str)}
                {_row("Адрес", r.get("address") or "—", border=False)}
            </div>
            """,
            unsafe_allow_html=True,
        )

        flags = []
        if r.get("mass_address"):
            flags.append("Массовый адрес регистрации")
        if r.get("mass_director"):
            flags.append("Массовый руководитель")
        for f in flags:
            st.markdown(
                f"""
                <div style="
                    border-left:3px solid #FFE000;background:#242424;border-radius:8px;
                    padding:10px 14px;margin-top:8px;
                    border-top:1px solid #333;border-right:1px solid #333;border-bottom:1px solid #333;
                ">
                    <span style="color:#FFE000;font-size:13px;">⚠&nbsp; {f}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )

    # --- Критерии риска ---
    with col_risk:
        st.markdown(
            "<div style='font-size:14px;font-weight:600;color:#8C8C8C;margin-bottom:8px;'>"
            "Оценка риска по 5 критериям (115-ФЗ)</div>",
            unsafe_allow_html=True,
        )
        triggered = r.get("triggered") or []

        if triggered:
            for reason in triggered:
                st.markdown(
                    f"""
                    <div style="
                        border-left:3px solid #FF3B30;background:#242424;border-radius:8px;
                        padding:12px 16px;margin-bottom:8px;
                        border-top:1px solid #333;border-right:1px solid #333;border-bottom:1px solid #333;
                    ">
                        <div style="font-weight:600;color:#FF3B30;font-size:13px;">❌&nbsp; {reason}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        else:
            st.markdown(
                """
                <div style="
                    border-left:4px solid #00C853;background:#242424;border-radius:12px;
                    padding:16px 20px;
                    border-top:1px solid #333;border-right:1px solid #333;border-bottom:1px solid #333;
                ">
                    <span style="color:#00C853;font-weight:600;">✓&nbsp;</span>
                    <span style="color:#FFFFFF;">Ни один из критериев риска не сработал.</span>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with st.expander("📋 Все проверенные критерии", expanded=False):
            criteria = [
                ("Статус организации",         r.get("status") == "active"),
                ("Срок регистрации > 12 мес.", _age_ok(r.get("reg_date"))),
                ("Адрес не массовый",          not r.get("mass_address", False)),
                ("Руководитель не массовый",   not r.get("mass_director", False)),
                ("Уставный капитал > 10 000",  _capital_ok(r.get("capital"))),
            ]
            for crit_name, ok in criteria:
                color_c = "#00C853" if ok else "#FF3B30"
                icon_c  = "✓" if ok else "✗"
                st.markdown(
                    f'<div style="color:{color_c};font-size:13px;padding:4px 0;">'
                    f'{icon_c}&nbsp; {crit_name}</div>',
                    unsafe_allow_html=True,
                )


# ---------------------------------------------------------------------------
# Секция 3 — ранее проверенные контрагенты
# ---------------------------------------------------------------------------

def _section_history() -> None:
    st.subheader("Ранее проверенные контрагенты")

    try:
        session = SessionLocal()
        records = get_recent_contractors(session, limit=50)
        session.close()
    except Exception as exc:
        st.warning(f"База данных недоступна: {exc}")
        return

    col_r1, col_r2 = st.columns([3, 1])
    with col_r2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🔄 Обновить", key="hist2_refresh"):
            st.rerun()
    with col_r1:
        verdict_filter = st.multiselect(
            "Фильтр по вердикту",
            options=["safe", "caution", "high_risk"],
            default=["safe", "caution", "high_risk"],
            format_func=lambda x: f"{_VERDICT_ICON[x]} {_VERDICT_LABEL[x]}",
            key="hist2_verdict_filter",
        )

    if not records:
        st.info("Проверенных контрагентов пока нет.")
        return

    rows = []
    for c in records:
        if c.verdict not in (verdict_filter or ["safe", "caution", "high_risk"]):
            continue
        checked = c.checked_at
        if checked and checked.tzinfo is None:
            checked = checked.replace(tzinfo=timezone.utc)
        rows.append({
            "Дата проверки": checked.strftime("%d.%m.%Y %H:%M") if checked else "—",
            "ИНН":           c.inn,
            "Наименование":  c.name or "—",
            "ОГРН":          c.ogrn or "—",
            "Тип":           _ENTITY_RU.get(c.entity_type or "", "—"),
            "Статус":        _STATUS_RU.get(c.status or "unknown", c.status or "—"),
            "Вердикт":       f"{_VERDICT_ICON.get(c.verdict,'?')} {_VERDICT_LABEL.get(c.verdict, c.verdict or '—')}",
            "Балл":          c.risk_score if c.risk_score is not None else "—",
            "Кэш до":        c.expires_at.strftime("%d.%m %H:%M") if c.expires_at else "—",
        })

    if not rows:
        st.info("Нет записей с выбранным вердиктом.")
        return

    import pandas as pd
    st.dataframe(
        pd.DataFrame(rows),
        width="stretch",
        hide_index=True,
        column_config={
            "Дата проверки": st.column_config.TextColumn(width="small"),
            "ИНН":           st.column_config.TextColumn(width="small"),
            "Наименование":  st.column_config.TextColumn(width="large"),
            "ОГРН":          st.column_config.TextColumn(width="small"),
            "Тип":           st.column_config.TextColumn(width="medium"),
            "Статус":        st.column_config.TextColumn(width="medium"),
            "Вердикт":       st.column_config.TextColumn(width="medium"),
            "Балл":          st.column_config.NumberColumn(width="small"),
            "Кэш до":        st.column_config.TextColumn(width="small"),
        },
    )
    st.caption(f"Показано {len(rows)} из {len(records)} записей.")


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _age_ok(reg_date) -> bool:
    if reg_date is None:
        return False
    from datetime import date
    today  = date.today()
    months = (today.year - reg_date.year) * 12 + (today.month - reg_date.month)
    return months >= 12


def _capital_ok(capital) -> bool:
    return capital is not None and float(capital) > 10_000
