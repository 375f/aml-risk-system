"""
app.py — точка входа AML Risk System.

Запуск:
    streamlit run app.py
"""

import asyncio
import sys

# Устраняет "Exception in _ProactorBasePipeTransport._call_connection_lost()"
# на Windows с Python 3.12+ — баг в ProactorEventLoop при разрыве соединения.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import streamlit as st

st.set_page_config(
    page_title="AML Risk System",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Глобальные стили — тёмная тема Т-Банка
# ---------------------------------------------------------------------------

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

/* Основа */
html, body, [class*="css"] {
    font-family: 'Inter', sans-serif !important;
    background-color: #1A1A1A;
    color: #FFFFFF;
}

/* Главная область */
.main .block-container {
    background-color: #1A1A1A;
    padding-top: 1.5rem;
}

/* Боковая панель */
[data-testid="stSidebar"] {
    background-color: #242424 !important;
    border-right: 1px solid #333333;
}
[data-testid="stSidebar"] * {
    color: #FFFFFF !important;
}
[data-testid="stSidebar"] a {
    color: #FFE000 !important;
}

/* Кнопки */
.stButton > button {
    background-color: #FFE000 !important;
    color: #000000 !important;
    font-family: 'Inter', sans-serif !important;
    font-weight: 600 !important;
    border: none !important;
    border-radius: 8px !important;
    padding: 10px 24px !important;
    font-size: 14px !important;
    transition: background-color 0.15s ease;
}
.stButton > button:hover {
    background-color: #F5D800 !important;
    color: #000000 !important;
}
.stButton > button:disabled {
    background-color: #404040 !important;
    color: #8C8C8C !important;
}

/* Табы */
.stTabs [data-baseweb="tab-list"] {
    background-color: #242424;
    border-radius: 10px;
    gap: 4px;
    padding: 4px;
    border: 1px solid #333333;
}
.stTabs [data-baseweb="tab"] {
    background-color: transparent !important;
    color: #8C8C8C !important;
    border-radius: 6px !important;
    font-family: 'Inter', sans-serif !important;
    font-weight: 500;
    padding: 8px 20px;
    border: none !important;
}
.stTabs [aria-selected="true"] {
    background-color: #FFE000 !important;
    color: #000000 !important;
    font-weight: 600 !important;
}
.stTabs [data-baseweb="tab-panel"] {
    background-color: transparent;
    padding-top: 1rem;
}

/* Поля ввода */
[data-testid="stTextInput"] input,
[data-testid="stTextArea"] textarea {
    background-color: #2E2E2E !important;
    border: 1px solid #404040 !important;
    border-radius: 8px !important;
    color: #FFFFFF !important;
    font-family: 'Inter', sans-serif !important;
}
[data-testid="stTextInput"] input:focus,
[data-testid="stTextArea"] textarea:focus {
    border-color: #FFE000 !important;
    box-shadow: 0 0 0 2px rgba(255, 224, 0, 0.2) !important;
}
[data-testid="stTextInput"] label,
[data-testid="stTextArea"] label {
    color: #8C8C8C !important;
    font-size: 13px !important;
    font-weight: 500 !important;
}

/* Файл-загрузчик */
[data-testid="stFileUploader"] {
    background-color: #2E2E2E;
    border: 2px dashed #404040;
    border-radius: 12px;
}
[data-testid="stFileUploader"]:hover {
    border-color: #FFE000;
}
[data-testid="stFileUploader"] label {
    color: #FFFFFF !important;
}
[data-testid="stFileUploader"] small {
    color: #8C8C8C !important;
}

/* Метрики */
[data-testid="stMetric"] {
    background-color: #242424;
    border-radius: 12px;
    padding: 16px 20px;
    border: 1px solid #333333;
}
[data-testid="stMetricLabel"] p {
    color: #8C8C8C !important;
    font-size: 12px !important;
    font-weight: 500 !important;
}
[data-testid="stMetricValue"] {
    color: #FFFFFF !important;
    font-size: 22px !important;
    font-weight: 700 !important;
}

/* Dataframe / таблицы */
[data-testid="stDataFrame"] {
    border-radius: 10px;
    overflow: hidden;
    border: 1px solid #333333;
}
[data-testid="stDataFrame"] th {
    background-color: #2E2E2E !important;
    color: #8C8C8C !important;
    font-size: 12px !important;
    font-weight: 600 !important;
}
[data-testid="stDataFrame"] td {
    color: #FFFFFF !important;
    font-size: 13px !important;
}

/* Expander */
[data-testid="stExpander"] {
    background-color: #242424;
    border: 1px solid #333333;
    border-radius: 10px;
}
[data-testid="stExpander"] summary {
    color: #FFFFFF !important;
}

/* Multiselect */
[data-testid="stMultiSelect"] [data-baseweb="select"] {
    background-color: #2E2E2E !important;
    border-color: #404040 !important;
    border-radius: 8px !important;
}
[data-testid="stMultiSelect"] [data-baseweb="select"] * {
    color: #FFFFFF !important;
}

/* Select / dropdown */
[data-testid="stSelectbox"] [data-baseweb="select"] {
    background-color: #2E2E2E !important;
    border-color: #404040 !important;
    border-radius: 8px !important;
}

/* Divider */
hr {
    border-color: #333333 !important;
}

/* Alerts / messages */
[data-testid="stAlert"] {
    border-radius: 10px !important;
    border: none !important;
}
div[data-baseweb="notification"] {
    background-color: #2E2E2E !important;
    border-radius: 10px !important;
}

/* Progress bar */
[data-testid="stProgressBar"] > div {
    background-color: #333333;
    border-radius: 4px;
}
[data-testid="stProgressBar"] > div > div {
    background-color: #FFE000;
    border-radius: 4px;
}

/* Spinner */
[data-testid="stSpinner"] {
    color: #FFE000 !important;
}

/* Caption / мелкий текст */
[data-testid="stCaptionContainer"] p {
    color: #8C8C8C !important;
}

/* Скроллбар */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: #1A1A1A; }
::-webkit-scrollbar-thumb { background: #404040; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #FFE000; }

/* Заголовки */
h1 { font-weight: 700 !important; color: #FFFFFF !important; }
h2 { font-weight: 600 !important; color: #FFFFFF !important; }
h3 { font-weight: 600 !important; color: #FFFFFF !important; }

/* Subheader */
[data-testid="stHeadingWithActionElements"] h2 {
    color: #FFFFFF !important;
    font-weight: 600 !important;
}

/* Info / warning / error / success override */
.stAlert [data-testid="stMarkdownContainer"] p {
    color: #FFFFFF !important;
}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Сайдбар
# ---------------------------------------------------------------------------

with st.sidebar:
    # Логотип Т-Банка
    st.markdown("""
    <div style="display:flex;align-items:center;gap:14px;padding:4px 0 20px 0;">
        <div style="
            width:48px;height:48px;
            background:#FFE000;
            border-radius:12px;
            display:flex;align-items:center;justify-content:center;
            font-size:26px;font-weight:900;color:#000000;
            font-family:'Inter',sans-serif;
            flex-shrink:0;
        ">Т</div>
        <div>
            <div style="font-size:16px;font-weight:700;color:#FFFFFF;line-height:1.2;">
                AML Risk System
            </div>
            <div style="font-size:11px;color:#8C8C8C;">Версия 1.0.0</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    st.markdown("**О системе**")
    st.markdown(
        "<div style='font-size:13px;color:#8C8C8C;line-height:1.6;'>"
        "Интеллектуальная система раннего предупреждения рисков блокировки "
        "расчётного счёта для субъектов малого предпринимательства."
        "</div>",
        unsafe_allow_html=True,
    )

    st.markdown("")
    st.markdown("""
    <div style="background:#2E2E2E;border-radius:10px;padding:14px;margin-bottom:8px;border:1px solid #333;">
        <div style="font-size:13px;font-weight:600;color:#FFE000;margin-bottom:6px;">
            📊 Модуль 1 — Анализ выписки
        </div>
        <div style="font-size:12px;color:#8C8C8C;line-height:1.5;">
            Загрузите CSV/XLSX. Система вычислит 7 признаков риска
            и классифицирует уровень.
        </div>
    </div>
    <div style="background:#2E2E2E;border-radius:10px;padding:14px;border:1px solid #333;">
        <div style="font-size:13px;font-weight:600;color:#FFE000;margin-bottom:6px;">
            🔍 Модуль 2 — Проверка контрагента
        </div>
        <div style="font-size:12px;color:#8C8C8C;line-height:1.5;">
            Введите ИНН. Оценка риска по 5 критериям 115-ФЗ
            через данные Rusprofile.
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    st.markdown("**Нормативная база**")
    st.markdown(
        """
- [115-ФЗ «О ПОД/ФТ»](https://www.consultant.ru/document/cons_doc_LAW_32834/)
- [18-МР ЦБ РФ — налоговая нагрузка](https://www.cbr.ru/StaticHtml/File/41290/18MR.pdf)
- [19-МР ЦБ РФ — наличные операции](https://www.cbr.ru/StaticHtml/File/41290/19MR.pdf)
- [ЕГРЮЛ — поиск по ИНН](https://egrul.nalog.ru/)
        """
    )

    st.divider()

    st.markdown("""
    <div style="font-size:11px;color:#8C8C8C;line-height:1.8;">
        <div>Пороги риска (ЦБ РФ)</div>
        <div>• Доля наличных ≥ 30%</div>
        <div>• Налоговая нагрузка &lt; 0.9%</div>
        <div>• Транзитные операции &gt; 50%</div>
        <div>• Переводы физлицам &gt; 30%</div>
        <div>• Концентрация &gt; 80%</div>
    </div>
    """, unsafe_allow_html=True)

    st.divider()
    st.caption("КНИТУ-КАИ · Дипломная работа · 2026")
    st.caption("09.03.04 «Программная инженерия»")


# ---------------------------------------------------------------------------
# Заголовок
# ---------------------------------------------------------------------------

st.markdown("""
<div style="margin-bottom:8px;">
    <h1 style="margin:0;font-size:28px;font-weight:700;color:#FFFFFF;">
        Система анализа рисков блокировки счетов
    </h1>
    <div style="font-size:13px;color:#8C8C8C;margin-top:4px;">
        115-ФЗ &nbsp;·&nbsp; ПОД/ФТ &nbsp;·&nbsp; Методрекомендации ЦБ РФ 18-МР и 19-МР
    </div>
</div>
""", unsafe_allow_html=True)

st.divider()

# ---------------------------------------------------------------------------
# Вкладки
# ---------------------------------------------------------------------------

tab1, tab2 = st.tabs(["📊 Анализ выписки", "🔍 Проверка контрагента"])

with tab1:
    from module1.ui import render as render_module1
    render_module1()

with tab2:
    from module2.ui import render as render_module2
    render_module2()
