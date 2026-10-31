# 🚀 DataCraft Studio: AI-Powered Dataset Cleaning & Delta Evaluation

DataCraft Studio is an enterprise-ready dataset cleaning and analysis copilot. It generates intelligent cleaning recipes, runs parallel simulations to evaluate candidate treatments, measures before/after delta effectiveness (quality delta, skew reduction, ML benchmark improvement, leakage absence), and applies transactional transformations with non-destructive checkpoint rollbacks.

---

## 🛠️ Architecture & Tech Stack

```
┌────────────────────────────────┐       ┌────────────────────────────────┐
│   React 19 + Vite Frontend     │       │     FastAPI Web Service        │
│  - AG Grid Community v34       │ ◄───► │  - Windowed Row Pagination     │
│  - Lucide & React Icons        │       │  - Transactional Checkpoints   │
│  - Real-time Polling & Metrics │       │  - Sliding Window Rate Limiter │
└────────────────────────────────┘       └──────────────┬─────────────────┘
                                                        │
                                         ┌──────────────▼─────────────────┐
                                         │       Redis 7 (Broker/Cache)   │
                                         │  - Task Queue (DB 0)           │
                                         │  - Profile Cache (DB 1)        │
                                         └──────────────┬─────────────────┘
                                                        │
                                         ┌──────────────▼─────────────────┐
                                         │     Celery Async Worker        │
                                         │  - Pandas 3.0 CoW Operations   │
                                         │  - 28 Safe Engine Functions    │
                                         │  - LLM Cleaning Recipes        │
                                         │  - Parallel Monte Carlo Sim    │
                                         └────────────────────────────────┘
```

- **Frontend**: React 19, Vite 7, AG Grid Community 34, React Router 7.
- **Backend API**: FastAPI 0.139, Pydantic, Gunicorn/Uvicorn.
- **Async Workers**: Celery 5.6 backed by Redis 7 (zero `exec()` or RCE vectors; strict dispatch).
- **Data Engine**: Pandas 3.0 (Copy-on-Write compliant), NumPy 2.5, SciPy 1.18, OpenPyXL 3.1.
- **AI Integration**: OpenRouter API (`google/gemini-2.5-flash` or configurable model) with structured JSON schema outputs.

---

## ✨ Core Capabilities

1. **Intelligent Recipe Generation**: Deep statistical profiling feeds LLM copilot to formulate end-to-end cleaning plans.
2. **Parallel Candidate Simulation**: Test multiple cleaning candidate pipelines asynchronously before applying destructive changes.
3. **Delta Effectiveness Scoring**: Evaluates clean effectiveness by comparing baseline vs. cleaned datasets across:
   - Missing value reduction (weight: 0.25)
   - Distribution skewness remediation (weight: 0.20)
   - ML validation benchmark delta (weight: 0.35)
   - Feature leakage absence check (weight: 0.20)
4. **Non-Destructive Checkpoint Pool**: Pre-cleaning snapshots saved automatically to `backend/data/checkpoints/` with one-click restore and purge APIs.
5. **Windowed Large-File Pagination**: Efficient streaming row chunking for files exceeding threshold (default > 8 MB).
6. **Hardened Security**:
   - Strict path traversal guards with containment verification.
   - Zero arbitrary code execution (`exec()` removed from Celery workers).
   - In-memory sliding-window IP rate limiting on compute-heavy AI/simulation routes.
   - Optional Bearer token authentication via `API_AUTH_TOKEN`.

---

## ⚙️ Environment Configuration

Create a `.env` file in `backend/` (or repository root for Docker Compose):

| Variable | Default | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | *(None)* | OpenRouter API key for LLM recipes and column insights. |
| `API_AUTH_TOKEN` | *(None)* | If set, enforces `Authorization: Bearer <token>` on all `/api/*` routes. |
| `REDIS_HOST` | `localhost` | Redis server hostname. |
| `REDIS_PORT` | `6379` | Redis server port. |
| `REDIS_DB_BROKER` | `0` | Redis DB for Celery task queue. |
| `REDIS_DB_CACHE` | `1` | Redis DB for dataset profile cache. |
| `PUBLIC_DIR` | `../public` | Directory containing hosted CSV datasets and static assets. |
| `RATE_LIMIT_PER_MINUTE` | `20` | Max requests per minute per IP on expensive endpoints. |
| `MAX_UPLOAD_MB` | `200` | Max file upload size in MB. |
| `MAX_UPLOAD_COLUMNS` | `2000` | Max column count permitted on CSV upload. |
| `LARGE_FILE_THRESHOLD_MB` | `8` | Files larger than this threshold are paginated server-side. |

---

## 🚀 Quickstart

### Option A: Docker Compose (Recommended for Production)

```bash
# Set your OpenRouter key
export OPENROUTER_API_KEY="your-openrouter-key"

# Build and start Redis, FastAPI backend, and Celery worker
docker compose up --build -d

# Check service health
docker compose ps
```
The application will be accessible at `http://localhost:8000`.

---

### Option B: Local Development

#### Prerequisites
- Node.js 20+ & npm
- Python 3.12+
- Running Redis instance (`localhost:6379`)

#### 1. Setup Backend
```bash
cd backend
python -m venv .venv

# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# Linux / macOS:
source .venv/bin/activate

pip install -r requirements.txt
```

#### 2. Start Backend API & Celery Worker
```bash
# Terminal 1: FastAPI API
uvicorn main:app --reload --port 8000

# Terminal 2: Celery Worker
# (On Windows, add --pool=solo)
celery -A celery_worker.celery_app worker --loglevel=info --pool=solo
```

#### 3. Setup & Start Frontend
```bash
# In repository root:
npm install
npm run dev
```
The development UI will be live at `http://localhost:5173` (proxies API requests to port 8000).

---

## 🧪 Testing & Code Quality

### Backend Automated Test Suite
The backend contains a comprehensive 111-test suite covering routes, security path containment, rate limiting, malformed CSV error handling, all 28 execution engine functions, transactional rollbacks, and effectiveness scoring:

```bash
cd backend
pytest -v
```

### Frontend Linting & Production Build
```bash
npm run lint    # ESLint verification (zero warnings policy)
npm run build   # Vite production build
```

---

## 📄 License
MIT License
