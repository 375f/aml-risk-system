"""
module1/ui.py — Streamlit-компонент вкладки «Анализ выписки».

Вызывается из app.py:
    from module1.ui import render
    with tab1:
        render()
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from db.connection import SessionLocal
from db.crud import get_history, save_analysis
from module1.classifier import predict
from module1.features import FEATURE_META, compute_features, describe_features
from module1.parser import ColumnMappingError, ParseError, parse_statement

# ---------------------------------------------------------------------------
# Палитра T-Bank
# ---------------------------------------------------------------------------

_RISK_COLOR  = {"low": "#00C853", "medium": "#FFE000", "high": "#FF3B30"}
_RISK_LABEL  = {"low": "Низкий риск", "medium": "Средний риск", "high": "Высокий риск"}
_RISK_ICON   = {"low": "🟢", "medium": "🟡", "high": "🔴"}
_STATUS_ICON = {True: "⚠ Риск", False: "✓ Норма"}


# ---------------------------------------------------------------------------
# Общие UI-компоненты
# ---------------------------------------------------------------------------

def _risk_card(level: str, proba: float, triggered_count: int, filename: str) -> None:
    """Карточка уровня риска с левой цветной полосой (стиль Т-Банка)."""
    color = _RISK_COLOR[level]
    label = _RISK_LABEL[level]
    icon  = _RISK_ICON[level]
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
                {icon}&nbsp; {label}
            </div>
            <div style="color:#8C8C8C;font-size:13px;margin-top:6px;">
                Уверенность модели:&nbsp;<strong style="color:#FFFFFF;">{proba*100:.1f}%</strong>
                &nbsp;·&nbsp;
                Сработавших признаков:&nbsp;<strong style="color:#FFFFFF;">{triggered_count} из 7</strong>
                &nbsp;·&nbsp;
                <span style="color:#8C8C8C;">{filename}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _badge(text: str, color: str = "#8C8C8C", bg: str = "#2E2E2E") -> str:
    return (
        f'<span style="display:inline-block;background:{bg};color:{color};'
        f'border-radius:6px;padding:2px 10px;font-size:12px;font-weight:600;">{text}</span>'
    )


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------

def render() -> None:
    """Отрендерить всю вкладку «Анализ выписки»."""
    st.subheader("Загрузка банковской выписки")
    _section_upload()

    if "analysis_result" in st.session_state:
        st.divider()
        _section_result()

    st.divider()
    _section_history()


# ---------------------------------------------------------------------------
# Секция 1 — загрузка файла
# ---------------------------------------------------------------------------

def _section_upload() -> None:
    uploaded = st.file_uploader(
        "Выберите файл выписки (CSV или XLSX)",
        type=["csv", "xlsx", "xls"],
        help="Поддерживаются форматы большинства российских банков (Сбербанк, Альфа, Тинькофф, ВТБ и др.)",
    )

    okved = st.text_input(
        "Код ОКВЭД (необязательно)",
        placeholder="Например: 46, 62, 47.1",
        help="Если указан — система проверит соответствие назначений платежей виду деятельности.",
    ).strip()

    if uploaded is None:
        st.markdown("""
        <div style="
            background:#242424;border:1px solid #333333;border-radius:12px;
            padding:20px 24px;color:#8C8C8C;font-size:13px;
        ">
            Загрузите файл банковской выписки для начала анализа.<br>
            Поддерживаются форматы: <strong style="color:#FFFFFF;">CSV, XLSX, XLS</strong>.
        </div>
        """, unsafe_allow_html=True)
        st.session_state.pop("analysis_result", None)
        return

    cache_key = f"parsed_{uploaded.name}_{uploaded.size}"
    if cache_key not in st.session_state:
        with st.spinner("Читаю файл…"):
            try:
                df, date_from, date_to = parse_statement(uploaded)
                st.session_state[cache_key] = (df, date_from, date_to)
            except (ParseError, ColumnMappingError) as exc:
                st.error(f"Ошибка парсинга: {exc}")
                return
            except Exception as exc:
                st.error(f"Неожиданная ошибка: {exc}")
                return

    df, date_from, date_to = st.session_state[cache_key]

    # Метрики
    debit_total  = float(df[df["type"] == "debit"]["amount"].sum())
    credit_total = float(df[df["type"] == "credit"]["amount"].sum())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Транзакций",   len(df))
    c2.metric("Дебет, руб.",  f"{debit_total:,.0f}".replace(",", " "))
    c3.metric("Кредит, руб.", f"{credit_total:,.0f}".replace(",", " "))
    c4.metric("Период", f"{date_from} — {date_to}" if date_from else "—")

    # Превью
    with st.expander("📋 Распознанные транзакции (первые 20 строк)", expanded=False):
        preview = df.head(20).copy()
        preview["date"]   = preview["date"].dt.strftime("%d.%m.%Y")
        preview["amount"] = preview["amount"].apply(lambda x: f"{x:,.2f}".replace(",", " "))
        st.dataframe(
            preview,
            column_config={
                "date":         st.column_config.TextColumn("Дата"),
                "amount":       st.column_config.TextColumn("Сумма"),
                "type":         st.column_config.TextColumn("Тип"),
                "description":  st.column_config.TextColumn("Назначение"),
                "counterparty": st.column_config.TextColumn("Контрагент"),
                "inn":          st.column_config.TextColumn("ИНН"),
            },
            use_container_width=True,
            hide_index=True,
        )

    if st.button("🔍 Анализировать", type="primary", use_container_width=True):
        _run_analysis(df, date_from, date_to, uploaded.name, debit_total, credit_total, okved)


# ---------------------------------------------------------------------------
# Запуск анализа
# ---------------------------------------------------------------------------

def _run_analysis(
    df: pd.DataFrame,
    date_from,
    date_to,
    filename: str,
    debit_total: float,
    credit_total: float,
    okved: str,
) -> None:
    with st.spinner("Вычисляю признаки риска…"):
        features  = compute_features(df, okved or None)
        described = describe_features(features)
        result    = predict(features)

    factors_data = [
        {
            "factor_name":  d["key"],
            "factor_value": d["value"],
            "threshold":    d["threshold"],
            "is_triggered": d["is_triggered"],
            "importance":   result["importances"].get(d["key"], 0.0),
        }
        for d in described
    ]

    try:
        session = SessionLocal()
        save_analysis(session, {
            "filename":         filename,
            "period_start":     date_from,
            "period_end":       date_to,
            "total_debit":      debit_total,
            "total_credit":     credit_total,
            "tx_count":         len(df),
            "risk_level":       result["risk_level"],
            "risk_score":       result["risk_proba"],
            "features_json":    features,
            "importances_json": result["importances"],
            "factors":          factors_data,
        })
        session.close()
    except Exception:
        pass

    st.session_state["analysis_result"] = {
        "risk_level":   result["risk_level"],
        "risk_proba":   result["risk_proba"],
        "importances":  result["importances"],
        "described":    described,
        "filename":     filename,
    }
    st.rerun()


# ---------------------------------------------------------------------------
# Секция 2 — результат анализа
# ---------------------------------------------------------------------------

def _section_result() -> None:
    r           = st.session_state["analysis_result"]
    level       = r["risk_level"]
    proba       = r["risk_proba"]
    described   = r["described"]
    importances = r["importances"]

    triggered_count = sum(1 for d in described if d["is_triggered"])

    # Риск-карточка (Т-банк стиль)
    _risk_card(level, proba, triggered_count, r["filename"])

    col_chart, col_table = st.columns([1, 1], gap="large")

    # График важности признаков
    with col_chart:
        st.markdown(
            "<div style='font-size:14px;font-weight:600;color:#8C8C8C;"
            "margin-bottom:8px;'>Важность признаков</div>",
            unsafe_allow_html=True,
        )
        imp_df = (
            pd.DataFrame(
                [{"Признак": FEATURE_META[i]["label"], "Важность": v}
                 for i, (k, v) in enumerate(importances.items())],
            )
            .sort_values("Важность", ascending=False)
            .set_index("Признак")
        )
        st.bar_chart(imp_df, height=280, color="#FFE000")

    # Таблица признаков
    with col_table:
        st.markdown(
            "<div style='font-size:14px;font-weight:600;color:#8C8C8C;"
            "margin-bottom:8px;'>Значения признаков</div>",
            unsafe_allow_html=True,
        )
        rows = []
        for d in described:
            val_display = d["display_value"] if d["unit"] else f"{d['value']:.3f}"
            thr_display = (
                f"{d['threshold'] * d['scale']:.1f} {d['unit']}".strip()
                if d["unit"] else f"{d['threshold']:.3f}"
            )
            rows.append({
                "Признак":  d["label"],
                "Значение": val_display,
                "Порог":    thr_display,
                "Статус":   _STATUS_ICON[d["is_triggered"]],
                "Источник": d["source"],
            })
        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Признак":  st.column_config.TextColumn(width="medium"),
                "Значение": st.column_config.TextColumn(width="small"),
                "Порог":    st.column_config.TextColumn(width="small"),
                "Статус":   st.column_config.TextColumn(width="small"),
                "Источник": st.column_config.TextColumn(width="medium"),
            },
        )

    # Детали по сработавшим признакам
    triggered = [d for d in described if d["is_triggered"]]
    if triggered:
        st.markdown(
            "<div style='font-size:14px;font-weight:600;color:#8C8C8C;"
            "margin:16px 0 8px 0;'>Выявленные факторы риска</div>",
            unsafe_allow_html=True,
        )
        for d in triggered:
            st.markdown(
                f"""
                <div style="
                    border-left:3px solid #FFE000;
                    background:#242424;
                    border-radius:8px;
                    padding:12px 16px;
                    margin-bottom:8px;
                    border-top:1px solid #333;border-right:1px solid #333;border-bottom:1px solid #333;
                ">
                    <div style="font-weight:600;color:#FFFFFF;font-size:14px;">
                        ⚠&nbsp; {d['label']}
                    </div>
                    <div style="color:#8C8C8C;font-size:13px;margin-top:4px;">
                        {d['risk_description']}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    else:
        st.markdown(
            """
            <div style="
                border-left:4px solid #00C853;background:#242424;
                border-radius:12px;padding:16px 20px;
                border-top:1px solid #333;border-right:1px solid #333;border-bottom:1px solid #333;
            ">
                <span style="color:#00C853;font-weight:600;">✓&nbsp;</span>
                <span style="color:#FFFFFF;">Ни один из контрольных признаков не превысил пороговых значений ЦБ РФ.</span>
            </div>
            """,
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Секция 3 — история анализов
# ---------------------------------------------------------------------------

def _section_history() -> None:
    st.subheader("История анализов")

    try:
        session = SessionLocal()
        records = get_history(session, limit=50)
        session.close()
    except Exception as exc:
        st.warning(f"База данных недоступна: {exc}")
        return

    if not records:
        st.info("История анализов пуста.")
        return

    col_f1, col_f2, col_f3 = st.columns([2, 2, 1])
    with col_f1:
        date_filter = st.date_input(
            "Показать начиная с",
            value=datetime.now(timezone.utc).date() - timedelta(days=30),
            key="hist_date_filter",
        )
    with col_f2:
        risk_filter = st.multiselect(
            "Уровень риска",
            options=["low", "medium", "high"],
            default=["low", "medium", "high"],
            format_func=lambda x: _RISK_LABEL[x],
            key="hist_risk_filter",
        )
    with col_f3:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🔄 Обновить", key="hist_refresh"):
            st.rerun()

    rows = []
    for rec in records:
        created = rec.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if created.date() < date_filter:
            continue
        if rec.risk_level not in (risk_filter or ["low", "medium", "high"]):
            continue
        rows.append({
            "Дата":         created.strftime("%d.%m.%Y %H:%M"),
            "Файл":         rec.filename or "—",
            "Период":       (f"{rec.period_start} — {rec.period_end}" if rec.period_start else "—"),
            "Транзакций":   rec.tx_count or 0,
            "Дебет, руб.":  f"{rec.total_debit:,.0f}".replace(",", " ") if rec.total_debit else "—",
            "Кредит, руб.": f"{rec.total_credit:,.0f}".replace(",", " ") if rec.total_credit else "—",
            "Риск":         f"{_RISK_ICON.get(rec.risk_level, '?')} {_RISK_LABEL.get(rec.risk_level, rec.risk_level)}",
            "Уверенность":  f"{(rec.risk_score or 0)*100:.1f}%",
        })

    if not rows:
        st.info("Нет записей за выбранный период.")
        return

    st.dataframe(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Дата":         st.column_config.TextColumn(width="small"),
            "Файл":         st.column_config.TextColumn(width="medium"),
            "Период":       st.column_config.TextColumn(width="medium"),
            "Транзакций":   st.column_config.NumberColumn(width="small"),
            "Дебет, руб.":  st.column_config.TextColumn(width="small"),
            "Кредит, руб.": st.column_config.TextColumn(width="small"),
            "Риск":         st.column_config.TextColumn(width="small"),
            "Уверенность":  st.column_config.TextColumn(width="small"),
        },
    )
    st.caption(f"Показано {len(rows)} из {len(records)} записей.")
