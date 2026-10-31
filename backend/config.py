"""
Shared runtime configuration for the FastAPI app and the Celery worker.

Both tiers must read the same env vars so they always point at the same Redis
and data directories (P1-13: worker previously hardcoded localhost).
"""
import os

from dotenv import load_dotenv

load_dotenv()

# --- Redis -----------------------------------------------------------------
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

# Broker and result backend share db 0 by default; cache uses its own db.
REDIS_DB_BROKER = int(os.getenv("REDIS_DB_BROKER", "0"))
REDIS_DB_RESULTS = int(os.getenv("REDIS_DB_RESULTS", "0"))
REDIS_DB_CACHE = int(os.getenv("REDIS_DB_CACHE", "1"))

REDIS_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}"
REDIS_URL_BROKER = os.getenv("REDIS_URL_BROKER", f"{REDIS_URL}/{REDIS_DB_BROKER}")
REDIS_URL_RESULTS = os.getenv("REDIS_URL_RESULTS", f"{REDIS_URL}/{REDIS_DB_RESULTS}")

# --- Paths -------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)

# Served statically by the SPA mount. Datasets live here so the frontend can
# fetch the raw CSV in small-file mode.
PUBLIC_DIR = os.path.abspath(os.getenv("PUBLIC_DIR", os.path.join(PROJECT_ROOT, "public")))

# Must stay OUTSIDE the served root: pre-cleaning snapshots are user data.
DATA_DIR = os.path.abspath(os.path.join(PROJECT_ROOT, "backend", "data"))
CHECKPOINTS_DIR = os.path.join(DATA_DIR, "checkpoints")

# --- Upload limits (P1-14) ---------------------------------------------------
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "200"))
MAX_UPLOAD_COLUMNS = int(os.getenv("MAX_UPLOAD_COLUMNS", "2000"))

# --- HTTP --------------------------------------------------------------------
CORS_ORIGINS = [
    o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()
]

# P1-2: when set, every /api/* request must present `Authorization: Bearer <token>`.
# Unset keeps the local dev experience open. Full JWT/OIDC multi-user auth is a
# deployment-level decision; this is the single-tenant stopgap.
API_AUTH_TOKEN = os.getenv("API_AUTH_TOKEN")

# Requests per minute per IP on expensive (AI / simulation) endpoints.
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "20"))

# --- Celery task policy ------------------------------------------------------
TASK_SOFT_TIME_LIMIT = int(os.getenv("TASK_SOFT_TIME_LIMIT", "1500"))
TASK_TIME_LIMIT = int(os.getenv("TASK_TIME_LIMIT", "1800"))

# --- Data integrity ----------------------------------------------------------
# Files larger than this are paginated server-side instead of parsed in-browser.
LARGE_FILE_THRESHOLD_MB = float(os.getenv("LARGE_FILE_THRESHOLD_MB", "8"))
