import logging
import os
import glob
import json
import io
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, HTTPException, UploadFile, File, Query, Request
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from fastapi.staticfiles import StaticFiles
from celery.result import AsyncResult
from fastapi.middleware.cors import CORSMiddleware
from redis import Redis

import config
from security import resolve_dataset, sanitize_filename, RateLimiter
from csvio import read_csv_strict
from checkpoint_manager import (
    create_checkpoint, list_checkpoints, restore_checkpoint,
    delete_checkpoint, delete_all_checkpoints, get_pool_size_mb
)
from celery_worker import (
    celery_app as worker, profile_dataset,
    generate_treatment_plans_task,
    run_impact_simulation_task, apply_ai_plan_task,
    run_parallel_simulation_task, generate_cleaning_recipe_task
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("datacraft.api")

redis_cache: Redis = Redis(
    host=config.REDIS_HOST, port=config.REDIS_PORT, db=config.REDIS_DB_CACHE,
    decode_responses=True,
)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- P1-2: bearer auth + rate limiting on the API surface -------------------
# Auth is active only when API_AUTH_TOKEN is configured; rate limiting always
# applies to expensive POST endpoints (AI calls, simulations, uploads).
AUTH_PREFIXES = ("/api/", "/simulation-status")
EXPENSIVE_POST_SUFFIXES = (
    "/run-simulation", "/run-parallel-simulation", "/generate-plans",
    "/apply-plan", "/upload",
)
limiter = RateLimiter(config.RATE_LIMIT_PER_MINUTE)


def _bearer_ok(request: Request) -> bool:
    return request.headers.get("authorization", "") == f"Bearer {config.API_AUTH_TOKEN}"


@app.middleware("http")
async def api_guard_middleware(request: Request, call_next):
    path = request.url.path
    if config.API_AUTH_TOKEN and path.startswith(AUTH_PREFIXES) and not path.startswith("/api/health"):
        if not _bearer_ok(request):
            return JSONResponse(status_code=401, content={"detail": "Unauthorized."})
    if request.method == "POST" and path.endswith(EXPENSIVE_POST_SUFFIXES):
        try:
            limiter.check(request)
        except HTTPException as e:
            return JSONResponse(status_code=e.status_code, content={"detail": e.detail})
    return await call_next(request)


class GeneratePlansRequest(BaseModel):
    target_variable: str
    goal: str
    temporal_column: Optional[str] = None  # Bug 4 Fix: Add temporal column selector

class ApplyPlanRequest(BaseModel):
    action_backlog: list          # Phase 3: PDIA action backlog
    plan_name: str
    ml_improvement_score: Optional[float] = None  # Phase 5: from parallel simulation
    target_variable: Optional[str] = None          # Phase 5: for effectiveness score

class RunParallelSimulationRequest(BaseModel):
    action_backlog: list   # Full PDIA backlog; backend derives risk-level subsets
    target_variable: str
    goal: str              # 'classification' | 'regression'

class CleanRequest(BaseModel):
    dataset_name: str
    action_type: str

class TaskRequest(BaseModel):
    dataset_name: str
    column_name: str
    task_type: str
    task_params: Optional[Dict[str, Any]] = None

class SimulationStep(BaseModel):
    """
    One atomic cleaning action, validated at the HTTP boundary.

    `extra="forbid"` is the security control here: it makes it impossible for a
    caller to smuggle a `python_code` (or any other) key through to the worker.
    Only registry-safe fields survive serialization.
    """
    model_config = ConfigDict(extra="forbid")

    function_name: str
    target_columns: List[str] = Field(default_factory=list)
    params: Dict[str, Any] = Field(default_factory=dict)


class SimulationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = "plan"
    rationale: str = ""
    steps: List[SimulationStep] = Field(default_factory=list)


class RunSimulationRequest(BaseModel):
    target_variable: str
    goal: str
    plans: Dict[str, SimulationPlan] = Field(default_factory=dict)


def _scan_keys(pattern: str) -> List[str]:
    """SCAN-based key listing. KEYS blocks a production Redis (P1-7)."""
    keys: List[str] = []
    cursor = 0
    while True:
        cursor, batch = redis_cache.scan(cursor=cursor, match=pattern, count=200)
        keys.extend(batch)
        if cursor == 0:
            break
    return keys


def _profile_error(detail: str) -> HTTPException:
    return HTTPException(status_code=500, detail=detail)


@app.get("/healthz")
@app.get("/api/health/live")
async def healthz():
    """Liveness: process is up."""
    return {"status": "ok"}


@app.get("/readyz")
@app.get("/api/health/ready")
async def readyz():
    """Readiness: Redis reachable. Orchestrators poll this, not /healthz."""
    try:
        redis_cache.ping()
        return {"status": "ok"}
    except Exception:
        logger.exception("Readiness check failed: Redis unreachable")
        return JSONResponse(status_code=503, content={"status": "redis unavailable"})


@app.post("/api/dataset/{dataset_name}/run-simulation")
async def run_simulation(dataset_name: str, request: RunSimulationRequest):
    try:
        resolve_dataset(dataset_name)
        task = run_impact_simulation_task.delay(
            dataset_name=dataset_name,
            # Serialize through the validated model: only known, typed fields reach
            # the worker. Anything the client invented is dropped here.
            plans={name: plan.model_dump() for name, plan in request.plans.items()},
            target_variable=request.target_variable,
            goal=request.goal
        )
        return {"job_id": task.id, "status": "Impact simulation job started."}
    except HTTPException:
        raise
    except Exception:
        logger.exception("run-simulation failed for %s", dataset_name)
        raise _profile_error("Could not start impact simulation.")


def get_next_version_path(file_path: str) -> str:
    if not os.path.exists(file_path):
        return file_path
    base, ext = os.path.splitext(file_path)
    version = 1
    while True:
        new_path = f"{base} ({version}){ext}"
        if not os.path.exists(new_path):
            return new_path
        version += 1

@app.post("/api/dataset/{dataset_name}/generate-plans")
async def generate_plans(dataset_name: str, request: GeneratePlansRequest):
    """
    Endpoint to kick off the AI-powered treatment plan generation task.
    Bug 4 Fix: Pass temporal_column through to the task.
    """
    try:
        # Verify file exists before dispatching a potentially long-running task
        resolve_dataset(dataset_name)

        task = generate_treatment_plans_task.delay(
            dataset_name=dataset_name,
            target_variable=request.target_variable,
            goal=request.goal,
            temporal_column=request.temporal_column  # Bug 4 Fix: Pass temporal_column
        )
        return {"job_id": task.id, "status": "Treatment plan generation job started."}
    except HTTPException:
        raise
    except Exception:
        logger.exception("generate-plans failed for %s", dataset_name)
        raise _profile_error("Could not start plan generation.")


@app.post("/api/upload")
async def upload_dataset(file: UploadFile = File(...)):
    # P1-14: streaming size cap, name + content validation, no silent buffering.
    name = sanitize_filename(file.filename)
    dest = get_next_version_path(os.path.join(config.PUBLIC_DIR, name))
    max_bytes = config.MAX_UPLOAD_MB * 1024 * 1024

    try:
        written = 0
        with open(dest, "wb") as buffer:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    buffer.close()
                    os.remove(dest)
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds the {config.MAX_UPLOAD_MB} MB upload limit."
                    )
                buffer.write(chunk)

        if written == 0:
            os.remove(dest)
            raise HTTPException(status_code=400, detail="Empty file.")

        # Cheap content probe: must parse as CSV and have data rows.
        import pandas as pd
        try:
            probe = pd.read_csv(dest, nrows=5)
        except Exception:
            os.remove(dest)
            raise HTTPException(status_code=400, detail="File is not a valid CSV.")
        if len(probe) == 0 or probe.columns.empty:
            os.remove(dest)
            raise HTTPException(status_code=400, detail="File has no data rows (header-only?).")
        if len(probe.columns) > config.MAX_UPLOAD_COLUMNS:
            os.remove(dest)
            raise HTTPException(
                status_code=400,
                detail=f"File has {len(probe.columns)} columns; limit is {config.MAX_UPLOAD_COLUMNS}."
            )

        # Dispatch single unified profile task
        profile_dataset.delay(dest)

        return {"status": "SUCCESS", "message": "File uploaded", "path": f"/{os.path.basename(dest)}", "name": os.path.basename(dest)}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Upload failed")
        raise HTTPException(status_code=500, detail="Could not save file.")

@app.delete("/api/dataset/{dataset_name}")
async def delete_dataset(dataset_name: str):
    try:
        file_path = resolve_dataset(dataset_name)

        cache_keys_to_delete = [
            f"profile:v1:{dataset_name}",
            f"statistics:{dataset_name}",
            f"diagnostics:{dataset_name}",
            f"effectiveness:{dataset_name}",
            f"recipe:{dataset_name}",
        ]

        os.remove(file_path)
        delete_all_checkpoints(dataset_name)
        redis_cache.delete(*cache_keys_to_delete)

        return {"message": f"Successfully ensured dataset '{dataset_name}' is deleted."}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Delete failed for %s", dataset_name)
        raise HTTPException(status_code=500, detail="A server error occurred while deleting the dataset.")

@app.get("/api/datasets")
async def get_available_datasets():
    try:
        csv_files = glob.glob(os.path.join(config.PUBLIC_DIR, "*.csv"))
        datasets = []
        for file_path in csv_files:
            file_name = os.path.basename(file_path)
            datasets.append({
                "name": file_name,
                "path": f"/{file_name}",
                "source": "server",
                "size_bytes": os.path.getsize(file_path),
            })
        return datasets
    except Exception:
        logger.exception("Listing datasets failed")
        raise HTTPException(status_code=500, detail="Failed to list datasets.")

@app.get("/api/datasets/dashboard-summary")
async def get_dashboard_summary():
    try:
        disk_files = {os.path.basename(p) for p in glob.glob(os.path.join(config.PUBLIC_DIR, "*.csv"))}
        cached_files = {k.split(':', 2)[2] for k in _scan_keys("profile:v1:*")}
        files_to_process = disk_files - cached_files
        for filename in files_to_process:
            profile_dataset.delay(os.path.join(config.PUBLIC_DIR, filename))

        files_to_remove = cached_files - disk_files
        if files_to_remove:
            keys_to_delete = [f"profile:v1:{fname}" for fname in files_to_remove]
            redis_cache.delete(*keys_to_delete)

        profile_keys = _scan_keys("profile:v1:*")
        if not profile_keys: return []

        all_profiles_raw = redis_cache.mget(profile_keys)
        all_profiles = [json.loads(s) for s in all_profiles_raw if s]

        summaries = []
        for profile in all_profiles:
            ds_name = profile["dataset_name"]
            eff_str = redis_cache.get(f"effectiveness:{ds_name}")
            eff_data = json.loads(eff_str) if eff_str else None

            # P2-1: real quality metrics instead of hardcoded zeros
            columns_profile = profile.get("columns", {})
            missing_cells = sum(int(c.get("missing_count", 0)) for c in columns_profile.values())
            total_cells = max(profile["row_count"] * profile["column_count"], 1)
            missing_pct = round(missing_cells / total_cells * 100, 2)
            outlier_cells = sum(int(c.get("outlier_count") or 0) for c in columns_profile.values())

            summaries.append({
                "id":             ds_name,
                "filename":       ds_name,
                "size":           f"{profile['row_count']} rows",
                "rows":           profile["row_count"],
                "columns":        profile["column_count"],
                "status":         "CLEANED" if profile["quality_score"] > 90 else "CLEANING" if profile["quality_score"] > 60 else "RAW",
                "qualityScore":   profile["quality_score"],
                "cleaning_effectiveness": eff_data["cleaning_effectiveness"] if eff_data else None,
                "effectiveness_components": eff_data if eff_data else None,
                "missing":        missing_pct,
                "duplicates":     (profile["duplicate_row_count"] / profile["row_count"] * 100) if profile["row_count"] > 0 else 0,
                "inconsistencies": outlier_cells,
                "rowsSkipped":    profile.get("rows_skipped", 0),
                "lastModified":   profile["created_at"][:10]
            })
        return summaries
    except Exception:
        logger.exception("Dashboard summary failed")
        raise HTTPException(status_code=500, detail="Failed to retrieve summaries.")

@app.get("/api/dataset/{dataset_name}/diagnostics")
async def get_dataset_diagnostics(dataset_name: str):
    resolve_dataset(dataset_name)
    cache_key = f"profile:v1:{dataset_name}"
    cached_result = redis_cache.get(cache_key)
    if cached_result:
        profile_data = json.loads(cached_result)
        return {
            "filename": dataset_name,
            "dataset_summary": {
                "row_count": profile_data["row_count"],
                "column_count": profile_data["column_count"],
                "duplicate_row_count": profile_data["duplicate_row_count"]
            },
            "column_diagnostics": [
                {
                    "column_name": col_name,
                    "data_type": col_data["data_type"],
                    "missing_count": col_data["missing_count"],
                    "missing_percentage": col_data["missing_pct"],
                    "constant_flag": col_data["unique_count"] == 1 if col_data["unique_count"] else False
                }
                for col_name, col_data in profile_data["columns"].items()
            ]
        }
    else:
        file_path = os.path.join(config.PUBLIC_DIR, dataset_name)
        profile_dataset.delay(file_path)
        raise HTTPException(status_code=202, detail="Profile generation is in progress.")

@app.get("/api/dataset/{dataset_name}/column-profile/{column_name}")
async def get_column_profile(dataset_name: str, column_name: str):
    """Returns the full Redis column profile (with histogram_bins) for preview modal."""
    resolve_dataset(dataset_name)
    cache_key = f"profile:v1:{dataset_name}"
    cached_result = redis_cache.get(cache_key)
    if not cached_result:
        raise HTTPException(status_code=404, detail="Profile not found. Run profiling first.")
    profile_data = json.loads(cached_result)
    col_data = profile_data.get("columns", {}).get(column_name)
    if col_data is None:
        raise HTTPException(status_code=404, detail=f"Column '{column_name}' not found in profile.")
    return col_data

@app.get("/api/dataset/{dataset_name}/statistics")
async def get_dataset_statistics(dataset_name: str):
    resolve_dataset(dataset_name)
    cache_key = f"profile:v1:{dataset_name}"
    cached_result = redis_cache.get(cache_key)
    if cached_result:
        profile_data = json.loads(cached_result)
        column_stats = []
        numeric_column_count = 0
        text_column_count = 0

        for col_name, col_data in profile_data["columns"].items():
            data_type = col_data["data_type"]
            if data_type in ['integer', 'float', 'identifier']:
                numeric_column_count += 1
            else:
                text_column_count += 1

            stat = {
                "column": col_name,
                "dataType": data_type,
                "nullCount": col_data["missing_count"],
                "nullPercentage": col_data["missing_pct"],
                "uniqueValues": col_data["unique_count"],
                "totalValues": profile_data["row_count"] - col_data["missing_count"],
                "mean": col_data.get("mean", "N/A"),
                "median": col_data.get("median", "N/A"),
                "mode": col_data.get("mode", "N/A")
            }
            column_stats.append(stat)

        eff_str = redis_cache.get(f"effectiveness:{dataset_name}")
        eff_data = json.loads(eff_str) if eff_str else None

        return {
            "filename":    dataset_name,
            "lastModified": profile_data["created_at"][:10],
            "size":        f"{profile_data['row_count']} rows",
            "rows":        profile_data["row_count"],
            "columns":     profile_data["column_count"],
            "totalCells":  profile_data["row_count"] * profile_data["column_count"],
            "status":      "CLEANED" if profile_data["quality_score"] > 90 else "CLEANING" if profile_data["quality_score"] > 60 else "RAW",
            "qualityScore":  profile_data["quality_score"],
            "cleaning_effectiveness": eff_data["cleaning_effectiveness"] if eff_data else None,
            "effectiveness_components": eff_data if eff_data else None,
            "missing_pct": sum(c["missing_count"] for c in profile_data["columns"].values()) / (profile_data["row_count"] * profile_data["column_count"]) * 100 if profile_data["row_count"] > 0 else 0,
            "duplicates_pct": (profile_data["duplicate_row_count"] / profile_data["row_count"] * 100) if profile_data["row_count"] > 0 else 0,
            "overallNullCount": sum(c["missing_count"] for c in profile_data["columns"].values()),
            "rowsSkipped": profile_data.get("rows_skipped", 0),
            "parseWarnings": profile_data.get("parse_warnings", []),
            "columnStats": column_stats,
            "numericColumnCount": numeric_column_count,
            "textColumnCount": text_column_count
        }
    else:
        file_path = os.path.join(config.PUBLIC_DIR, dataset_name)
        profile_dataset.delay(file_path)
        raise HTTPException(status_code=202, detail="Profile generation is in progress.")

@app.get("/api/dataset/{dataset_name}/rows")
async def get_dataset_rows(dataset_name: str, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000)):
    """
    P1-12: server-side pagination. Large CSVs must not be materialized in the
    browser; the frontend fetches fixed-size windows through this endpoint.
    """
    import pandas as pd
    file_path = resolve_dataset(dataset_name)

    total_rows: Optional[int] = None
    profile_str = redis_cache.get(f"profile:v1:{dataset_name}")
    if profile_str:
        total_rows = int(json.loads(profile_str)["row_count"])

    if total_rows is None:
        # Heuristic line count; quoted newlines make this approximate only when
        # no profile exists yet, which is a transient state.
        with open(file_path, "rb") as f:
            total_rows = max(sum(1 for _ in f) - 1, 0)

    if offset >= total_rows:
        return {"rows": [], "total": total_rows, "offset": offset, "limit": limit}

    df = pd.read_csv(
        file_path,
        skiprows=range(1, offset + 1),
        nrows=limit,
        low_memory=False,
    )
    records = df.astype(object).where(pd.notnull(df), None).to_dict(orient="records")
    return {"rows": records, "total": total_rows, "offset": offset, "limit": limit}

@app.post("/api/dataset/{dataset_name}/refresh-statistics")
async def refresh_dataset_statistics(dataset_name: str):
    file_path = resolve_dataset(dataset_name)

    redis_cache.delete(f"profile:v1:{dataset_name}")
    redis_cache.delete(f"statistics:{dataset_name}")
    redis_cache.delete(f"diagnostics:{dataset_name}")
    profile_dataset.delay(file_path)
    return {"message": "Profile refresh initiated."}



@app.post("/api/submit_task")
async def submit_task(request: TaskRequest):
    resolve_dataset(request.dataset_name)
    task = worker.send_task(
        'celery_worker.route_task',
        args=[request.dataset_name, request.column_name, request.task_type, request.task_params]
    )
    return {"job_id": task.id, "status": "Job accepted."}

@app.get("/api/analyze/status/{job_id}")
async def get_analysis_status(job_id: str):
    task_result = AsyncResult(job_id, app=worker)
    if task_result.ready():
        if task_result.successful():
            return task_result.get()
        else:
            return {"status": "FAILURE", "error": str(task_result.info)}
    else:
        return {"status": "PENDING"}

@app.get("/api/statistics/status/{job_id}")
async def get_statistics_status(job_id: str):
    task_result = AsyncResult(job_id, app=worker)
    if task_result.ready():
        if task_result.successful():
            return task_result.get()
        else:
            return {"status": "FAILURE", "error": str(task_result.info)}
    else:
        return {"status": "PENDING"}

@app.post("/api/statistics/{dataset_name}")
async def start_statistics_generation(dataset_name: str):
    """
    P1-9: dispatches the unified profile task directly. The old
    generate_comprehensive_stats wrapper called .get() inside a Celery task,
    which risks worker deadlock, and has been deleted.
    """
    try:
        file_path = resolve_dataset(dataset_name)
        task = profile_dataset.delay(file_path)
        return {"job_id": task.id, "status": "Statistics generation job started."}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Statistics dispatch failed for %s", dataset_name)
        raise _profile_error("Could not start statistics generation.")

@app.post("/api/dataset/clean")
async def clean_dataset(request: CleanRequest):
    try:
        file_path = resolve_dataset(request.dataset_name)

        task = worker.send_task(
            'celery_worker.perform_dataset_cleaning_task',
            args=[file_path, request.action_type]
        )

        return {"job_id": task.id, "message": f"Dataset cleaning job '{request.action_type}' started."}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Clean dispatch failed for %s", request.dataset_name)
        raise _profile_error("Could not start cleaning job.")



# =============================================================================
# PHASE 5: APPLY-PLAN — accept ml_improvement_score + target_variable
# =============================================================================

@app.post("/api/dataset/{dataset_name}/apply-plan")
async def apply_plan(dataset_name: str, request: ApplyPlanRequest):
    """Applies PDIA action backlog. Phase 5: accepts effectiveness metadata."""
    file_path = resolve_dataset(dataset_name)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Dataset not found.")

    task = apply_ai_plan_task.delay(
        dataset_name,
        request.action_backlog,
        request.plan_name,
        request.ml_improvement_score,
        request.target_variable
    )
    return {"job_id": task.id, "status": "Plan application started."}


# =============================================================================
# PHASE 5.1: PARALLEL SIMULATION — dispatch Celery group
# =============================================================================

@app.post("/api/dataset/{dataset_name}/run-parallel-simulation")
async def run_parallel_simulation(dataset_name: str, request: RunParallelSimulationRequest):
    """
    Phase 5: Dispatches 3 parallel validate_plan_task subtasks (conservative /
    balanced / aggressive) derived from the PDIA backlog risk_level field.
    Returns job_id for polling GET /simulation-status/{job_id}.
    """
    file_path = resolve_dataset(dataset_name)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Dataset not found.")

    if not request.action_backlog:
        raise HTTPException(status_code=400, detail="Action backlog is empty.")

    if not request.target_variable:
        raise HTTPException(status_code=400, detail="target_variable is required.")

    task = run_parallel_simulation_task.delay(
        dataset_name,
        request.action_backlog,
        request.target_variable,
        request.goal
    )
    return {"job_id": task.id, "status": "Parallel simulation dispatched."}


# =============================================================================
# PHASE 5.1: SIMULATION STATUS — per-plan streaming poll
# =============================================================================

@app.get("/simulation-status/{job_id}")
async def get_simulation_status(job_id: str):
    """
    Phase 5: Returns per-plan status as subtasks complete.
    Polls the parent task result first, then checks individual subtask IDs
    stored in Redis under sim_group:{job_id}.
    """
    parent_result = AsyncResult(job_id, app=worker)
    parent_state  = parent_result.state

    if parent_state in ('PENDING', 'STARTED', 'RETRY'):
        return {
            "status": "INITIALIZING",
            "plans": [],
            "message": "Computing baseline ML score and dispatching workers..."
        }

    if parent_state == 'FAILURE':
        return {
            "status": "FAILURE",
            "plans": [],
            "error": str(parent_result.info)
        }

    tracking_str = redis_cache.get(f"sim_group:{job_id}")
    if not tracking_str:
        return {
            "status": "INITIALIZING",
            "plans": [],
            "message": "Workers dispatched — waiting for first results..."
        }

    tracking = json.loads(tracking_str)

    plans      = []
    all_done   = True
    any_failed = False

    for i, subtask_id in enumerate(tracking.get("subtask_ids", [])):
        scenario = tracking["scenarios"][i] if i < len(tracking.get("scenarios", [])) else f"scenario_{i}"
        subtask  = AsyncResult(subtask_id, app=worker)

        if subtask.ready():
            if subtask.successful():
                result = subtask.get(disable_sync_subtasks=False)
                plans.append({"task_state": "SUCCESS", **result})
            else:
                any_failed = True
                plans.append({
                    "scenario_name": scenario,
                    "task_state":    "FAILURE",
                    "status":        "FAILURE",
                    "error":         str(subtask.info),
                    "effectiveness_score": 0.0
                })
        else:
            all_done = False
            plans.append({
                "scenario_name": scenario,
                "task_state":    subtask.state,  # PENDING | STARTED
                "status":        "PENDING"
            })

    completed   = sorted(
        [p for p in plans if p.get("task_state") == "SUCCESS"],
        key=lambda p: p.get("effectiveness_score", 0),
        reverse=True
    )
    pending_plans  = [p for p in plans if p.get("task_state") not in ("SUCCESS", "FAILURE")]
    failed_plans   = [p for p in plans if p.get("task_state") == "FAILURE"]
    ordered_plans  = completed + pending_plans + failed_plans

    overall_status = "COMPLETE" if all_done else ("FAILURE" if any_failed and all_done else "RUNNING")

    return {
        "status":           overall_status,
        "plans":            ordered_plans,
        "baseline_score":   tracking.get("baseline_score"),
        "baseline_metric":  tracking.get("baseline_metric", "Score"),
        "baseline_error":   tracking.get("baseline_error"),
        "leakage_warnings": tracking.get("leakage_warnings", []),
        "dispatched_at":    tracking.get("dispatched_at")
    }


# =============================================================================
# PHASE 5.3: DOWNLOAD CLEANING RECIPE
# =============================================================================

@app.get("/api/dataset/{dataset_name}/download-recipe")
async def download_cleaning_recipe(dataset_name: str):
    """
    Phase 5.3: Returns the cleaning recipe JSON generated after plan application.
    Stored in Redis under recipe:{dataset_name} for 24h.
    """
    resolve_dataset(dataset_name)
    recipe_str = redis_cache.get(f"recipe:{dataset_name}")
    if not recipe_str:
        raise HTTPException(
            status_code=404,
            detail="No cleaning recipe found. Apply a plan first, then the recipe "
                   "will be auto-generated and available here within seconds."
        )
    return json.loads(recipe_str)


# =============================================================================
# PHASE 5.2: EFFECTIVENESS SCORE — standalone fetch
# =============================================================================

@app.get("/api/dataset/{dataset_name}/effectiveness")
async def get_effectiveness_score(dataset_name: str):
    """
    Phase 5.2: Fetches the stored cleaning effectiveness metrics for a dataset.
    Available after a plan has been applied via apply-plan endpoint.
    """
    resolve_dataset(dataset_name)
    eff_str = redis_cache.get(f"effectiveness:{dataset_name}")
    if not eff_str:
        return {
            "available": False,
            "message": "No effectiveness score yet. Apply a cleaning plan to generate one."
        }
    data = json.loads(eff_str)
    return {"available": True, **data}


# =============================================================================
# CHECKPOINT / ROLLBACK ENDPOINTS
# =============================================================================

@app.get("/api/dataset/{dataset_name}/checkpoints")
async def get_checkpoints(dataset_name: str):
    """List all checkpoints for a dataset (newest first)."""
    resolve_dataset(dataset_name)
    checkpoints = list_checkpoints(dataset_name)
    pool_mb = get_pool_size_mb()
    return {"checkpoints": checkpoints, "pool_mb": round(pool_mb, 2), "pool_limit_mb": 500}


@app.post("/api/dataset/{dataset_name}/checkpoints")
async def create_checkpoint_endpoint(dataset_name: str):
    """Manually create a checkpoint of the current dataset state."""
    file_path = resolve_dataset(dataset_name)
    result = create_checkpoint(dataset_name, file_path, batch_label="Manual checkpoint")
    if result and result.get('error'):
        raise HTTPException(status_code=400, detail=result['error'])
    return result


@app.post("/api/dataset/{dataset_name}/checkpoints/{checkpoint_id}/restore")
async def restore_checkpoint_endpoint(dataset_name: str, checkpoint_id: str):
    """Restore dataset to a specific checkpoint."""
    file_path = resolve_dataset(dataset_name)
    result = restore_checkpoint(dataset_name, checkpoint_id, file_path)
    if not result.get('success'):
        raise HTTPException(status_code=404, detail=result.get('error', 'Restore failed.'))
    # Invalidate profile cache so UI re-profiles restored data
    redis_cache.delete(f"profile:v1:{dataset_name}")
    profile_dataset.delay(file_path)
    return {"message": f"Restored to checkpoint {checkpoint_id}. Re-profiling in background.", **result}


@app.delete("/api/dataset/{dataset_name}/checkpoints/{checkpoint_id}")
async def delete_checkpoint_endpoint(dataset_name: str, checkpoint_id: str):
    """Delete a single checkpoint to free pool space."""
    resolve_dataset(dataset_name)
    result = delete_checkpoint(dataset_name, checkpoint_id)
    if not result.get('success'):
        raise HTTPException(status_code=404, detail=result.get('error', 'Delete failed.'))
    return result


@app.delete("/api/dataset/{dataset_name}/checkpoints")
async def delete_all_checkpoints_endpoint(dataset_name: str):
    """Wipe all checkpoints for a dataset."""
    resolve_dataset(dataset_name)
    result = delete_all_checkpoints(dataset_name)
    return result


# =============================================================================
# EXPORT ENDPOINT
# =============================================================================

@app.get("/api/dataset/{dataset_name}/export")
async def export_dataset(dataset_name: str, format: str = Query(default='csv', pattern='^(csv|xlsx)$')):
    """Stream the cleaned dataset as CSV or Excel download."""
    import pandas as pd
    file_path = resolve_dataset(dataset_name)

    df, _rows_skipped = read_csv_strict(file_path, low_memory=False)
    base_name = dataset_name.replace('.csv', '')

    if format == 'xlsx':
        try:
            buffer = io.BytesIO()
            df.to_excel(buffer, index=False, engine='openpyxl')
            buffer.seek(0)
            return StreamingResponse(
                buffer,
                media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                headers={'Content-Disposition': f'attachment; filename="{base_name}_cleaned.xlsx"'}
            )
        except ImportError:
            raise HTTPException(status_code=400, detail="openpyxl not installed. Use format=csv instead.")
    else:
        csv_str = df.to_csv(index=False)
        return StreamingResponse(
            io.StringIO(csv_str),
            media_type='text/csv',
            headers={'Content-Disposition': f'attachment; filename="{base_name}_cleaned.csv"'}
        )




# =============================================================================
# STATIC FILES — MUST BE LAST
# =============================================================================
# Starlette matches routes in registration order. A Mount on "/" is a catch-all,
# so registering it before any API route makes that route permanently unreachable
# (every request resolves to the mount and 404s). It must stay at the very bottom
# of this file; `test_routes.py::test_no_api_route_is_shadowed` guards this.
app.mount("/", StaticFiles(directory=config.PUBLIC_DIR, html=True), name="public")
