"""Central config. Reads .env if present, falls back to sane local defaults."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _load_dotenv():
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()

# ponytail: SQLite fallback so the pipeline runs before Postgres credentials exist.
# SQLAlchemy makes the two interchangeable — set DATABASE_URL in .env for Postgres.
DATABASE_URL = os.environ.get("DATABASE_URL") or f"sqlite:///{ROOT / 'levista.db'}"
USING_FALLBACK_DB = not os.environ.get("DATABASE_URL")

INPUT_DIR = Path(
    os.environ.get(
        "INPUT_DIR",
        r"D:\levista\Levista performance report input files from the respected applications",
    )
)
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", r"D:\levista\output"))

# Business thresholds used by the insights engine (rupees).
MIN_SPEND_FOR_ALERT = 500.0
BREAKEVEN_ROAS = 1.0
HEALTHY_ROAS = 3.0

# Recommendation priority bands, in rupees at stake.
HIGH_IMPACT = 25_000.0
MEDIUM_IMPACT = 5_000.0
