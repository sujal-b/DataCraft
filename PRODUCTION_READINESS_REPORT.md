# DataCraft Studio — Production Readiness Audit

**Audit date:** 2026-09-07
**Scope:** Full stack — React/Vite frontend, FastAPI + Celery + Redis backend, deployment config, data integrity
**Verdict:** ⛔ **NOT READY FOR PRODUCTION.** 5 ship-blockers (2 of them security-critical), 15 high-severity defects.

Every finding below was verified by reading the code and, where possible, by executing it. Verification method is noted on the P0 items.

---

## Executive Summary

The architecture is genuinely good: an async Celery-backed pipeline, a deterministic (no-`exec`) action registry for cleaning, transactional rollback, checkpointing, and a composite effectiveness score. That foundation is worth keeping.

However, **the product's core value proposition — "evaluate cleaning effectiveness by showing delta improvements (baseline vs. after cleaning)" — does not currently work.** The entire Phase 5 feature set (parallel simulation, effectiveness scoring, recipe download, export, checkpoint rollback) is dead code at runtime, for two independent reasons detailed in P0-4 and P0-5. Meanwhile the frontend is fully built to consume it, so the UI silently renders stale/empty states rather than erroring.

On top of that there is an **unauthenticated remote code execution hole** and a **live API key committed to source control**.

| Severity | Count | Meaning |
|---|---|---|
| 🔴 **P0** | 5 | Ship blocker. Security breach, build failure, or core feature non-functional. |
| 🟠 **P1** | 15 | Fix before launch. Data loss, correctness, or operational failure under load. |
| 🟡 **P2** | 14 | Fix in first maintenance release. Quality, maintainability, observability. |
| 🔵 **P3** | 8 | Backlog / hygiene. |

---

# 🔴 P0 — Ship Blockers

## P0-1. Live OpenRouter API key hardcoded in source

**File:** `backend/ai_service.py:7`

```python
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY","sk-or-v1-REDACTED_OPENROUTER_KEY")
```

A real key is committed as the *default value*. Every clone of the repo ships with a working credential, and the key is in git history. The `if not OPENROUTER_API_KEY: raise` guard below it is unreachable dead code — the default always satisfies it, so a missing env var silently falls back to the leaked key instead of failing loudly.

**Remediation (do in this order):**
1. **Revoke the key now** at openrouter.ai before anything else. Assume it is burned.
2. Strip the default:
   ```python
   OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
   if not OPENROUTER_API_KEY:
       raise RuntimeError("OPENROUTER_API_KEY is not set. Refusing to start.")
   ```
3. Purge from history — the key survives in every prior commit, so removing the line is not enough:
   ```bash
   pip install git-filter-repo
   git filter-repo --replace-text <(echo 'sk-or-v1-REDACTED_OPENROUTER_KEY==>REDACTED')
   git push --force-with-lease
   ```
4. Add a pre-commit secret scanner (`gitleaks` or `detect-secrets`) so this cannot recur.
5. Load secrets from a real secret manager (AWS Secrets Manager / Vault) in production, not a `.env` file.

---

## P0-2. Unauthenticated remote code execution

**Files:** `backend/main.py:76-87` (reachable endpoint) → `backend/celery_worker.py:725-734` → `backend/celery_worker.py:683-723`

`POST /api/dataset/{dataset_name}/run-simulation` accepts `plans: Dict[str, Any]` — an arbitrary, unvalidated JSON object. That object flows into:

```python
# celery_worker.py:731
if 'python_code' in plan and plan['python_code']:
    df_processed = execute_ai_transformation(df, plan['python_code'])
```

and then:

```python
# celery_worker.py:704
local_scope = {"df": local_df, "pd": pd, "np": np}
exec(code_str, {}, local_scope)
```

`exec(code, {}, scope)` is **not a sandbox**. Verified on this machine's own venv — this escapes and executes a shell command:

```python
exec('[c for c in ().__class__.__mro__[1].__subclasses__() '
     'if c.__name__=="BuiltinImporter"][0].load_module("os").system("echo RCE_CONFIRMED")', {}, {})
# → RCE_CONFIRMED
```

An unauthenticated attacker gets arbitrary code execution as the service account. Confirmed this endpoint is reachable (it is registered *before* the static mount — see P0-4).

Two exploitation paths, not one:
- **Direct:** post `{"plans": {"conservative_plan": {"python_code": "<payload>"}}, ...}`.
- **Indirect (prompt injection):** `get_treatment_plan_hypotheses` embeds dataset-derived values (`top_values`, column names) into the LLM prompt. A malicious CSV can instruct the model to emit `python_code`, which is then `exec`'d. No user interaction required.

**Remediation:**
1. **Delete `execute_ai_transformation` entirely.** It is a legacy path. The Phase 3 deterministic registry (`FUNCTION_REGISTRY`) already covers every cleaning operation — nothing needs `exec`.
2. In `_validate_plan_robust`, drop the `python_code` branch and always use `_apply_actions_to_df` (the full-registry applier that already exists at `celery_worker.py:1096`).
3. Replace `plans: Dict[str, Any]` with a strict Pydantic model so arbitrary keys are rejected at the boundary:
   ```python
   class PlanIn(BaseModel):
       model_config = ConfigDict(extra="forbid")
       steps: list[ActionIn] = []
   ```
4. Sanitize LLM prompt inputs (truncate `top_values`, strip control characters) and never trust model output for anything executable.
5. Even after removal: run workers as a non-root user with no network egress and a read-only filesystem, as defence in depth.

---

## P0-3. Production build fails — missing dependency

**Verified by running `npm run build`:**

```
[vite]: Rollup failed to resolve import "lucide-react" from
"C:/Users/Hp/Desktop/Project/src/pages/DashboardPage.jsx".
✓ 22 modules transformed.
✗ Build failed in 356ms
```

`lucide-react` is imported in `DashboardPage.jsx` but is **absent from `package.json`**. It currently works in dev only because it was installed ad-hoc (or hoisted from another install). There is no deployable artifact.

**Remediation:**
```bash
npm install lucide-react
npm run build   # must pass
```
Then add a CI job that runs `npm ci && npm run build` on every PR so an undeclared dependency can never reach `main` again.

Also remove the bogus `"celery": "^0.0.0"` npm dependency in `package.json` — that is an unrelated, empty npm package (the real Celery is the Python one) and a supply-chain smell.

---

## P0-4. `StaticFiles` mount at `/` shadows 11 API routes → all return 404

**File:** `backend/main.py:425`

```python
app.mount("/", StaticFiles(directory=public_dir, html=True), name="public")
```

This mount sits **in the middle of the file**, not at the end. FastAPI/Starlette match routes in registration order, so the mount swallows every request that reaches it — including all endpoints registered *after* line 425.

**Verified** by loading the app and resolving paths through Starlette's own matcher:

| Method | Path | Resolved to | Result |
|---|---|---|---|
| POST | `/api/dataset/{n}/run-parallel-simulation` | `Mount` | ❌ 404 |
| GET  | `/simulation-status/{job_id}` | `Mount` | ❌ 404 |
| GET  | `/api/dataset/{n}/download-recipe` | `Mount` | ❌ 404 |
| GET  | `/api/dataset/{n}/effectiveness` | `Mount` | ❌ 404 |
| GET  | `/api/dataset/{n}/checkpoints` | `Mount` | ❌ 404 |
| POST | `/api/dataset/{n}/checkpoints/{id}/restore` | `Mount` | ❌ 404 |
| GET  | `/api/dataset/{n}/export` | `Mount` | ❌ 404 |
| GET  | `/api/dataset/{n}/statistics` | `APIRoute` | ✅ OK |

The frontend actively calls all seven dead endpoints (`DataTablePage.jsx:408, 431, 495, 557, 626, 649`; `PostCommitScreen.jsx:161`). So: **simulation, effectiveness scoring, recipe generation, export, and rollback are all non-functional**, and the UI just never gets data.

**Remediation — move the mount to the very end of the file:**
```python
# ... all @app.get/@app.post routes above ...

# MUST be last: catch-all for SPA + dataset files
app.mount("/", StaticFiles(directory=public_dir, html=True), name="public")
```
Then add a regression test that asserts every path in `app.openapi()["paths"]` resolves to an `APIRoute` and not the mount. This bug is invisible in code review and recurs easily.

---

## P0-5. Duplicate `apply-plan` route — Phase 5 metadata silently discarded

**Files:** `backend/main.py:122` and `backend/main.py:432`

Two handlers are registered for the identical path. **Verified:** the first (`apply_plan`, registered at route index 6) always wins; `apply_dataset_plan` (index 21) is unreachable.

The winner only forwards three of five fields:
```python
# main.py:134 — ml_improvement_score and target_variable are NEVER passed
task = apply_ai_plan_task.delay(
    dataset_name=dataset_name,
    action_backlog=request.action_backlog,
    note=request.plan_name
)
```

The frontend *does* send them (`DataTablePage.jsx:501-502`). They are dropped on the floor. Downstream in `apply_ai_plan_task`, both fall back to defaults (`ml_improvement_score=0.5`, `target_variable=None`), which means:

- The **40%-weighted ML component of the effectiveness score is always the hardcoded constant `0.5`** — the headline "delta improvement" number is fabricated, not measured.
- `target_variable=None` → `_leakage_post = []` → **leakage score is always `1.0`** (perfect). The leakage check never runs post-clean.

So even after fixing P0-4, the effectiveness score would still be wrong in two of its four components.

**Remediation:** delete the first handler entirely; keep the Phase 5 one at line 432 and rename it `apply_plan`. Verify with a test that two handlers never share a path:
```python
paths = [r.path for r in app.routes if isinstance(r, APIRoute)]
assert len(paths) == len(set(paths)), "duplicate route registration"
```

---

# 🟠 P1 — High Severity

### P1-1. Path traversal on upload and on every `{dataset_name}` parameter
`main.py:146` writes to `os.path.join(public_dir, file.filename)` using the raw client-supplied filename — `../../` escapes `public/`. Only `delete_dataset` (line 161) has any check, and it only tests `".."` and `"/"`, missing Windows `\` and URL-encoded `%2e%2e`. Every other endpoint (`statistics`, `diagnostics`, `export`, `checkpoints`, `apply-plan`) does **no** validation.
**Fix:** one shared resolver used everywhere:
```python
def resolve_dataset(name: str) -> Path:
    p = (PUBLIC_DIR / name).resolve()
    if not str(p).startswith(str(PUBLIC_DIR.resolve()) + os.sep):
        raise HTTPException(400, "Invalid dataset name.")
    if not p.is_file():
        raise HTTPException(404, "Dataset not found.")
    return p
```
Also sanitize upload filenames (`werkzeug.utils.secure_filename`) and enforce the versioning logic that already exists in `get_next_version_path`.

### P1-2. No authentication or authorization anywhere
Every endpoint is world-readable/writable. Any anonymous caller can list, download, modify, or delete every dataset. Combined with P0-2 this is a full compromise.
**Fix:** add an auth dependency (JWT/OIDC) on all `/api/*` routes, plus per-dataset ownership (owner_id column + row-level checks). Add a rate limiter (`slowapi`) — the AI and simulation endpoints are expensive and currently freely hammerable.

### P1-3. All datasets and checkpoints are publicly downloadable
`public/` is mounted statically with `html=True`, and `public/checkpoints/` lives inside it. Any file — including pre-cleaning snapshots users may believe were superseded — is fetchable at `/checkpoints/{dataset}/{id}.csv`. There is also no `robots.txt` or `index` guard.
**Fix:** move data + checkpoints **out** of `public/` into a `DATA_DIR` outside the served root. Serve files only through the authenticated `/export` endpoint.

### P1-4. AG Grid Enterprise used without a licence
`main.jsx:9` registers `AllEnterpriseModule` from `ag-grid-enterprise`. AG Grid Enterprise is **commercial software**; without a licence key it logs licence errors, displays a watermark, and puts you in breach of the licence agreement. `README.md:26` incorrectly claims "AG Grid Community", suggesting this was accidental.
**Fix:** either buy a licence and set `licenseKey`, or drop to the community build (`ag-grid-community` only) and remove `ag-grid-enterprise` from `package.json`. **This is a legal question, not just a technical one — resolve it before launch.**

### P1-5. Dependencies unpinned and incomplete
`requirements.txt` has **zero version constraints** — `pip install -r` gives a different stack on every run, and `fastapi` latest already emits `FastAPIDeprecationWarning` for `regex=` (P2-6). `scipy` is imported directly in two modules but only present transitively via `statsmodels`. `openpyxl` is **not installed** (verified) — so `?format=xlsx` export would fail even once P0-4 is fixed.
**Fix:** pin with `pip-compile` (add hashes for prod), add `scipy`, `openpyxl`, `httpx` (tests). Add `pytest` + `pytest-cov`. Remove `"celery"` from `package.json`.

### P1-6. Zero automated tests; no CI
No `pytest`, no `vitest`, no test files, no CI config. Nothing in this report would have been caught.
**Fix:** build out, in priority order:
1. Route-table test (catches P0-4 and P0-5 regressions directly).
2. `execution_engine` unit tests — every function in `FUNCTION_REGISTRY` × valid/invalid type, empty df, all-NaN column. This is the highest-risk logic and is pure, so it is cheap to test.
3. `_compute_effectiveness_score` — assert known inputs produce expected components.
4. Path-traversal tests for `resolve_dataset`.
5. API smoke tests with `TestClient` (needs `httpx`).
Then a GitHub Actions workflow: `npm ci && npm run lint && npm run build`, `pytest`, `gitleaks`.

### P1-7. `KEYS` used in a hot path; unbounded cache growth
`main.py:202` and `main.py:213` call `redis_cache.keys("profile:v1:*")`. `KEYS` is O(N) and **blocks the entire Redis instance** — forbidden in production. It runs on every dashboard load.
Also `audit:{dataset}` is `RPUSH`+`LTRIM` with **no TTL** (`execution_engine.py:955-957`), so audit logs grow forever.
**Fix:** `SCAN` with `MATCH`, or better, maintain a Redis `SET` of active profile names. Add `EXPIRE` on audit keys (e.g. 30 days). Set `maxmemory-policy allkeys-lru` on Redis.

### P1-8. Frontend polling: intervals leak on unmount and never time out
`DataTablePage.jsx:680-682` cleans up only `metricsPollingRef` and `insightsPollingRef`. **Four** refs — `diagnosticPollingRef`, `plansPollingRef`, `parallelSimPollingRef`, `afterProfilePollRef` — are never cleared. `setInterval` at line 512/571 has no attempt cap, so a permanently-`PENDING` job polls forever and leaks.
**Fix:** one cleanup effect clearing all six refs; add `attempts >= MAX` and wall-clock timeouts that surface an error toast instead of hanging.

### P1-9. Deadlock: `result.get()` called inside a Celery task
`celery_worker.py:390-391`:
```python
result = profile_dataset.delay(file_path)
return result.get()   # ← synchronous wait inside a task
```
Calling `.get()` inside a task risks a worker deadlock/timeout. This whole function is marked DEPRECATED and is still wired to the reachable endpoint `POST /api/statistics/{dataset_name}` (`main.py:387`).
**Fix:** delete `generate_comprehensive_stats` and point the endpoint at `profile_dataset` + the shared polling mechanism.

### P1-10. Silent data loss during ingest
`profile_dataset` reads with `on_bad_lines='skip'` — malformed rows are **silently discarded** and `row_count` reflects the truncated frame. For a *data quality* product, silently dropping rows is the worst possible default; the profile then reports a clean bill of health for a file that failed to parse.
**Fix:** parse with `on_bad_lines='error'` (or count skips), surface `rows_skipped` / `parse_warnings` in the profile, and show a banner in the UI. Log the file hash alongside the count.

### P1-11. Destructive actions requiring confirmation are silently dropped
`execution_engine.py:826-829` routes confirmation-required actions out of `approved_actions`, and `apply_ai_plan_task:954-956` only `print()`s a warning. They are never applied and **the user is never told**. A user who selects 10 actions may get 6 applied with no indication.
**Fix:** return `confirmation_required_actions` to the client, render a confirmation modal, and have the client re-submit with an explicit `confirmed_action_ids` list.

### P1-12. Frontend loads entire dataset into browser memory
`DataTablePage.jsx:104-109` fetches the whole CSV and `Papa.parse`s it into JS objects. `public/kith_sales.csv` is **26 MB** (~250k rows); parsing that into objects is several hundred MB of heap — browser tab crash. AG Grid's row virtualization does not help because the data is already fully materialized in JS first.
**Fix:** server-side pagination / windowed fetch (`GET /api/dataset/{n}/rows?offset=&limit=`), or AG Grid's server-side row model. Enforce a row cap for in-browser mode with a clear message.

### P1-13. Worker configuration is hardcoded
`celery_worker.py:53-54` hardcodes `redis://localhost:6379/0` and `Redis(host='localhost', port=6379, db=1)`, while `main.py:28-31` correctly reads env vars. In any deployed environment the web tier and worker tier will point at different Redis instances. Also `broker` and `backend` share db 0, and `time_limit=1800` (30 min) with no `soft_time_limit`.
**Fix:** single shared `config.py` reading env for both; separate broker/result DBs; set `soft_time_limit` so tasks can clean up; add `task_acks_late=True` + `worker_prefetch_multiplier=1`.

### P1-14. Unbounded upload with no server-side validation
`main.py:143` accepts any file of any size. `UploadFile` buffers to disk, so a large POST fills the volume. No extension/content-type check, no magic-byte sniff, no row/column caps.
**Fix:** enforce `MAX_UPLOAD_MB` via streaming with an abort on overflow, validate `.csv` by content, cap columns/rows, and reject empty or header-only files.

### P1-15. `.gitignore` does not ignore `node_modules` or data files
Verified: `git status` shows `?? node_modules/` (8,638 files) and every `public/*.csv` (incl. the 26 MB `kith_sales.csv`) and `public/checkpoints/` as untracked. A `git add .` commits the entire dependency tree and all user data. The file also contains stray ```` ``` ```` fence lines (harmless but wrong).
**Fix:**
```gitignore
node_modules/
public/*.csv
public/checkpoints/
dist/
.env
.env.*
```
and `git rm -r --cached public/checkpoints` if already tracked.

---

# 🟡 P2 — Medium

| # | Finding | Location | Fix |
|---|---|---|---|
| 2-1 | Dashboard reports hardcoded zeros: `"missing": 0`, `"inconsistencies": 0`. Quality metrics are fabricated. | `main.py:235,237` | Compute from profile; delete the fields if not implemented. |
| 2-2 | `mode` hardcoded to `"N/A"` in statistics payload. | `main.py:320` | Compute, or drop the field so the UI can hide it. |
| 2-3 | `Query(regex=...)` deprecated — emits `FastAPIDeprecationWarning` on import today, will break on upgrade. | `main.py:672` | Use `pattern=`. |
| 2-4 | `inplace=True` on a column slice (`df[col].fillna(..., inplace=True)`) — breaks under pandas 3 copy-on-write; `df.replace(..., inplace=True)` likewise. | `celery_worker.py:642,744` | Assign back: `df[col] = df[col].fillna(v)`. |
| 2-5 | Bare `except:` swallows everything incl. `KeyboardInterrupt`; mutates the caller's DataFrame via `df[target] = pd.to_numeric(...)`. | `celery_worker.py:813` | `except (ValueError, TypeError):` and operate on a copy. |
| 2-6 | No structured logging — ~30 `print()` calls; no request IDs; no correlation between API call and Celery job. | all modules | `logging` + JSON formatter; propagate a `request_id` into task payloads. |
| 2-7 | Raw exception text returned to clients (`detail=str(e)`, `detail=f"Could not save file: {e}"`) leaks paths/internals. | `main.py:87,120,156,183` | Log the exception, return a generic message + correlation ID. |
| 2-8 | CORS hardcoded to `http://localhost:5173` with no env override — production origin unset. | `main.py:35` | `settings.CORS_ORIGINS` from env; never `*`. |
| 2-9 | Skew-reduction normalizes by `max(max_before_skew, 2.0)` and defaults to `0.5` when no numeric columns — an arbitrary constant that dominates 20% of the score. | `celery_worker.py:1295,1298` | Document the choice; exclude the component (renormalize weights) rather than assume neutral. |
| 2-10 | `ml_improvement_score = raw_delta + 0.5` conflates relative-delta with an absolute score; a 50% drop and 200% gain both clamp to 0/1 differently depending on baseline magnitude. | `celery_worker.py:1508` | Map through a documented monotone function (e.g. logistic) and unit-test the boundaries. |
| 2-11 | Quality score `100 - missing% - duplicate%` ignores outliers, skew, type errors, and constant columns — a single metric drives the RAW/CLEANING/CLEANED status. | `celery_worker.py:99` | Either expand the formula or label it honestly as "completeness score". |
| 2-12 | No health/readiness endpoints (`/healthz`, `/readyz`) checking Redis + worker liveness — orchestrators cannot healthcheck this. | `main.py` | Add both; `/readyz` verifies broker connectivity. |
| 2-13 | `Procfile` runs `gunicorn -w 4` with no `--timeout`, no `--preload` guidance, and no `release:` phase for migrations; no `runtime.txt` pinning Python. | `backend/Procfile` | Pin runtime, set `--timeout`, add `/healthz` wiring. |
| 2-14 | No containerization or `docker-compose`, yet the stack needs Redis + API + worker. Local prod-parity setup is undocumented and the README assumes Windows `.venv\Scripts\`. | repo root | Add `Dockerfile`, `docker-compose.yml`, `.env.example`. |

---

# 🔵 P3 — Hygiene / Backlog

| # | Finding | Fix |
|---|---|---|
| 3-1 | **README is inaccurate:** says React 18 (actually 19), AG Grid Community (actually Enterprise — see P1-4), and omits setup steps, env vars, and architecture that no longer matches. | Rewrite: accurate stack, quickstart, env var table, API reference. |
| 3-2 | `package.json` has `name: "project"`, `version: "0.0.0"`. | Set `name: "datacraft-studio"`, real semver. |
| 3-3 | ESLint: **15 errors, 4 warnings**, incl. unused vars and empty catch blocks (`DataTablePage.jsx:605`). The `lint` script uses the removed `--ext` flag. | Fix errors; drop `--ext`; gate CI on `--max-warnings 0`. |
| 3-4 | Substantial dead code: `generate_comprehensive_stats`, `generate_diagnostic_report`, `execute_ai_transformation`, `_apply_plan_steps`, `get_temporal_profile`, `get_statistical_profile`, `perform_*`, `route_task`, `src/data/salesData.js`. | Delete; confirmed no live callers after P0-2/P1-9 fixes. |
| 3-5 | `graphify-out/` (124 files) and `dist/` are committed build artifacts. | Remove and gitignore. |
| 3-6 | `architecture_map.txt` is stale (missing checkpoint_manager, execution_engine, 5 new components) and duplicates README. | Delete or generate automatically. |
| 3-7 | `import json` at the bottom of `execution_engine.py:1016` — works only by accident of module import order. | Move to top. |
| 3-8 | `UploadPage.jsx:47,54` calls `addDataset` twice with different shapes. | Remove the duplicate call. |

---

## Suggested Remediation Order

**Day 1 (contain):** Revoke the API key (P0-1) → delete `exec` (P0-2) → add `lucide-react` (P0-3).
**Day 2 (restore function):** Move the static mount to the end (P0-4) → dedupe `apply-plan` (P0-5) → add the route-table regression test that pins both.
**Week 1 (hardening):** Path traversal (P1-1), auth (P1-2), move data out of `public/` (P1-3), resolve the AG Grid licence question (P1-4), pin deps (P1-5).
**Week 2 (correctness + confidence):** Test suite + CI (P1-6), Redis `KEYS`→`SCAN` (P1-7), polling cleanup (P1-8), task deadlock (P1-9), ingest data-loss surfacing (P1-10), confirmation flow (P1-11).
**Before launch:** P1-12…P1-15, then work down P2.

The two route-registration bugs (P0-4, P0-5) are the highest-leverage fixes — together they restore the product's entire reason for existing. Both are invisible to code review, which is exactly why the route-table test should land in the same commit as the fixes.
