import os
from dotenv import load_dotenv

load_dotenv()

# База данных
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost:5432/aml_db")

# Rusprofile
RUSPROFILE_TIMEOUT = int(os.getenv("RUSPROFILE_TIMEOUT", "30"))

# Пороги риска — Модуль 1 (источники: 18-МР и 19-МР ЦБ РФ от 21.07.2017)
CASH_RATIO_THRESHOLD = 0.30        # 19-МР: доля наличных >= 30% → риск
TAX_RATIO_THRESHOLD = 0.009        # 18-МР: налоговая нагрузка < 0.9% → риск
TRANSIT_RATIO_THRESHOLD = 0.50     # транзитный характер > 50% → риск
OKVED_MISMATCH_THRESHOLD = 0.60    # несоответствие ОКВЭД > 60% → риск
FL_RATIO_THRESHOLD = 0.30          # доля переводов физлицам > 30% → риск
CONCENTRATION_THRESHOLD = 0.80     # концентрация контрагентов > 80% → риск
AVG_TX_CONTROL_LIMIT = 600_000     # суммы до 600 000 руб. не требуют обязательного контроля

# Скоринг — Модуль 2
SCORE_LIQUIDATED = 50
SCORE_LIQUIDATING = 40
SCORE_YOUNG_3M = 30
SCORE_YOUNG_6M = 20
SCORE_YOUNG_12M = 10
SCORE_MASS_ADDRESS = 20
SCORE_MASS_DIRECTOR = 20
SCORE_MIN_CAPITAL = 10

VERDICT_SAFE_MAX = 25
VERDICT_CAUTION_MAX = 60

# Кэш контрагентов
CONTRACTOR_CACHE_TTL_HOURS = int(os.getenv("CONTRACTOR_CACHE_TTL_HOURS", "24"))

# Модель
MODEL_PATH = os.getenv("MODEL_PATH", "ml/model.joblib")
