import logging
from celery import Celery, group
import pandas as pd
import numpy as np
import os
import json
import hashlib
import uuid
from redis import Redis
from datetime import datetime, timezone

logger = logging.getLogger("datacraft.worker")
from scipy import stats
from statsmodels.tsa.stattools import acf
from sklearn.preprocessing import StandardScaler, MinMaxScaler
import config
from csvio import read_csv_strict
from ai_service import get_ai_interpretation, get_treatment_plan_hypotheses
from data_type_detector import detect_data_type
from execution_engine import (
    FUNCTION_REGISTRY,
    validate_plan,
    execute_transactionally,
    ExecutionReport
)

from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler, OneHotEncoder, LabelEncoder
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import roc_auc_score, mean_squared_error

import pandas as pd
import numpy as np

class NumpyJSONEncoder(json.JSONEncoder):
    """
    A comprehensive JSON encoder that handles all common NumPy and pandas data types.
    This prevents TypeError exceptions for types like numpy.int64, numpy.float64,
    pandas.Timestamp, etc.
    """
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, pd.Timestamp):
            return obj.isoformat() # Convert Timestamp to standard ISO string
        return super(NumpyJSONEncoder, self).default(obj)


# P1-13: env-driven via shared config — never hardcode broker endpoints here.
celery_app = Celery(
    'tasks',
    broker=config.REDIS_URL_BROKER,
    backend=config.REDIS_URL_RESULTS,
)
celery_app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=config.TASK_SOFT_TIME_LIMIT,
    broker_connection_retry_on_startup=True,
)
redis_cache = Redis(
    host=config.REDIS_HOST, port=config.REDIS_PORT, db=config.REDIS_DB_CACHE,
    decode_responses=True,
)

@celery_app.task(time_limit=1800)
def profile_dataset(file_path: str, target_variable: str = None):
    """
    Unified profiling task that replaces both generate_comprehensive_stats and generate_diagnostic_report.
    Produces a single canonical DataProfile object stored under profile:v1:{dataset_name}.

    Phase 1 Implementation:
    - Computes all fields in the unified DataProfile schema
    - Histogram bins with IQR capping for outlier-resistant visualization
    - Leakage risk score computation when target is known
    - MNAR correlations for missingness mechanism detection
    - Profile versioning with latest pointer and historical versions
    """
    try:
        file_name = os.path.basename(file_path)
        cache_key_latest = f"profile:v1:{file_name}"

        # Check for existing profile to detect schema drift
        existing_profile_str = redis_cache.get(cache_key_latest)
        existing_profile = json.loads(existing_profile_str) if existing_profile_str else None

        # Compute source hash for cache invalidation detection
        with open(file_path, 'rb') as f:
            source_hash = hashlib.md5(f.read()).hexdigest()

        common_na_values = ['', '#N/A', '#N/A N/A', '#NA', '-1.#IND', '-1.#QNAN', '-NaN', '-nan',
                            '1.#IND', '1.#QNAN', '<NA>', 'N/A', 'NA', 'NULL', 'NaN', 'n/a',
                            'nan', 'null', 'None']

        df, rows_skipped = read_csv_strict(file_path, na_values=common_na_values)
        parse_warnings = []
        if rows_skipped:
            parse_warnings.append(
                f"{rows_skipped} malformed line(s) could not be parsed and were excluded "
                f"from this profile. Row counts reflect parseable rows only."
            )

        if df.empty:
            redis_cache.delete(cache_key_latest)
            return {"status": "ERROR", "message": "Dataset is empty."}

        rows, columns = df.shape
        duplicate_row_count = int(df.duplicated().sum())
        missing_cells = df.isnull().sum().sum()
        total_cells = rows * columns if rows > 0 else 1
        missing_pct = (missing_cells / total_cells) * 100
        duplicate_pct = (duplicate_row_count / rows) * 100 if rows > 0 else 0

        # Quality score formula: max(0, 100 - missing_pct - duplicate_pct)
        quality_score = max(0, 100 - missing_pct - duplicate_pct)

        columns_profile = {}

        # Pre-compute target correlations if target is known (for leakage detection)
        target_correlations = {}
        if target_variable and target_variable in df.columns:
            target_series = df[target_variable]
            if pd.api.types.is_numeric_dtype(target_series):
                for col in df.columns:
                    if col == target_variable:
                        continue
                    col_series = df[col]
                    if pd.api.types.is_numeric_dtype(col_series) and col_series.nunique() > 2:
                        try:
                            corr = target_series.corr(col_series)
                            if pd.notnull(corr):
                                target_correlations[col] = corr
                        except Exception:
                            pass

        for col in df.columns:
            series = df[col]
            clean_series = series.dropna()
            missing_count = int(series.isnull().sum())
            missing_ratio = missing_count / len(series) if len(series) > 0 else 0
            unique_count = series.nunique()
            unique_ratio = unique_count / len(clean_series) if len(clean_series) > 0 else 0

            data_type = detect_data_type(series)

            mode_val = None
            if not clean_series.empty:
                mode_vals = clean_series.mode()
                if not mode_vals.empty:
                    first_mode = mode_vals.iloc[0]
                    if pd.notna(first_mode):
                        mode_val = first_mode.item() if hasattr(first_mode, "item") else first_mode

            col_profile = {
                "data_type": data_type,
                "missing_count": missing_count,
                "missing_pct": round(missing_ratio * 100, 4),
                "unique_count": unique_count,
                "unique_ratio": round(unique_ratio, 4),
                # Numeric fields (initialized to null)
                "mean": None,
                "median": None,
                "std": None,
                "skewness": None,
                "kurtosis": None,
                "iqr_lower_fence": None,
                "iqr_upper_fence": None,
                "outlier_count": None,
                "histogram_bins": None,
                # Categorical fields
                "top_values": None,
                "mode": mode_val,
                # Temporal fields
                "acf_1": None,
                "is_time_series": False,
                # Leakage & MNAR
                "leakage_risk_score": 0.0,
                "mnar_correlations": {}
            }

            # Numeric column stats with histogram bins (Phase 1 enhancement)
            if data_type in ['integer', 'float'] and not clean_series.empty and clean_series.nunique() > 2:
                numeric_data = clean_series.astype(float)
                col_profile["mean"] = round(float(numeric_data.mean()), 4)
                col_profile["median"] = round(float(numeric_data.median()), 4)
                col_profile["std"] = round(float(numeric_data.std()), 4) if len(numeric_data) > 1 else None
                col_profile["skewness"] = round(float(numeric_data.skew()), 4) if len(numeric_data) > 2 else None
                col_profile["kurtosis"] = round(float(numeric_data.kurtosis()), 4) if len(numeric_data) > 3 else None

                # IQR and outliers
                q1 = numeric_data.quantile(0.25)
                q3 = numeric_data.quantile(0.75)
                iqr = q3 - q1
                lower_fence = float(q1 - 1.5 * iqr)
                upper_fence = float(q3 + 1.5 * iqr)
                col_profile["iqr_lower_fence"] = round(lower_fence, 4)
                col_profile["iqr_upper_fence"] = round(upper_fence, 4)
                outlier_count = int(((numeric_data < lower_fence) | (numeric_data > upper_fence)).sum())
                col_profile["outlier_count"] = outlier_count

                # Histogram bins (20 bins) with IQR capping for visualization
                try:
                    # Cap values at IQR fences before binning so outliers don't compress visible distribution
                    capped_data = numeric_data.clip(lower=lower_fence, upper=upper_fence)
                    counts, edges = np.histogram(capped_data, bins=20)
                    col_profile["histogram_bins"] = [
                        {"edge": round(float(edges[i]), 4), "count": int(counts[i])}
                        for i in range(len(counts))
                    ]
                    # Raw histogram (30 bins, full range including outliers) for preview modal
                    raw_counts, raw_edges = np.histogram(numeric_data, bins=30)
                    col_profile["raw_histogram_bins"] = [
                        {"edge": round(float(raw_edges[i]), 4), "count": int(raw_counts[i])}
                        for i in range(len(raw_counts))
                    ]
                    col_profile["raw_min"] = round(float(numeric_data.min()), 4)
                    col_profile["raw_max"] = round(float(numeric_data.max()), 4)
                except Exception:
                    pass

                # Leakage risk score computation (Phase 1 enhancement)
                if target_variable and target_variable in target_correlations:
                    score = 0.0
                    # High correlation with target
                    if abs(target_correlations.get(col, 0)) > 0.95:
                        score += 0.7
                    # Near-unique identifier
                    if unique_ratio > 0.9 and rows > 100:
                        score += 0.5
                    # Column name contains target name substring
                    if target_variable.lower() in col.lower():
                        score += 0.3
                    col_profile["leakage_risk_score"] = round(min(score, 1.0), 4)

            # Categorical column stats
            if data_type == 'categorical' and not clean_series.empty:
                value_counts = clean_series.value_counts().head(10)
                col_profile["top_values"] = [
                    {"value": str(val), "count": int(cnt)} for val, cnt in value_counts.items()
                ]

                # Leakage risk for categorical (near-unique identifiers)
                if target_variable:
                    score = 0.0
                    if unique_ratio > 0.9 and rows > 100:
                        score += 0.5
                    if target_variable.lower() in col.lower():
                        score += 0.3
                    col_profile["leakage_risk_score"] = round(min(score, 1.0), 4)

            # Temporal analysis for all columns
            time_cols = [c for c in df.columns if 'time' in c.lower() or 'date' in c.lower()]
            if time_cols and not clean_series.empty:
                time_col = time_cols[0]
                try:
                    ts_df = df[[time_col, col]].dropna()
                    if len(ts_df) > 10:
                        ts_df = ts_df.sort_values(by=time_col)
                        ts_series = ts_df[col].astype(float)
                        if ts_series.nunique() > 1:
                            acf_values = acf(ts_series, nlags=1, fft=False)
                            col_profile["acf_1"] = round(float(acf_values[1]), 4) if len(acf_values) > 1 else None
                            col_profile["is_time_series"] = True
                except Exception:
                    pass

            # MNAR correlations (Phase 1 enhancement)
            missing_indicator = series.isnull().astype(int)
            if missing_indicator.sum() > 0 and missing_indicator.sum() < len(missing_indicator):
                for other_col in df.columns:
                    if other_col == col:
                        continue
                    other_series = df[other_col]
                    if pd.api.types.is_numeric_dtype(other_series) and other_series.nunique() > 2:
                        try:
                            corr = missing_indicator.corr(other_series)
                            if pd.notnull(corr) and abs(corr) > 0.3:
                                col_profile["mnar_correlations"][other_col] = round(float(corr), 4)
                        except Exception:
                            pass

            columns_profile[col] = col_profile

        # Generate new profile ID
        new_profile_id = str(uuid.uuid4())

        data_profile = {
            "profile_id": new_profile_id,
            "source_hash": source_hash,
            "parent_profile_id": existing_profile["profile_id"] if existing_profile else None,
            "dataset_name": file_name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "row_count": rows,
            "column_count": columns,
            "duplicate_row_count": duplicate_row_count,
            "quality_score": round(quality_score, 4),
            "rows_skipped": rows_skipped,
            "parse_warnings": parse_warnings,
            "columns": columns_profile
        }

        # Store under latest pointer (overwrites previous)
        redis_cache.set(cache_key_latest, json.dumps(data_profile, cls=NumpyJSONEncoder), ex=86400)

        # Also store under versioned key for historical comparison
        versioned_cache_key = f"profile:{file_name}:{new_profile_id}"
        redis_cache.set(versioned_cache_key, json.dumps(data_profile, cls=NumpyJSONEncoder), ex=604800)

        # Schema drift detection (Phase 1.2)
        drift_report = None
        if existing_profile:
            drift_report = _detect_schema_drift(existing_profile, data_profile, df)
            if drift_report and drift_report.get("has_drift"):
                drift_cache_key = f"drift:{file_name}:{new_profile_id}"
                redis_cache.set(drift_cache_key, json.dumps(drift_report, cls=NumpyJSONEncoder), ex=604800)

        return {"status": "SUCCESS", "result": data_profile, "drift_report": drift_report}

    except Exception as e:
        logger.exception("CRITICAL ERROR in profile_dataset for %s", file_path)
        raise e


def _detect_schema_drift(old_profile: dict, new_profile: dict, df: pd.DataFrame) -> dict:
    """
    Detects schema drift between two profiles:
    - Columns added/removed
    - Data type changes
    - Missing rate delta > 10%
    - Distribution shift via KS test (p < 0.05)
    """
    from scipy import stats

    drift_detected = False
    drift_details = {
        "columns_added": [],
        "columns_removed": [],
        "data_type_changes": [],
        "missing_rate_changes": [],
        "distribution_shifts": []
    }

    old_columns = set(old_profile.get("columns", {}).keys())
    new_columns = set(new_profile.get("columns", {}).keys())

    # Columns added/removed
    drift_details["columns_added"] = list(new_columns - old_columns)
    drift_details["columns_removed"] = list(old_columns - new_columns)
    if drift_details["columns_added"] or drift_details["columns_removed"]:
        drift_detected = True

    # Data type changes and missing rate delta
    for col in new_columns & old_columns:
        old_col = old_profile["columns"].get(col, {})
        new_col = new_profile["columns"].get(col, {})

        # Data type change
        if old_col.get("data_type") != new_col.get("data_type"):
            drift_details["data_type_changes"].append({
                "column": col,
                "old_type": old_col.get("data_type"),
                "new_type": new_col.get("data_type")
            })
            drift_detected = True

        # Missing rate delta > 10%
        old_missing = old_col.get("missing_pct", 0)
        new_missing = new_col.get("missing_pct", 0)
        if abs(new_missing - old_missing) > 10:
            drift_details["missing_rate_changes"].append({
                "column": col,
                "old_missing_pct": old_missing,
                "new_missing_pct": new_missing,
                "delta": round(new_missing - old_missing, 2)
            })
            drift_detected = True

        # Distribution shift via KS test for numeric columns
        if new_col.get("data_type") in ['integer', 'float'] and old_col.get("histogram_bins"):
            try:
                # Reconstruct approximate distributions from histogram bins
                old_bins = old_col.get("histogram_bins", [])
                if old_bins and len(old_bins) > 1:
                    # Use bin edges and counts to approximate samples
                    old_edges = [b["edge"] for b in old_bins] + [old_bins[-1]["edge"] + (old_bins[-1]["edge"] - old_bins[-2]["edge"]) if len(old_bins) > 1 else 1]
                    old_counts = [b["count"] for b in old_bins]

                    # Get new data for KS test
                    col_series = df[col].dropna().astype(float)
                    if len(col_series) > 10:
                        # Perform KS test
                        ks_statistic, p_value = stats.kstest(col_series, lambda x: np.interp(x, old_edges[:-1], np.cumsum(old_counts) / sum(old_counts)))
                        if p_value < 0.05:
                            drift_details["distribution_shifts"].append({
                                "column": col,
                                "ks_statistic": round(float(ks_statistic), 4),
                                "p_value": round(float(p_value), 4)
                            })
                            drift_detected = True
            except Exception:
                pass

    return {
        "has_drift": drift_detected,
        "old_profile_id": old_profile.get("profile_id"),
        "new_profile_id": new_profile.get("profile_id"),
        "detected_at": datetime.now(timezone.utc).isoformat(),
        **drift_details
    } if drift_detected else None


# P1-9: generate_comprehensive_stats and generate_diagnostic_report are deleted.
# The first deadlocked workers (.get() inside a task); both were superseded by
# the unified profile_dataset task. /api/statistics/{name} now dispatches it.

@celery_app.task(time_limit=1800)
def generate_treatment_plans_task(dataset_name: str, target_variable: str, goal: str, temporal_column: str = None):
    """
    Generates three competing data cleaning plans by passing the diagnostic report to an LLM.
    Bug 2 Fix: Accept target_variable, goal, and temporal_column as explicit task parameters.
    Embed modeling_context into report object BEFORE any LLM call. Never mutate cached data.
    """
    try:
        # Use the unified profile cache key
        cache_key = f"profile:v1:{dataset_name}"
        report_str = redis_cache.get(cache_key)

        if not report_str:
            return {"status": "FAILURE", "error": f"Profile for {dataset_name} not found in cache."}

        data_profile = json.loads(report_str)

        # Build a fresh modeling_context from explicit parameters - never mutate cached data
        modeling_context = {
            'target_variable': target_variable,
            'goal': goal,
            'temporal_column': temporal_column
        }

        # Pass context separately to AI service (it expects this structure)
        # The AI service will receive modeling_context via diagnostic_report['modeling_context']
        ai_input = {
            **data_profile,  # Spread the profile data
            'modeling_context': modeling_context  # Add fresh context
        }

        plans = get_treatment_plan_hypotheses(ai_input)

        if "error" in plans:
             return {"status": "FAILURE", "error": plans.get("details", "AI service failed to generate plans.")}

        return {"status": "SUCCESS", "result": plans}

    except Exception as e:
        logger.exception("CRITICAL ERROR in generate_treatment_plans_task for %s", dataset_name)
        return {"status": "FAILURE", "error": str(e)}

def get_temporal_profile(df: pd.DataFrame, col: str) -> dict:
    time_cols = [c for c in df.columns if 'time' in c.lower() or 'date' in c.lower()]
    if not time_cols:
        return {"is_time_series": False}
    time_col = time_cols[0]
    try:
        ts_data = pd.to_datetime(df[time_col], errors='coerce').dropna()
        if ts_data.empty: return {"is_time_series": False}
    except Exception:
        return {"is_time_series": False}
    ts_series = df.set_index(time_col)[col].sort_index().dropna()
    acf_1 = None
    if ts_series.nunique() > 1 and len(ts_series) > 1:
        try:
            acf_1 = round(acf(ts_series, nlags=1, fft=False)[1], 2)
        except Exception:
            acf_1 = None
    return {"is_time_series": True, "temporal_stability_acf1": acf_1}

def get_mnar_indicators(df: pd.DataFrame, col: str) -> dict:
    correlations = {}
    missing_indicator = df[col].isnull().astype(int)
    for other_col in df.columns:
        if other_col == col: continue
        try:
            if pd.api.types.is_numeric_dtype(df[other_col]) and df[other_col].nunique() > 1:
                corr = missing_indicator.corr(df[other_col])
                if pd.notnull(corr) and abs(corr) > 0.3:
                    correlations[other_col] = round(corr, 2)
        except Exception:
            continue
    return correlations

def get_statistical_profile(df: pd.DataFrame, column_name: str) -> dict:
    detected_type = detect_data_type(df[column_name])

    missing_count = int(df[column_name].isnull().sum())
    total_count = len(df[column_name])
    missing_pct = (missing_count / total_count) * 100 if total_count > 0 else 0

    profile = {
        "column": column_name,
        "missing_count": missing_count,
        "missing_pct": round(missing_pct, 4),
        "data_type": detected_type,
        "unique_values": df[column_name].nunique()
    }
    if detected_type in ['integer', 'float', 'identifier']:
        clean_data = df[column_name].dropna()
        if not clean_data.empty:
            profile["mean"] = round(clean_data.mean(), 2)
            profile["median"] = round(clean_data.median(), 2)
    profile["mnar_indicators"] = get_mnar_indicators(df, column_name)
    profile.update(get_temporal_profile(df, column_name))
    return profile

def perform_standardization(df: pd.DataFrame, column_name: str, method: str, file_path: str) -> dict:
    new_col_name = f"{column_name}_{method}_scaled"
    if new_col_name in df.columns:
        return {"status": "SKIPPED", "message": f"Column '{new_col_name}' already exists."}
    if not pd.api.types.is_numeric_dtype(df[column_name]):
        raise ValueError(f"Column '{column_name}' is not numeric.")
    if df[column_name].isnull().any():
        raise ValueError(f"Column '{column_name}' contains missing values. Impute first.")
    scaler = StandardScaler() if method == 'standard' else MinMaxScaler()
    df[new_col_name] = scaler.fit_transform(df[[column_name]].values.astype(np.float32))
    df.to_csv(file_path, index=False)
    q1 = float(df[column_name].quantile(0.25))
    q3 = float(df[column_name].quantile(0.75))
    audit_report = {
        "new_column_added": new_col_name, "message": f"Successfully created new column: '{new_col_name}'.",
        "method": method, "timestamp_utc": datetime.now(timezone.utc).isoformat(), "row_count_affected": len(df),
        "input_stats_robust": {"median": float(df[column_name].median()), "interquartile_range": q3 - q1}
    }
    return audit_report

def perform_delete_column(df: pd.DataFrame, column_name: str, file_path: str):
    if column_name not in df.columns:
        raise ValueError(f"Column '{column_name}' not found.")
    df = df.drop(columns=[column_name])
    df.to_csv(file_path, index=False)
    return {"message": f"Successfully deleted column '{column_name}' and updated the dataset."}

@celery_app.task
def perform_dataset_cleaning_task(file_path: str, action_type: str):
    try:
        if not os.path.exists(file_path):
            return {"status": "FAILURE", "error": "File not found."}

        df, _rows_skipped = read_csv_strict(file_path)
        original_rows = len(df)

        if action_type == 'drop_na_rows':
            df = df.dropna()
            rows_affected = original_rows - len(df)
            message = f"Successfully dropped {rows_affected} rows with missing values."

        elif action_type == 'drop_duplicate_rows':
            df = df.drop_duplicates()
            rows_affected = original_rows - len(df)
            message = f"Successfully dropped {rows_affected} duplicate rows."

        else:
            return {"status": "FAILURE", "error": f"Unknown cleaning action: {action_type}"}

        # Overwrite the original file with the cleaned data
        df.to_csv(file_path, index=False)

        return {"status": "SUCCESS", "message": message, "rows_affected": rows_affected}

    except Exception as e:
        logger.exception("CRITICAL ERROR in perform_dataset_cleaning_task for %s", file_path)
        return {"status": "FAILURE", "error": str(e)}

def perform_imputation(df: pd.DataFrame, column_name: str, method: str, value=None) -> dict:
    if column_name not in df.columns:
        raise ValueError(f"Column '{column_name}' not found.")

    original_missing_count = int(df[column_name].isnull().sum())
    if original_missing_count == 0:
        return {"message": "No missing values to impute.", "rows_affected": 0}

    if method == 'mean':
        fill_value = df[column_name].mean()
        df[column_name] = df[column_name].fillna(fill_value)  # P2-4: no inplace on a column slice (pandas 3 CoW)
    elif method == 'median':
        fill_value = df[column_name].median()
        df[column_name] = df[column_name].fillna(fill_value)
    elif method == 'mode':
        fill_value = df[column_name].mode()[0]
        df[column_name] = df[column_name].fillna(fill_value)
    elif method == 'constant':
        dtype = df[column_name].dtype
        try:
            fill_value = pd.Series([value]).astype(dtype).iloc[0]
        except (ValueError, TypeError):
            fill_value = value
        df[column_name] = df[column_name].fillna(fill_value)
    else:
        raise ValueError(f"Invalid imputation method: {method}")

    return {"message": f"Successfully imputed {original_missing_count} missing values in '{column_name}'.", "rows_affected": original_missing_count}

def _validate_plan_robust(df: pd.DataFrame, plan: dict, target: str, goal: str) -> dict:
    """
    Returns a dict: {"score": float, "error": str/None}

    Applies the plan through FUNCTION_REGISTRY only. Never executes strings.
    """
    try:
        # --- EXECUTION ---
        # Deterministic, registry-only application. Any 'python_code' key present
        # in a client-supplied plan is ignored outright — see note in module docstring.
        df_processed = _apply_actions_to_df(df, plan.get('steps', []))

        # --- PREPARATION ---
        df_processed = df_processed.dropna(subset=[target])
        if df_processed.empty:
            return {"score": -np.inf, "error": "Dataset became empty after cleaning."}

        # --- ROBUSTNESS: SANITIZE INFINITY ---
        # Feature Engineering (e.g. division) often creates inf. Treat as NaN for imputation.
        df_processed = df_processed.replace([np.inf, -np.inf], np.nan)

        X = df_processed.drop(columns=[target])
        y = df_processed[target]

        # Check for single class (Crash prevention for ROC AUC)
        if goal == 'classification' and y.nunique() < 2:
             return {"score": -np.inf, "error": "Target has only 1 class (needs 2+ for classification)."}

        # --- PIPELINE SETUP ---
        numeric_cols = X.select_dtypes(include=['number']).columns
        categorical_cols = X.select_dtypes(include=['object', 'category']).columns

        numeric_transformer = Pipeline(steps=[
            ('imputer', SimpleImputer(strategy='median')),
            ('scaler', StandardScaler())
        ])

        categorical_transformer = Pipeline(steps=[
            ('imputer', SimpleImputer(strategy='constant', fill_value='missing')),
            ('onehot', OneHotEncoder(handle_unknown='ignore', sparse_output=False))
        ])

        preprocessor = ColumnTransformer(transformers=[
            ('num', numeric_transformer, numeric_cols),
            ('cat', categorical_transformer, categorical_cols)
        ])

        if goal == 'classification':
            model = RandomForestClassifier(n_estimators=30, max_depth=8, random_state=42, n_jobs=-1)
            # Handle text targets
            if y.dtype == 'object':
                le = LabelEncoder()
                y = le.fit_transform(y)
            metric = roc_auc_score
        else:
            model = RandomForestRegressor(n_estimators=30, max_depth=8, random_state=42, n_jobs=-1)
            metric = lambda y_true, y_pred: -np.sqrt(mean_squared_error(y_true, y_pred))

        # --- TRAINING ---
        pipeline = Pipeline(steps=[('preprocessor', preprocessor), ('model', model)])
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

        pipeline.fit(X_train, y_train)

        # --- SCORING ---
        if goal == 'classification':
            # Handle binary vs multiclass
            if len(np.unique(y)) > 2:
                probs = pipeline.predict_proba(X_test)
                score = metric(y_test, probs, multi_class='ovr')
            else:
                probs = pipeline.predict_proba(X_test)[:, 1]
                score = metric(y_test, probs)
        else:
            preds = pipeline.predict(X_test)
            score = metric(y_test, preds)

        return {"score": score, "error": None}

    except Exception as e:
        return {"score": -np.inf, "error": str(e)}

def detect_data_leakage(df: pd.DataFrame, target: str) -> list:
    warnings = []

    # P2-5: never mutate the caller's frame (the old df[target] assignment
    # silently rewrote the baseline dataset during simulation).
    df = df.copy()

    try:
        if df[target].dtype == 'object':
            df[target] = pd.to_numeric(df[target], errors='coerce')
    except (ValueError, TypeError):
        pass

    # Check 1: Perfect Correlation (Leakage)
    numeric_cols = df.select_dtypes(include=[np.number]).columns

    if target in numeric_cols:
        correlations = df[numeric_cols].corrwith(df[target]).abs()
        # Filter out the target itself
        correlations = correlations.drop(target, errors='ignore')

        # Flag anything > 0.95 (Extremely suspicious)
        suspicious_cols = correlations[correlations > 0.95].index.tolist()

        if suspicious_cols:
            warnings.append(
                f"High Leakage Risk: Columns {suspicious_cols} are >95% correlated with the target."
            )

    # Check 2: ID Column Detection
    categorical_cols = df.select_dtypes(include=['object', 'category']).columns
    for col in categorical_cols:
        if col == target: continue

        unique_ratio = df[col].nunique() / len(df)
        if unique_ratio > 0.95 and len(df) > 100:
            msg = f"Potential ID Column: '{col}' is nearly unique. It may cause overfitting."
            warnings.append(msg)

    return warnings

# --- START: NEW MAIN SIMULATION TASK ---
@celery_app.task(time_limit=3600)
def run_impact_simulation_task(dataset_name: str, plans: dict, target_variable: str, goal: str):
    try:
        file_path = os.path.join(os.path.dirname(__file__), '..', 'public', dataset_name)
        df_raw, _rows_skipped = read_csv_strict(file_path)

        leakage_warnings = detect_data_leakage(df_raw, target_variable)

        # 1. Baseline
        baseline_res = _validate_plan_robust(df_raw, {}, target_variable, goal)
        baseline_score = baseline_res["score"]

        simulation_results = []
        plan_keys = ['conservative_plan', 'balanced_plan', 'aggressive_plan', 'architect_plan']
        metric_name = "AUC" if goal == 'classification' else "Neg RMSE"

        for key in plan_keys:
            if key not in plans: continue
            plan = plans[key]

            # 2. Plan Score
            plan_res = _validate_plan_robust(df_raw, plan, target_variable, goal)
            plan_score = plan_res["score"]
            error_msg = plan_res["error"]

            # 3. Handle Errors/Deltas
            if error_msg or not np.isfinite(plan_score) or not np.isfinite(baseline_score):
                 impact_data = {
                    "metric_name": metric_name,
                    "baseline_score": "N/A",
                    "plan_score": "Error",
                    "delta_percent": 0,
                    # Show the REAL error in the UI
                    "impact_string": f"<b>Simulation Failed:</b> {error_msg or baseline_res.get('error') or 'Unknown error'}"
                }
            else:
                delta = ((plan_score - baseline_score) / abs(baseline_score)) * 100 if baseline_score != 0 else 0
                sign = "+" if delta >= 0 else ""
                impact_data = {
                    "metric_name": metric_name,
                    "baseline_score": round(baseline_score, 4),
                    "plan_score": round(plan_score, 4),
                    "delta_percent": round(delta, 2),
                    "impact_string": f"{metric_name} changed by *{sign}{delta:.2f}%*"
                }

            plan['measured_impact'] = impact_data
            simulation_results.append(plan)

        sorted_results = sorted(
            simulation_results,
            key=lambda p: p['measured_impact'].get('delta_percent', -999),
            reverse=True
        )

        return {"status": "SUCCESS", "result": sorted_results,"warnings": leakage_warnings}

    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        return {"status": "FAILURE", "error": str(e)}

@celery_app.task
def apply_ai_plan_task(dataset_name: str, action_backlog: list, note: str = "Applied AI Plan",
                       ml_improvement_score: float = 0.5, target_variable: str = None):
    """
    Phase 5 extended: now accepts ml_improvement_score (from parallel simulation) and
    target_variable so effectiveness score can be computed post-apply.
    """
    """
    Phase 3: Executes the PDIA action backlog using the deterministic execution engine.
    No exec(). Full rollback on failure. Auditable transaction trail.

    Bug 1 Fix: Delete cache keys FIRST → write CSV → dispatch background re-profile task.
    This ensures that if the task crashes mid-write, cache is already invalidated (not stale).
    """
    try:
        file_path = os.path.join(os.path.dirname(__file__), '..', 'public', dataset_name)
        if not os.path.exists(file_path):
            return {"status": "FAILURE", "error": "File not found."}

        # 1. Load Data — P1-10: strict parse; skipped malformed lines are counted
        # and reported in the result instead of vanishing silently.
        df, rows_skipped = read_csv_strict(file_path)
        original_rows = len(df)
        original_columns = len(df.columns)

        # 2. Load profile for validation context
        cache_key = f"profile:v1:{dataset_name}"
        profile_data_str = redis_cache.get(cache_key)
        profile_data = json.loads(profile_data_str) if profile_data_str else None

        # 3. Validate the action backlog
        validation_result = validate_plan(action_backlog, df, profile_data)

        # Check for skipped actions
        if validation_result.skipped_actions:
            logger.warning("Skipped %d actions during validation", len(validation_result.skipped_actions))
            for skipped in validation_result.skipped_actions:
                logger.warning("  - %s: %s", skipped.get('action_id'), skipped.get('skip_reason'))

        # Use only approved actions
        approved_actions = validation_result.approved_actions

        # P1-11: confirmation-required actions are held back and REPORTED to the
        # client, never silently dropped. The UI renders them for explicit
        # re-submission with confirmed_action_ids.
        confirmation_held_back = list(validation_result.confirmation_required_actions)
        if confirmation_held_back:
            logger.info("Held back %d confirmation-required action(s)", len(confirmation_held_back))

        # 4. Execute transactionally with full rollback on failure
        df_result, execution_summary = execute_transactionally(
            df=df,
            approved_actions=approved_actions,
            dataset_name=dataset_name,
            profile_data=profile_data,
            redis_client=redis_cache
        )

        # Check if rollback occurred
        if execution_summary.get("rollback_performed"):
            return {
                "status": "ROLLBACK",
                "message": "Execution failed and rolled back to original state.",
                "execution_log": execution_summary.get("execution_log", []),
                "critical_error": execution_summary.get("critical_error")
            }

        # 4.5. CHECKPOINT: Save snapshot before overwriting (enables rollback)
        checkpoint_info = None
        try:
            from checkpoint_manager import create_checkpoint
            actions_summary = ', '.join(
                a.get('function_name', '?') for a in approved_actions[:3]
            )
            if len(approved_actions) > 3:
                actions_summary += f' +{len(approved_actions) - 3} more'
            checkpoint_info = create_checkpoint(
                dataset_name, file_path,
                batch_label=f'{note} — {actions_summary}'
            )
        except Exception as cp_err:
            logger.warning("Warning: Checkpoint creation failed (non-fatal): %s", cp_err)

        # 5. BUG 1 FIX: Invalidate Cache FIRST before writing
        # If we crash mid-write, cache is already gone (no stale data)
        redis_cache.delete(f"profile:v1:{dataset_name}")
        redis_cache.delete(f"statistics:{dataset_name}")
        redis_cache.delete(f"diagnostics:{dataset_name}")

        # 6. Save Over the Original File
        df_result.to_csv(file_path, index=False)

        # 7. PHASE 5: Compute Effectiveness Score using before-profile (profile_data)
        # profile_data was loaded BEFORE cache invalidation — it IS the "before" state.
        if profile_data and len(approved_actions) > 0:
            try:
                # Leakage detection on the cleaned result
                _leakage_post = []
                if target_variable:
                    try:
                        _leakage_post = detect_data_leakage(df_result.copy(), target_variable)
                    except Exception:
                        pass  # Non-fatal if leakage check fails

                effectiveness_data = _compute_effectiveness_score(
                    before_profile=profile_data,
                    after_df=df_result,
                    ml_improvement_score=float(ml_improvement_score) if ml_improvement_score is not None else 0.5,
                    leakage_warnings=_leakage_post
                )
                redis_cache.set(
                    f"effectiveness:{dataset_name}",
                    json.dumps(effectiveness_data, cls=NumpyJSONEncoder),
                    ex=86400  # 24h TTL
                )
                execution_summary["cleaning_effectiveness"] = effectiveness_data["cleaning_effectiveness"]
                logger.info("Effectiveness score stored for %s: %.4f", dataset_name, effectiveness_data['cleaning_effectiveness'])
            except Exception as eff_err:
                logger.warning("Warning: Effectiveness score computation failed (non-fatal): %s", eff_err)

        # 8. PHASE 5: Generate Cleaning Recipe in background
        try:
            generate_cleaning_recipe_task.delay(
                dataset_name,
                [dict(a) for a in approved_actions],  # serialize copies
                profile_data  # before_profile for statistical justifications
            )
        except Exception as recipe_err:
            logger.warning("Warning: Recipe generation dispatch failed (non-fatal): %s", recipe_err)

        # 9. Dispatch background re-profile task to regenerate fresh cache
        reprofile_task = profile_dataset.delay(file_path)

        # Update execution summary with result profile ID (will be set after re-profiling)
        execution_summary["result_profile_id"] = "pending_reprofile"
        execution_summary["reprofile_task_id"] = reprofile_task.id

        return {
            "status": "SUCCESS",
            "message": f"Successfully applied {len(approved_actions)} actions. Dataset updated.",
            "rows_before": original_rows,
            "rows_after": len(df_result),
            "columns_before": original_columns,
            "columns_after": len(df_result.columns),
            "rows_skipped_on_read": rows_skipped,
            "actions_applied": execution_summary["actions_applied"],
            "actions_skipped": [a.get("action_id") for a in validation_result.skipped_actions],
            "confirmation_required_actions": confirmation_held_back,
            "checkpoint": checkpoint_info,
            "execution_summary": execution_summary
        }

    except Exception as e:
        logger.exception("CRITICAL ERROR in apply_ai_plan_task: %s", e)
        return {"status": "FAILURE", "error": str(e)}


@celery_app.task
def route_task(dataset_name: str, column_name: str, task_type: str, task_params: dict = None):
    try:
        file_path = os.path.join(
            os.path.dirname(__file__), '..', 'public', os.path.basename(dataset_name)
        )
        df = pd.read_csv(file_path)
        if task_type == 'diagnosis':
            profile = get_statistical_profile(df, column_name)
            result = get_ai_interpretation(profile)
            return {"status": "SUCCESS", "result": result}
        elif task_type == 'delete_column':
            result = perform_delete_column(df, column_name, file_path)
            return {"status": "SUCCESS", "result": result}
        elif task_type.startswith('impute_'):
            method = task_type.split('_')[1]
            custom_value = task_params.get('value') if task_params else None
            result = perform_imputation(df, column_name, method, value=custom_value)
            df.to_csv(file_path, index=False)
            return {"status": "SUCCESS", "result": result}
        elif task_type in ['standard_scale', 'minmax_scale']:
            method = 'standard' if task_type == 'standard_scale' else 'minmax'
            result = perform_standardization(df, column_name, method, file_path)
            return {"status": "SUCCESS", "result": result}
        else:
            return {"status": "ERROR", "message": "Unknown task type."}
    except Exception as e:
        return {"status": "FAILURE", "error": str(e)}


# ============================================================================
# PHASE 5.1: FULL-REGISTRY ACTION APPLICATION FOR ACCURATE SIMULATION
# ============================================================================

def _apply_actions_to_df(df: pd.DataFrame, actions: list) -> pd.DataFrame:
    """
    Applies PDIA action backlog to a dataframe using the full FUNCTION_REGISTRY.
    Falls back gracefully on individual action failures — never breaks the pipeline.
    Handles both 'column' (singular, from AI backlog) and 'target_columns' (list, from engine).
    """
    df_result = df.copy()
    for action in actions:
        func_name = action.get('function_name', '')

        # Normalize column references
        target_cols = action.get('target_columns') or []
        if not target_cols:
            col_val = action.get('column', '')
            if isinstance(col_val, str) and col_val:
                target_cols = [col_val]
            elif isinstance(col_val, list):
                target_cols = col_val
        if isinstance(target_cols, str):
            target_cols = [target_cols]

        params = action.get('recommended_params') or action.get('params') or {}

        if func_name not in FUNCTION_REGISTRY:
            logger.info("[sim] Skipping unknown function '%s'", func_name)
            continue

        # Only pass columns that still exist (earlier actions may have deleted them)
        valid_cols = [c for c in target_cols if c in df_result.columns]
        if target_cols and not valid_cols:
            logger.info("[sim] All target columns for '%s' already removed; skipping", func_name)
            continue

        try:
            df_result, _ = FUNCTION_REGISTRY[func_name](df_result, valid_cols, params)
        except Exception as e:
            logger.warning("[sim] Warning: %s on %s failed: %s", func_name, valid_cols, e)
            continue  # Non-fatal: continue with next action

    return df_result


# ============================================================================
# PHASE 5.1: SHARED ML PROBE PIPELINE
# ============================================================================

def _run_ml_pipeline(df_processed: pd.DataFrame, target: str, goal: str) -> dict:
    """
    Runs a probe ML model on the processed dataframe and returns a comparable score.
    Extracted from _validate_plan_robust for shared use across Phase 5 subtasks.

    Returns: {"score": float, "error": str|None, "metric_name": str}
    """
    try:
        df_processed = df_processed.dropna(subset=[target])
        if df_processed.empty:
            return {"score": -np.inf, "error": "Dataset empty after dropping null targets.", "metric_name": "N/A"}

        if len(df_processed) < 20:
            return {"score": -np.inf, "error": f"Too few rows ({len(df_processed)}) for reliable ML evaluation.", "metric_name": "N/A"}

        df_processed = df_processed.replace([np.inf, -np.inf], np.nan)

        X = df_processed.drop(columns=[target])
        y = df_processed[target]

        # Guard: single class for classification
        if goal == 'classification' and y.nunique() < 2:
            return {"score": -np.inf, "error": "Target has only 1 class after cleaning.", "metric_name": "AUC"}

        # Guard: non-numeric target for regression
        if goal == 'regression' and not pd.api.types.is_numeric_dtype(y):
            try:
                y = pd.to_numeric(y, errors='raise')
            except Exception:
                return {"score": -np.inf, "error": "Regression target is not numeric.", "metric_name": "Neg-RMSE"}

        numeric_cols = X.select_dtypes(include=['number']).columns
        # Exclude high-cardinality categoricals to prevent OHE explosion
        categorical_cols = [c for c in X.select_dtypes(include=['object', 'category']).columns
                            if X[c].nunique() <= 50]

        numeric_transformer = Pipeline([
            ('imputer', SimpleImputer(strategy='median')),
            ('scaler', StandardScaler())
        ])
        cat_transformer = Pipeline([
            ('imputer', SimpleImputer(strategy='constant', fill_value='missing')),
            ('onehot', OneHotEncoder(handle_unknown='ignore', sparse_output=False, max_categories=50))
        ])

        transformers = []
        if len(numeric_cols) > 0:
            transformers.append(('num', numeric_transformer, numeric_cols))
        if categorical_cols:
            transformers.append(('cat', cat_transformer, categorical_cols))

        if not transformers:
            return {"score": -np.inf, "error": "No usable feature columns after preprocessing.", "metric_name": "N/A"}

        preprocessor = ColumnTransformer(transformers=transformers, remainder='drop')
        metric_name = "AUC" if goal == 'classification' else "Neg-RMSE"

        if goal == 'classification':
            model = RandomForestClassifier(n_estimators=30, max_depth=8, random_state=42, n_jobs=-1)
            if y.dtype == 'object' or str(y.dtype) == 'category':
                le = LabelEncoder()
                y = le.fit_transform(y)
        else:
            model = RandomForestRegressor(n_estimators=30, max_depth=8, random_state=42, n_jobs=-1)

        pipeline = Pipeline([('preprocessor', preprocessor), ('model', model)])

        # Stratify split for classification when possible
        try:
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=0.2, random_state=42,
                stratify=(y if goal == 'classification' else None)
            )
        except ValueError:
            X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

        pipeline.fit(X_train, y_train)

        if goal == 'classification':
            n_classes = len(np.unique(y))
            if n_classes > 2:
                probs = pipeline.predict_proba(X_test)
                score = roc_auc_score(y_test, probs, multi_class='ovr')
            else:
                probs = pipeline.predict_proba(X_test)[:, 1]
                score = roc_auc_score(y_test, probs)
        else:
            preds = pipeline.predict(X_test)
            score = -np.sqrt(mean_squared_error(y_test, preds))  # Negative RMSE: higher = better

        return {"score": float(score), "error": None, "metric_name": metric_name}

    except Exception as e:
        return {"score": -np.inf, "error": str(e), "metric_name": "N/A"}


# ============================================================================
# PHASE 5.2: COMPOSITE EFFECTIVENESS SCORE
# ============================================================================

def _compute_effectiveness_score(
    before_profile: dict,
    after_df: pd.DataFrame,
    ml_improvement_score: float,
    leakage_warnings: list
) -> dict:
    """
    Computes the 4-component cleaning effectiveness score per the Phase 5 spec:
      0.30 * missing_reduction_score
      0.20 * skew_reduction_score
      0.40 * ml_improvement_score
      0.10 * leakage_absence_score
    All components normalized to [0, 1]. Stored in Redis as effectiveness:{dataset_name}.
    """
    # --- Component 1: Missing Reduction ---
    before_cols = before_profile.get('columns', {})
    before_missing = sum(int(c.get('missing_count', 0)) for c in before_cols.values())
    before_rows    = max(int(before_profile.get('row_count', 1)), 1)
    before_col_n   = max(int(before_profile.get('column_count', 1)), 1)
    before_total   = before_rows * before_col_n
    before_missing_pct = before_missing / before_total

    after_rows_n, after_col_n = after_df.shape
    after_total = max(after_rows_n * after_col_n, 1)
    after_missing = int(after_df.isnull().sum().sum())
    after_missing_pct = after_missing / after_total

    if before_missing_pct > 0.001:
        missing_reduction_score = min(1.0, max(0.0,
            (before_missing_pct - after_missing_pct) / before_missing_pct))
    else:
        missing_reduction_score = 1.0  # Already perfectly clean

    # --- Component 2: Skew Reduction ---
    skew_reductions = []
    max_before_skew = 0.001  # Avoid division by zero

    for col_name, col_info in before_cols.items():
        b_skew = col_info.get('skewness')
        if b_skew is None or col_name not in after_df.columns:
            continue
        try:
            clean_vals = after_df[col_name].dropna()
            if len(clean_vals) > 2 and pd.api.types.is_numeric_dtype(after_df[col_name]):
                a_skew = float(clean_vals.skew())
                reduction = abs(float(b_skew)) - abs(a_skew)
                skew_reductions.append(reduction)
                max_before_skew = max(max_before_skew, abs(float(b_skew)))
        except Exception:
            continue

    if skew_reductions:
        raw_mean = float(np.mean(skew_reductions))
        reference = max(max_before_skew, 2.0)  # Normalize: 2.0 skew = "significant"
        skew_reduction_score = min(1.0, max(0.0, raw_mean / reference))
    else:
        skew_reduction_score = 0.5  # Neutral when no numeric cols measured

    # --- Component 3: ML Improvement (passed in from parallel simulation) ---
    ml_improvement_clamped = min(1.0, max(0.0, float(ml_improvement_score)))

    # --- Component 4: Leakage Absence ---
    leakage_absence_score = 1.0 if not leakage_warnings else 0.0

    # --- Composite Effectiveness ---
    effectiveness = (
        0.30 * missing_reduction_score +
        0.20 * skew_reduction_score +
        0.40 * ml_improvement_clamped +
        0.10 * leakage_absence_score
    )

    return {
        "cleaning_effectiveness":   round(float(effectiveness), 4),
        "missing_reduction_score":  round(float(missing_reduction_score), 4),
        "skew_reduction_score":     round(float(skew_reduction_score), 4),
        "ml_improvement_score":     round(float(ml_improvement_clamped), 4),
        "leakage_absence_score":    float(leakage_absence_score),
        "quality_improvement":      round(float(missing_reduction_score), 4),
        "skew_reduction":           round(float(skew_reduction_score), 4),
        "ml_improvement":           round(float(ml_improvement_clamped), 4),
        "leakage_prevention":       float(leakage_absence_score),
        "computed_at":              datetime.now(timezone.utc).isoformat()
    }


# ============================================================================
# PHASE 5.3: PYTHON CODE TEMPLATE RENDERER (deterministic, not LLM)
# ============================================================================

def _render_python_template(func_name: str, cols: list, params: dict, applied_values: dict) -> list:
    """
    Returns a list of Python code lines for a single cleaning action.
    Template-based: deterministic, reproducible, pipeline-deployable.
    Every registered function has a corresponding template.
    """
    lines = []
    cols_repr = repr(cols)

    if func_name == 'impute_median':
        for col in cols:
            val = applied_values.get(col, f'df["{col}"].median()')
            lines.append(f'df["{col}"] = df["{col}"].fillna({val})  # Median imputation')

    elif func_name == 'impute_mean':
        for col in cols:
            val = applied_values.get(col, f'df["{col}"].mean()')
            lines.append(f'df["{col}"] = df["{col}"].fillna({val})  # Mean imputation')

    elif func_name == 'impute_mode':
        for col in cols:
            val = applied_values.get(col)
            if val is not None:
                lines.append(f'df["{col}"] = df["{col}"].fillna({repr(val)})  # Mode imputation')
            else:
                lines.append(f'df["{col}"] = df["{col}"].fillna(df["{col}"].mode().iloc[0] if not df["{col}"].mode().empty else df["{col}"])  # Mode')

    elif func_name == 'impute_constant':
        fill_val = params.get('value', 0)
        for col in cols:
            lines.append(f'df["{col}"] = df["{col}"].fillna({repr(fill_val)})')

    elif func_name == 'clip_outliers':
        multiplier = params.get('multiplier', 1.5)
        for col in cols:
            safe = col.replace(' ', '_').replace('-', '_')
            lines.append(f'# IQR outlier clipping: "{col}" (multiplier={multiplier})')
            lines.append(f'_q1_{safe} = df["{col}"].quantile(0.25)')
            lines.append(f'_q3_{safe} = df["{col}"].quantile(0.75)')
            lines.append(f'_iqr_{safe} = _q3_{safe} - _q1_{safe}')
            lines.append(f'df["{col}"] = df["{col}"].clip(lower=_q1_{safe} - {multiplier}*_iqr_{safe}, upper=_q3_{safe} + {multiplier}*_iqr_{safe})')

    elif func_name == 'drop_rows_where_null':
        lines.append(f'df = df.dropna(subset={cols_repr})')

    elif func_name == 'drop_duplicate_rows':
        subset = cols if cols else None
        lines.append(f'df = df.drop_duplicates(subset={repr(subset)})')

    elif func_name == 'delete_column':
        lines.append(f'df = df.drop(columns={cols_repr}, errors="ignore")')

    elif func_name == 'log_transform':
        for col in cols:
            safe = col.replace(' ', '_').replace('-', '_')
            lines.append(f'# Log transform "{col}" (shifts negative/zero values first)')
            lines.append(f'_shift_{safe} = max(0, -df["{col}"].min()) + 1')
            lines.append(f'df["{col}"] = np.log1p(df["{col}"] + _shift_{safe})')

    elif func_name == 'standard_scale':
        for col in cols:
            lines.append(f'df["{col}"] = (df["{col}"] - df["{col}"].mean()) / df["{col}"].std()  # Z-score normalization')

    elif func_name == 'min_max_scale':
        for col in cols:
            lines.append(f'df["{col}"] = (df["{col}"] - df["{col}"].min()) / (df["{col}"].max() - df["{col}"].min())  # Min-max [0, 1]')

    elif func_name == 'one_hot_encode':
        drop_first = params.get('drop_first', False)
        lines.append(f'df = pd.get_dummies(df, columns={cols_repr}, drop_first={drop_first})')

    elif func_name == 'label_encode':
        lines.append('from sklearn.preprocessing import LabelEncoder as _LE')
        for col in cols:
            lines.append(f'df["{col}"] = _LE().fit_transform(df["{col}"].astype(str))')

    elif func_name == 'forward_fill':
        limit = params.get('limit', None)
        for col in cols:
            lines.append(f'df["{col}"] = df["{col}"].ffill(limit={limit})  # Forward fill (time series)')

    elif func_name == 'create_missing_flag':
        suffix = params.get('suffix', '_missing')
        for col in cols:
            lines.append(f'df["{col}{suffix}"] = df["{col}"].isnull().astype(int)')

    elif func_name == 'create_date_features':
        features = params.get('features', ['year', 'month', 'day', 'dayofweek'])
        for col in cols:
            lines.append(f'df["{col}"] = pd.to_datetime(df["{col}"], errors="coerce")')
            if 'year'      in features: lines.append(f'df["{col}_year"]      = df["{col}"].dt.year')
            if 'month'     in features: lines.append(f'df["{col}_month"]     = df["{col}"].dt.month')
            if 'day'       in features: lines.append(f'df["{col}_day"]       = df["{col}"].dt.day')
            if 'dayofweek' in features: lines.append(f'df["{col}_dayofweek"] = df["{col}"].dt.dayofweek')
            if 'hour'      in features: lines.append(f'df["{col}_hour"]      = df["{col}"].dt.hour')

    elif func_name == 'create_interaction':
        op = params.get('operation', 'multiply')
        if len(cols) >= 2:
            col_a, col_b = cols[0], cols[1]
            new_col = f"{col_a}_{col_b}_interaction"
            op_sym = {'multiply': '*', 'add': '+', 'subtract': '-'}.get(op)
            if op_sym:
                lines.append(f'df["{new_col}"] = df["{col_a}"] {op_sym} df["{col_b}"]')
            elif op == 'divide':
                lines.append(f'df["{new_col}"] = df["{col_a}"] / df["{col_b}"].replace(0, np.nan)')

    else:
        lines.append(f'# NOTE: No template for "{func_name}" — implement manually')

    return lines


# ============================================================================
# PHASE 5.1: PARALLEL SIMULATION SUBTASK (one risk-level scenario)
# ============================================================================

@celery_app.task(time_limit=900, max_retries=0)
def validate_plan_task(dataset_name: str, action_subset: list, target: str, goal: str,
                       scenario_name: str, baseline_score: float):
    """
    Phase 5: Validates one simulation scenario concurrently.

    Given an already-filtered action_subset (by risk_level), applies them to
    a fresh copy of the dataset, trains a probe ML model, computes 4-component
    effectiveness sub-scores, and returns full metrics.

    Parameters
    ----------
    action_subset  : list of PDIA action dicts filtered by risk_level
    target         : target column name
    goal           : 'classification' | 'regression'
    scenario_name  : 'conservative' | 'balanced' | 'aggressive'
    baseline_score : ML score on raw (uncleaned) dataset
    """
    try:
        file_path = os.path.join(os.path.dirname(__file__), '..', 'public', dataset_name)
        if not os.path.exists(file_path):
            return {
                "scenario_name": scenario_name, "status": "FAILURE",
                "error": f"Dataset not found: {dataset_name}",
                "effectiveness_score": 0.0, "actions_count": len(action_subset)
            }

        df_raw, _rows_skipped = read_csv_strict(file_path)

        # Load before-profile for sub-score computation
        before_profile_str = redis_cache.get(f"profile:v1:{dataset_name}")
        before_profile = json.loads(before_profile_str) if before_profile_str else {
            "columns": {}, "row_count": len(df_raw), "column_count": len(df_raw.columns)
        }

        # Apply actions using full FUNCTION_REGISTRY
        df_cleaned = _apply_actions_to_df(df_raw, action_subset) if action_subset else df_raw.copy()

        # Guard: target must survive cleaning
        if target not in df_cleaned.columns:
            return {
                "scenario_name": scenario_name, "status": "FAILURE",
                "error": f"Target column '{target}' was removed by {scenario_name} cleaning actions.",
                "actions_count": len(action_subset), "effectiveness_score": 0.0
            }

        # --- ML Validation ---
        ml_result = _run_ml_pipeline(df_cleaned, target, goal)
        ml_score    = ml_result["score"]
        ml_error    = ml_result["error"]
        metric_name = ml_result["metric_name"]

        # --- ML Improvement Score → [0, 1] ---
        # 0.5 = neutral (baseline unchanged), 0.0 = severe regression, 1.0 = major improvement
        if ml_error or not np.isfinite(ml_score) or not np.isfinite(float(baseline_score)):
            ml_improvement_score = 0.5
            raw_delta     = 0.0
            delta_percent = 0.0
            impact_string = f"<b>ML Score Unavailable:</b> {ml_error or 'Baseline invalid'}"
        else:
            raw_delta     = (ml_score - float(baseline_score)) / abs(float(baseline_score)) if baseline_score != 0 else 0.0
            delta_percent = round(raw_delta * 100, 2)
            # Shift so raw_delta=0 → 0.5 (neutral), clamp to [0, 1]
            ml_improvement_score = min(1.0, max(0.0, raw_delta + 0.5))
            sign = "+" if delta_percent >= 0 else ""
            impact_string = f"{metric_name}: {sign}{delta_percent:.2f}% vs. baseline"

        # --- Missing Reduction ---
        before_cols = before_profile.get('columns', {})
        before_missing = sum(int(c.get('missing_count', 0)) for c in before_cols.values())
        before_total   = max(before_profile.get('row_count', 1) * before_profile.get('column_count', 1), 1)
        before_missing_pct = before_missing / before_total

        after_r, after_c = df_cleaned.shape
        after_missing_pct = int(df_cleaned.isnull().sum().sum()) / max(after_r * after_c, 1)

        if before_missing_pct > 0.001:
            missing_reduction_score = min(1.0, max(0.0,
                (before_missing_pct - after_missing_pct) / before_missing_pct))
        else:
            missing_reduction_score = 1.0

        # --- Skew Reduction ---
        skew_reductions = []
        max_before_skew = 0.001
        for col_name, col_info in before_cols.items():
            b_skew = col_info.get('skewness')
            if b_skew is None or col_name not in df_cleaned.columns:
                continue
            try:
                clean_vals = df_cleaned[col_name].dropna()
                if len(clean_vals) > 2 and pd.api.types.is_numeric_dtype(df_cleaned[col_name]):
                    reduction = abs(float(b_skew)) - abs(float(clean_vals.skew()))
                    skew_reductions.append(reduction)
                    max_before_skew = max(max_before_skew, abs(float(b_skew)))
            except Exception:
                continue

        if skew_reductions:
            skew_reduction_score = min(1.0, max(0.0,
                float(np.mean(skew_reductions)) / max(max_before_skew, 2.0)))
        else:
            skew_reduction_score = 0.5  # Neutral

        # --- Leakage Absence ---
        try:
            leakage_warnings_post = detect_data_leakage(df_cleaned.copy(), target)
            leakage_absence_score = 1.0 if not leakage_warnings_post else 0.0
        except Exception:
            leakage_warnings_post = []
            leakage_absence_score = 0.5  # Unknown

        # --- Composite Effectiveness ---
        effectiveness_score = round(
            0.30 * missing_reduction_score +
            0.20 * skew_reduction_score +
            0.40 * ml_improvement_score +
            0.10 * leakage_absence_score,
            4
        )

        return {
            "scenario_name":          scenario_name,
            "status":                 "SUCCESS",
            "actions_count":          len(action_subset),
            "ml_score":               round(float(ml_score), 4) if np.isfinite(ml_score) else None,
            "baseline_score":         round(float(baseline_score), 4) if np.isfinite(float(baseline_score)) else None,
            "delta_percent":          delta_percent,
            "impact_string":          impact_string,
            "metric_name":            metric_name,
            "missing_reduction_score": round(float(missing_reduction_score), 4),
            "skew_reduction_score":   round(float(skew_reduction_score), 4),
            "leakage_absence_score":  float(leakage_absence_score),
            "ml_improvement_score":   round(float(ml_improvement_score), 4),
            "effectiveness_score":    effectiveness_score,
            "leakage_warnings":       leakage_warnings_post,
            "error":                  ml_error
        }

    except Exception as e:
        logger.exception("CRITICAL ERROR in validate_plan_task [%s]: %s", scenario_name, e)
        return {
            "scenario_name":     scenario_name,
            "status":           "FAILURE",
            "error":            str(e),
            "effectiveness_score": 0.0,
            "actions_count":    len(action_subset)
        }


# ============================================================================
# PHASE 5.1: PARENT TASK — DISPATCHES PARALLEL GROUP + STORES TRACKING
# ============================================================================

@celery_app.task(bind=True, time_limit=600)
def run_parallel_simulation_task(self, dataset_name: str, action_backlog: list,
                                  target_variable: str, goal: str):
    """
    Phase 5: Orchestrates parallel plan simulation via Celery group.

    1. Computes baseline ML score on raw dataset (done once in parent, synchronously)
    2. Derives 3 action subsets from backlog risk_level:
         - conservative: risk_level == 'LOW'
         - balanced:     risk_level in ['LOW', 'MEDIUM']
         - aggressive:   all actions
    3. Dispatches group of 3 validate_plan_task subtasks (run in parallel)
    4. Stores subtask IDs in Redis under sim_group:{self.request.id}

    Returns quickly. Frontend polls GET /simulation-status/{job_id}.
    """
    parent_id = self.request.id

    try:
        file_path = os.path.join(os.path.dirname(__file__), '..', 'public', dataset_name)
        if not os.path.exists(file_path):
            return {"status": "FAILURE", "error": f"Dataset not found: {dataset_name}"}

        df_raw, _rows_skipped = read_csv_strict(file_path)

        # 1. Baseline ML score on raw (uncleaned) data
        logger.info("[sim:%s] Computing baseline for %s (%s)...", parent_id[:8], dataset_name, goal)
        baseline_result = _run_ml_pipeline(df_raw, target_variable, goal)
        baseline_score  = baseline_result["score"]
        baseline_error  = baseline_result["error"]

        # Leakage check on raw data
        try:
            leakage_warnings = detect_data_leakage(df_raw.copy(), target_variable)
        except Exception:
            leakage_warnings = []

        # 2. Derive subsets — any action missing risk_level defaults to MEDIUM
        conservative_subset = [
            a for a in action_backlog
            if a.get('risk_level', 'MEDIUM') == 'LOW'
        ]
        balanced_subset = [
            a for a in action_backlog
            if a.get('risk_level', 'MEDIUM') in ('LOW', 'MEDIUM')
        ]
        aggressive_subset = list(action_backlog)  # All actions

        # Normalize baseline_score for JSON serialization
        b_score_serializable = float(baseline_score) if np.isfinite(baseline_score) else None

        logger.info("[sim:%s] Baseline=%s | Conservative=%d, Balanced=%d, Aggressive=%d actions",
                    parent_id[:8], b_score_serializable, len(conservative_subset),
                    len(balanced_subset), len(aggressive_subset))

        # 3. Dispatch parallel Celery group
        job = group([
            validate_plan_task.s(
                dataset_name, conservative_subset, target_variable, goal,
                "conservative", b_score_serializable or 0.0
            ),
            validate_plan_task.s(
                dataset_name, balanced_subset, target_variable, goal,
                "balanced", b_score_serializable or 0.0
            ),
            validate_plan_task.s(
                dataset_name, aggressive_subset, target_variable, goal,
                "aggressive", b_score_serializable or 0.0
            ),
        ])
        group_result = job.apply_async()
        subtask_ids  = [r.id for r in group_result.results]

        # 4. Store tracking in Redis for polling endpoint
        tracking = {
            "parent_id":     parent_id,
            "subtask_ids":   subtask_ids,
            "scenarios":     ["conservative", "balanced", "aggressive"],
            "scenario_sizes": {
                "conservative": len(conservative_subset),
                "balanced":     len(balanced_subset),
                "aggressive":   len(aggressive_subset)
            },
            "baseline_score":  b_score_serializable,
            "baseline_metric": baseline_result.get("metric_name", "Score"),
            "baseline_error":  baseline_error,
            "leakage_warnings": leakage_warnings,
            "dispatched_at":   datetime.now(timezone.utc).isoformat()
        }
        redis_cache.set(
            f"sim_group:{parent_id}",
            json.dumps(tracking, cls=NumpyJSONEncoder),
            ex=3600  # 1-hour TTL
        )

        logger.info("[sim:%s] Group dispatched. Subtask IDs: %s", parent_id[:8], subtask_ids)
        return {"status": "DISPATCHED", "subtask_count": 3}

    except Exception as e:
        logger.exception("CRITICAL ERROR in run_parallel_simulation_task: %s", e)
        return {"status": "FAILURE", "error": str(e)}


# ============================================================================
# PHASE 5.3: CLEANING RECIPE GENERATION
# ============================================================================

@celery_app.task(time_limit=300)
def generate_cleaning_recipe_task(dataset_name: str, applied_actions: list,
                                   before_profile: dict = None):
    """
    Phase 5.3: Generates a production-deployable cleaning recipe JSON containing:
      - source_schema: column type pairs from the before-profile
      - actions: per-action statistical justifications and applied values
      - generated_python: clean Pandas code from templates (NOT LLM-generated)

    Stored in Redis under recipe:{dataset_name} for 24h.
    Frontend downloads via GET /api/dataset/{name}/download-recipe.
    """
    try:
        file_path = os.path.join(os.path.dirname(__file__), '..', 'public', dataset_name)

        # Load the current (post-cleaning) dataset to compute applied values
        df = read_csv_strict(file_path)[0] \
            if os.path.exists(file_path) else pd.DataFrame()

        # Build source schema from before_profile (typing before cleaning)
        source_schema = []
        if before_profile and 'columns' in before_profile:
            for col_name, col_info in before_profile['columns'].items():
                source_schema.append(f"{col_name}:{col_info.get('data_type', 'unknown')}")
        elif not df.empty:
            for col in df.columns:
                if   pd.api.types.is_float_dtype(df[col]):   dt = 'float'
                elif pd.api.types.is_integer_dtype(df[col]): dt = 'integer'
                else:                                          dt = 'categorical'
                source_schema.append(f"{col}:{dt}")

        recipe_actions = []
        python_lines   = [
            "import pandas as pd",
            "import numpy as np",
            "",
            f"# DataCraft Studio — Auto-generated cleaning recipe",
            f"# Dataset : {dataset_name}",
            f"# Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            "",
            f"df = pd.read_csv('{dataset_name}')",
            ""
        ]

        for action in applied_actions:
            func_name   = action.get('function_name', '')
            target_cols = action.get('target_columns') or []
            if not target_cols:
                col_val = action.get('column', '')
                target_cols = [col_val] if isinstance(col_val, str) and col_val else []
            if isinstance(target_cols, str):
                target_cols = [target_cols]

            params = action.get('recommended_params') or action.get('params') or {}

            # Compute applied values (median/mean/mode) from current post-clean df
            applied_values = {}
            for col in target_cols:
                if col not in df.columns:
                    continue
                try:
                    if   func_name == 'impute_median': applied_values[col] = round(float(df[col].median()), 6)
                    elif func_name == 'impute_mean':   applied_values[col] = round(float(df[col].mean()),   6)
                    elif func_name == 'impute_mode':
                        mv = df[col].mode()
                        if not mv.empty: applied_values[col] = mv.iloc[0]
                except Exception:
                    pass

            # Statistical justification from before_profile
            justification_parts = []
            for col in target_cols:
                if before_profile and col in before_profile.get('columns', {}):
                    ci = before_profile['columns'][col]
                    parts = []
                    if ci.get('skewness')     is not None and abs(ci['skewness']) > 0.5:
                        parts.append(f"skewness={ci['skewness']:.3f}")
                    if ci.get('missing_pct',  0) > 0:
                        parts.append(f"missing_pct={ci['missing_pct']:.2f}%")
                    if ci.get('outlier_count') is not None and ci['outlier_count'] > 0:
                        parts.append(f"outlier_count={ci['outlier_count']}")
                    if parts:
                        justification_parts.append(f"{col}: {', '.join(parts)}")

            justification = "; ".join(justification_parts) or "Applied per AI recommendation"

            # Render Python lines from deterministic templates
            code_lines = _render_python_template(func_name, target_cols, params, applied_values)
            python_lines.extend(code_lines)
            python_lines.append("")

            recipe_actions.append({
                "function_name":            func_name,
                "target_columns":           target_cols,
                "params":                   params,
                "statistical_justification": justification,
                "applied_value":            applied_values if applied_values else None
            })

        output_name = dataset_name.replace('.csv', '_cleaned.csv')
        python_lines += [
            f"df.to_csv('{output_name}', index=False)",
            f"print(f'Saved cleaned dataset to {output_name}. Shape: {{df.shape}}')"
        ]

        recipe = {
            "recipe_version":  "1.0",
            "created_at":      datetime.now(timezone.utc).isoformat(),
            "dataset_name":    dataset_name,
            "source_schema":   source_schema,
            "actions_count":   len(recipe_actions),
            "actions":         recipe_actions,
            "generated_python": "\n".join(python_lines)
        }

        redis_cache.set(
            f"recipe:{dataset_name}",
            json.dumps(recipe, cls=NumpyJSONEncoder),
            ex=86400  # 24h TTL
        )

        logger.info("Recipe generated for %s: %d actions, %d non-empty code lines",
                    dataset_name, len(recipe_actions), sum(1 for l in python_lines if l.strip()))
        return {"status": "SUCCESS"}

    except Exception as e:
        logger.exception("ERROR in generate_cleaning_recipe_task for %s: %s", dataset_name, e)
        return {"status": "FAILURE", "error": str(e)}