"""
smoke_test.py  —  end-to-end smoke test for all implemented modules.

Run from aml_system/:
    python smoke_test.py
"""

import sys
import io
import textwrap
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

PASS = "[PASS]"
FAIL = "[FAIL]"
results: list[tuple[str, bool, str]] = []


def check(name: str, fn):
    try:
        fn()
        results.append((name, True, ""))
        print(f"  {PASS}  {name}")
    except Exception as e:
        results.append((name, False, str(e)))
        print(f"  {FAIL}  {name}")
        print(f"         {traceback.format_exc().splitlines()[-1]}")


# ===========================================================================
# 1. Parser
# ===========================================================================
print("\n[1] Parser")

def _parser_format_a():
    from module1.parser import parse_statement
    csv = textwrap.dedent("""
        Date;Description;Debit;Credit;Counterparty;INN
        01.03.2024;Cash withdrawal;50000;;ATM;
        05.03.2024;Payment to supplier;;200000;LLC Rose;7701234560
        10.03.2024;VAT tax;20000;;FTS;7707289922
        15.03.2024;Salary;30000;;Petrov I.I.;
    """).strip()
    buf = io.BytesIO(csv.encode()); buf.name = "test.csv"
    df, d_from, d_to = parse_statement(buf)
    assert len(df) == 4, f"expected 4 rows, got {len(df)}"
    assert set(df.columns) >= {"date", "amount", "type", "description"}
    assert (df["amount"] > 0).all()

check("Format A  (Debit / Credit columns)", _parser_format_a)


def _parser_format_b():
    from module1.parser import parse_statement
    csv = textwrap.dedent("""
        Date;Amount;Type;Description
        01.03.2024;50000;Expense;Cash withdrawal
        05.03.2024;200000;Income;Payment received
        10.03.2024;20000;Expense;VAT tax
    """).strip()
    buf = io.BytesIO(csv.encode()); buf.name = "test.csv"
    df, _, _ = parse_statement(buf)
    assert len(df) == 3
    assert set(df["type"].unique()) <= {"debit", "credit"}

check("Format B  (Amount + Type column)", _parser_format_b)


def _parser_xlsx():
    import openpyxl
    from module1.parser import parse_statement
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["Date", "Description", "Debit", "Credit"])
    ws.append(["01.03.2024", "Cash", 50000, None])
    ws.append(["05.03.2024", "Income", None, 100000])
    buf = io.BytesIO(); wb.save(buf); buf.seek(0); buf.name = "test.xlsx"
    df, _, _ = parse_statement(buf)
    assert len(df) == 2

check("XLSX parse", _parser_xlsx)


def _parser_cp1251():
    from module1.parser import parse_statement
    content = "Date;Description;Debit;Credit\n01.03.2024;Payment;50000;\n"
    buf = io.BytesIO(content.encode("cp1251")); buf.name = "test.csv"
    df, _, _ = parse_statement(buf)
    assert len(df) == 1

check("Encoding  CP1251", _parser_cp1251)


def _parser_errors():
    from module1.parser import parse_statement, ParseError, ColumnMappingError
    # Empty file
    buf = io.BytesIO(b"Date;Amount\n"); buf.name = "e.csv"
    try:
        parse_statement(buf)
        raise AssertionError("should raise")
    except (ParseError, ColumnMappingError):
        pass
    # Unsupported format
    buf2 = io.BytesIO(b"garbage"); buf2.name = "x.pdf"
    try:
        parse_statement(buf2)
        raise AssertionError("should raise")
    except ParseError:
        pass

check("Error handling (empty / unsupported)", _parser_errors)


# ===========================================================================
# 2. Features
# ===========================================================================
print("\n[2] Features")

def _make_df():
    import pandas as pd
    rows = [
        ("2024-03-01", 50000, "debit",  "Снятие наличных через банкомат", "Банкомат ВТБ",  ""),
        ("2024-03-02", 20000, "debit",  "Налог НДС Q1",                   "ИФНС",          "7707289922"),
        ("2024-03-03", 30000, "debit",  "Зарплата Петров И.И.",           "Петров И.И.",   ""),
        ("2024-03-04", 40000, "debit",  "Аренда офиса",                   "ИП Смирнов",    "501234567890"),
        ("2024-03-05",200000, "credit", "Оплата от клиента",              "ООО Альфа",     "7701234560"),
    ]
    df = pd.DataFrame(rows, columns=["date","amount","type","description","counterparty","inn"])
    df["date"] = pd.to_datetime(df["date"])
    df["amount"] = df["amount"].astype(float)
    return df

def _features_compute():
    from module1.features import compute_features, FEATURE_KEYS
    df = _make_df()
    f = compute_features(df)
    assert set(f.keys()) == set(FEATURE_KEYS), f"missing keys: {set(FEATURE_KEYS) - set(f.keys())}"
    for k, v in f.items():
        assert 0.0 <= v <= 1.0, f"{k}={v} out of [0,1]"

check("compute_features  (7 keys, all in [0,1])", _features_compute)


def _features_cash_ratio():
    from module1.features import compute_features
    df = _make_df()
    f = compute_features(df)
    # cash debit=50000, total debit=140000  ->  ~0.357
    assert abs(f["cash_ratio"] - 50000/140000) < 0.01

check("cash_ratio formula", _features_cash_ratio)


def _features_describe():
    from module1.features import compute_features, describe_features
    df = _make_df()
    desc = describe_features(compute_features(df))
    assert len(desc) == 7
    for item in desc:
        assert "key" in item and "is_triggered" in item
        assert isinstance(item["is_triggered"], bool)

check("describe_features  (7 items, is_triggered bool)", _features_describe)


def _features_vector():
    from module1.features import compute_features, feature_vector, FEATURE_KEYS
    df = _make_df()
    vec = feature_vector(compute_features(df))
    assert len(vec) == 7
    assert all(isinstance(v, float) for v in vec)

check("feature_vector  (length 7, all float)", _features_vector)


def _features_empty_df():
    import pandas as pd
    from module1.features import compute_features
    empty = pd.DataFrame(columns=["date","amount","type","description","counterparty","inn"])
    f = compute_features(empty)
    assert all(v == 0.0 for v in f.values()), f"expected all zeros: {f}"

check("Empty DataFrame -> all zeros", _features_empty_df)


# ===========================================================================
# 3. ML dataset + model
# ===========================================================================
print("\n[3] ML")

def _dataset_exists():
    p = Path("ml/data.csv")
    assert p.exists(), "ml/data.csv not found — run: python ml/dataset.py"
    import pandas as pd
    df = pd.read_csv(p)
    assert len(df) == 1000
    assert set(df.columns) >= {"cash_ratio", "risk_class", "risk_label"}
    assert df.isnull().sum().sum() == 0

check("ml/data.csv  (1000 rows, no NaN)", _dataset_exists)


def _model_exists():
    p = Path("ml/model.joblib")
    assert p.exists(), "ml/model.joblib not found — run: python ml/train.py"
    import joblib
    model = joblib.load(p)
    assert hasattr(model, "predict")

check("ml/model.joblib  (exists, loadable)", _model_exists)


def _classifier_predict():
    from module1.classifier import predict

    low = dict(cash_ratio=0.05, tax_ratio=0.06, transit_ratio=0.10,
               okved_mismatch=0.10, avg_tx_norm=0.80,
               counterparty_concentration=0.20, fl_ratio=0.04)
    r = predict(low)
    assert r["risk_level"] == "low",  f"expected low, got {r['risk_level']}"
    assert 0.0 <= r["risk_proba"] <= 1.0
    assert len(r["importances"]) == 7

    high = dict(cash_ratio=0.55, tax_ratio=0.002, transit_ratio=0.75,
                okved_mismatch=0.82, avg_tx_norm=0.08,
                counterparty_concentration=0.90, fl_ratio=0.50)
    r2 = predict(high)
    assert r2["risk_level"] == "high", f"expected high, got {r2['risk_level']}"

check("classifier.predict  (low -> low, high -> high)", _classifier_predict)


def _pipeline_e2e():
    from module1.parser import parse_statement
    from module1.features import compute_features
    from module1.classifier import predict

    csv = textwrap.dedent("""
        Date;Description;Debit;Credit;Counterparty;INN
        01.03.2024;Cash withdrawal;50000;;ATM;
        05.03.2024;Payment;;200000;LLC Alpha;7701234560
        10.03.2024;VAT tax;20000;;FTS;7707289922
        15.03.2024;Salary;30000;;Petrov I.I.;
        20.03.2024;Rent;40000;;IP Smirnov;501234567890
    """).strip()
    buf = io.BytesIO(csv.encode()); buf.name = "test.csv"
    df, _, _ = parse_statement(buf)
    feats = compute_features(df)
    result = predict(feats)
    assert result["risk_level"] in {"low", "medium", "high"}
    assert len(result["importances"]) == 7

check("Full pipeline: parse -> features -> predict", _pipeline_e2e)


# ===========================================================================
# 4. Database
# ===========================================================================
print("\n[4] Database")

def _db_connect():
    from db.connection import engine
    from sqlalchemy import text
    with engine.connect() as conn:
        v = conn.execute(text("SELECT version()")).scalar()
    assert "PostgreSQL" in v

check("PostgreSQL connection", _db_connect)


def _db_tables():
    from db.connection import engine
    from sqlalchemy import inspect as sa_inspect
    insp = sa_inspect(engine)
    tables = insp.get_table_names()
    for t in ("analysis_history", "risk_factors", "contractors"):
        assert t in tables, f"table {t!r} missing"

check("Tables exist  (analysis_history, risk_factors, contractors)", _db_tables)


def _db_save_analysis():
    from db.connection import SessionLocal
    from db.crud import save_analysis, get_history
    session = SessionLocal()
    rec = save_analysis(session, {
        "filename": "smoke_test.csv",
        "period_start": "2024-03-01",
        "period_end": "2024-03-31",
        "total_debit": 140000,
        "total_credit": 200000,
        "tx_count": 5,
        "risk_level": "low",
        "risk_score": 0.90,
        "features_json": {"cash_ratio": 0.05},
        "importances_json": {"tax_ratio": 0.25},
        "factors": [
            {"factor_name": "cash_ratio", "factor_value": 0.05,
             "threshold": 0.30, "is_triggered": False, "importance": 0.09},
        ],
    })
    assert rec.id is not None
    history = get_history(session, limit=5)
    assert any(r.id == rec.id for r in history)
    session.close()

check("save_analysis + get_history", _db_save_analysis)


def _db_contractor_cache():
    from db.connection import SessionLocal
    from db.crud import save_contractor, get_contractor_cache
    session = SessionLocal()

    expires_ok  = datetime.now(timezone.utc) + timedelta(hours=24)
    expires_old = datetime.now(timezone.utc) - timedelta(hours=1)

    # unique INN each run to avoid conflicts
    inn_hit  = f"770{datetime.now().microsecond:07d}"[:10]
    inn_miss = f"771{datetime.now().microsecond:07d}"[:10]

    save_contractor(session, {"inn": inn_hit,  "name": "LLC Test", "expires_at": expires_ok})
    save_contractor(session, {"inn": inn_miss, "name": "LLC Old",  "expires_at": expires_old})

    assert get_contractor_cache(session, inn_hit)  is not None, "cache HIT failed"
    assert get_contractor_cache(session, inn_miss) is None,     "cache MISS failed (expired TTL)"
    session.close()

check("save_contractor + cache TTL (hit / miss)", _db_contractor_cache)


# ===========================================================================
# Summary
# ===========================================================================
total  = len(results)
passed = sum(1 for _, ok, _ in results if ok)
failed = total - passed

print(f"\n{'='*55}")
print(f"  Results: {passed}/{total} passed", end="")
if failed:
    print(f"  ({failed} FAILED)")
    print()
    for name, ok, err in results:
        if not ok:
            print(f"  FAIL: {name}")
            print(f"        {err}")
else:
    print("  -- all OK")
print(f"{'='*55}\n")

sys.exit(0 if failed == 0 else 1)
