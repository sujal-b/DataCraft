"""
Phase 3: Deterministic Execution Engine
Safe, auditable, transactional execution. No exec(). Full rollback on failure.
"""
import json
import pandas as pd
import numpy as np
from typing import Tuple, List, Dict, Any, Optional
from dataclasses import dataclass, field, asdict
import uuid
from datetime import datetime, timezone
from redis import Redis

from column_types import (
    ACTION_TYPE_COMPATIBILITY,
    describe_action_types,
    infer_type_from_dtype,
    normalize_type,
)


@dataclass
class ExecutionReport:
    """Report generated after each function execution."""
    rows_affected: int = 0
    columns_affected: List[str] = field(default_factory=list)
    values_changed: int = 0
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ValidationResult:
    """Result of validating a single action."""
    action_id: str
    approved: bool
    reason: str = ""
    confirmation_required: bool = False
    confirmation_reason: str = ""
    leakage_protection_flag: bool = False


@dataclass
class ValidationReport:
    """Full validation report for an action list."""
    approved_actions: List[Dict[str, Any]] = field(default_factory=list)
    skipped_actions: List[Dict[str, Any]] = field(default_factory=list)
    confirmation_required_actions: List[Dict[str, Any]] = field(default_factory=list)
    leakage_protected_actions: List[Dict[str, Any]] = field(default_factory=list)


# ============================================================================
# TRANSFORMATION FUNCTIONS
# Each function has signature: fn(df, columns, params) -> (DataFrame, ExecutionReport)
# ============================================================================

def fn_impute_mean(df: pd.DataFrame, columns: List[str], params: Dict[str, Any] = None) -> Tuple[pd.DataFrame, ExecutionReport]:
    """Impute missing values with column mean."""
    report = ExecutionReport()
    df_result = df.copy()
    values_changed = 0

    for col in columns:
        if col not in df_result.columns:
            report.warnings.append(f"Column '{col}' not found, skipping")
            continue
        if not pd.api.types.is_numeric_dtype(df_result[col]):
            report.warnings.append(f"Column '{col}' is not numeric, skipping")
            continue

        original_nulls = df_result[col].isnull().sum()
        mean_val = df_result[col].mean()
        df_result[col] = df_result[col].fillna(mean_val)
        new_nulls = df_result[col].isnull().sum()
        values_changed += int(original_nulls - new_nulls)
        report.rows_affected += int(original_nulls - new_nulls)
        report.columns_affected.append(col)

    report.values_changed = values_changed
    return df_result, report


def fn_impute_median(df: pd.DataFrame, columns: List[str], params: Dict[str, Any] = None) -> Tuple[pd.DataFrame, ExecutionReport]:
    """Impute missing values with column median."""
    report = ExecutionReport()
    df_result = df.copy()
    values_changed = 0

    for col in columns:
        if col not in df_result.columns:
            report.warnings.append(f"Column '{col}' not found, skipping")
            continue
        if not pd.api.types.is_numeric_dtype(df_result[col]):
            report.warnings.append(f"Column '{col}' is not numeric, skipping")
            continue

        original_nulls = df_result[col].isnull().sum()
        median_val = df_result[col].median()
        df_result[col] = df_result[col].fillna(median_val)
        new_nulls = df_result[col].isnull().sum()
        values_changed += int(original_nulls - new_nulls)
        report.rows_affected += int(original_nulls - new_nulls)
        report.columns_affected.append(col)

    report.values_changed = values_changed
    return df_result, report


def fn_impute_mode(df: pd.DataFrame, columns: List[str], params: Dict[str, Any] = None) -> Tuple[pd.DataFrame, ExecutionReport]:
    """Impute missing values with column mode."""
    report = ExecutionReport()
    df_result = df.copy()
    values_changed = 0

    for col in columns:
        if col not in df_result.columns:
            report.warnings.append(f"Column '{col}' not found, skipping")
            continue

        original_nulls = df_result[col].isnull().sum()
        mode_val = df_result[col].mode()
        if len(mode_val) > 0:
            df_result[col] = df_result[col].fillna(mode_val[0])
            new_nulls = df_result[col].isnull().sum()
            values_changed += int(original_nulls - new_nulls)
            report.rows_affected += int(original_nulls - new_nulls)
            report.columns_affected.append(col)
        else:
            report.warnings.append(f"Column '{col}' has no mode value, skipping")

    report.values_changed = values_changed
    return df_result, report


def fn_impute_constant(df: pd.DataFrame, columns: List[str], params: Dict[str, Any] = None) -> Tuple[pd.DataFrame, ExecutionReport]:
    """Impute missing values with a constant value."""
    report = ExecutionReport()
    df_result = df.copy()
    values_changed = 0
    fill_value = params.get('value', 0) if params else 0

    for col in columns:
        if col not in df_result.columns:
            report.warnings.append(f"Column '{col}' not found, skipping")
            continue

        original_nulls = df_result[col].isnull().sum()
        df_result[col] = df_result[col].fillna(fill_value)
        new_nulls = df_result[col].isnull().sum()
        values_changed += int(original_nulls - new_nulls)
        report.rows_affected += int(original_nulls - new_nulls)
        report.columns_affected.append(col)

    report.values_changed = values_changed
    return df_result, report


def fn_forward_fill(df: pd.DataFrame, columns: List[str], params: Dict[str, Any] = None) -> Tuple[pd.DataFrame, ExecutionReport]:
    """Forward fill missing values (for time series)."""
    report = ExecutionReport()
    df_result = df.copy()
    values_changed = 0
    limit = params.get('limit', None) if params else None

    for col in columns:
        if col not in df_result.columns:
            report.warnings.append(f"Column '{col}' not found, skipping")
            continue
        if not pd.api.types.is_numeric_dtype(df_result[col]):
            report.warnings.append(f"Column '{col}' is not numeric, skipping")
            continue

        original_nulls = df_result[col].isnull().sum()
        df_result[col] = df_result[col].ffill(limit=limit)
        new_nulls = df_result[col].isnull().sum()
        values_changed += int(original_nulls - new_nulls)
        report.rows_affected += int(original_nulls - new_nulls)
        report.columns_affected.append(col)

    report.values_changed = values_changed
    return df_result, report


def fn_delete_column(df: pd.DataFrame, columns: List[str], params: Dict[str, Any] = None) -> Tuple[pd.DataFrame, ExecutionReport]:
    """Delete specified columns."""
    report = ExecutionReport()
    df_result = df.copy()

    existing_cols = [col for col in columns if col in df_result.columns]
    missing_cols = [col for col in columns if col not in df_result.columns]

    if missing_cols:
        report.warnings.extend([f"Column '{col}' not found, skipping" for col in missing_cols])

    if existing_cols:
        df_result = df_result.drop(columns=existing_cols)
        report.columns_affected = existing_cols
        report.rows_affected = len(df_result)

    return df_result, report


def fn_drop_na_rows(df: pd.DataFrame, columns: List[str] = None, params: Dict[str, Any] = None) -> Tuple[pd.DataFrame, ExecutionReport]:
    """Drop rows where specified columns (or all columns if none specified) have null values."""
    report = ExecutionReport()
    df_result = df.copy()
    original_rows = len(df_result)

    if columns:
        subset_cols = [col for col in columns if col in df_result.columns]
        missing_cols = [col for col in columns if col not in df_result.columns]
        if missing_cols:
            report.warnings.extend([f"Column '{col}' not found, skipping" for col in missing_cols])
        if not subset_cols:
            report.warnings.append("No valid columns provided for row dropping")
            return df_result, report
    else:
        subset_cols = list(df_result.columns)

    if original_rows == 0:
        return df_result, report

    df_result = df_result.dropna(subset=subset_cols if subset_cols else None)
    rows_dropped = original_rows - len(df_result)

    report.rows_affected = rows_dropped
    report.columns_affected = subset_cols
    report.values_changed = rows_dropped

    if rows_dropped > 0 and original_rows > 0:
        drop_pct = (rows_dropped / original_rows) * 100
        report.warnings.append(f"Dropped {rows_dropped} rows ({drop_pct:.1f}%)")

    return df_result, report


fn_drop_rows_where_null = fn_drop_na_rows


def fn_drop_duplicate_rows(df: pd.DataFrame, columns: List[str] = None, params: Dict[str, Any] = None) -> Tuple[pd.DataFrame, ExecutionReport]:
    """Drop duplicate rows."""
    report = ExecutionReport()
    df_result = df.copy()

    original_rows = len(df_result)
    subset = None
    if columns:
        valid_cols = [c for c in columns if c in df_result.columns]
        missing_cols = [c for c in columns if c not in df_result.columns]
        if missing_cols:
            report.warnings.extend([f"Column '{c}' not found, skipping" for c in missing_cols])
        if valid_cols:
            subset = valid_cols
        elif len(df_result.columns) > 0:
            # All specified columns were missing
            return df_result, report

    df_result = df_result.drop_duplicates(subset=subset)
    duplicates_dropped = original_rows - len(df_result)

    report.rows_affected = duplicates_dropped
    report.values_changed = duplicates_dropped
    if subset:
        report.columns_affected = subset

    if duplicates_dropped > 0:
        report.warnings.append(f"Dropped {duplicates_dropped} duplicate rows")

    return df_result, report


def fn_log_transform(df: pd.DataFrame, columns: List[str], params: Dict[str, Any] = None) -> Tuple[pd.DataFrame, ExecutionReport]:
    """Apply log transformation to numeric columns."""
    report = ExecutionReport()
    df_result = df.copy()
    values_changed = 0
    base = params.get('base', np.e) if params else np.e

    for col in columns:
        if col not in df_result.columns:
            report.warnings.append(f"Column '{col}' not found, skipping")
            continue
        if not pd.api.types.is_numeric_dtype(df_result[col]):
            report.warnings.append(f"Column '{col}' is not numeric, skipping")
            continue

        # Handle non-positive values
        col_data = df_result[col]
        min_val = col_data.min()
        if min_val <= 0:
            offset = abs(min_val) + 1
            col_data = col_data + offset
            report.warnings.append(f"Added offset {offset} to '{col}' to handle non-positive values")

        original_nulls = col_data.isnull().sum()
        if base == np.e:
            df_result[col] = np.log(col_data)
        elif base == 10:
            df_result[col] = np.log10(col_data)
        elif base == 2:
            df_result[col] = np.log2(col_data)
        else:
            df_result[col] = np.log(col_data) / np.log(base)

        new_nulls = df_result[col].isnull().sum()
        values_changed += int(original_nulls - new_nulls)
        report.rows_affected += int(original_nulls - new_nulls)
        report.columns_affected.append(col)

    report.values_changed = values_changed
    return df_result, report


def fn_clip_outliers(df: pd.DataFrame, columns: List[str], params: Dict[str, Any] = None) -> Tuple[pd.DataFrame, ExecutionReport]:
    """Clip outliers using IQR method."""
    report = ExecutionReport()
    df_result = df.copy()
    values_changed = 0
    multiplier = params.get('multiplier', 1.5) if params else 1.5

    for col in columns:
        if col not in df_result.columns:
            report.warnings.append(f"Column '{col}' not found, skipping")
            continue
        if not pd.api.types.is_numeric_dtype(df_result[col]):
            report.warnings.append(f"Column '{col}' is not numeric, skipping")
            continue

        clean_data = df_result[col].dropna()
        if len(clean_data) < 4:
            report.warnings.append(f"Column '{col}' has insufficient data for IQR calculation")
            continue

        q1 = clean_data.quantile(0.25)
        q3 = clean_data.quantile(0.75)
        iqr = q3 - q1
        lower_bound = q1 - multiplier * iqr
        upper_bound = q3 + multiplier * iqr

        original_values = df_result[col].copy()
        df_result[col] = df_result[col].clip(lower=lower_bound, upper=upper_bound)

        clipped_count = ((original_values < lower_bound) | (original_values > upper_bound)).sum()
        values_changed += int(clipped_count)
        report.rows_affected += int(clipped_count)
        report.columns_affected.append(col)

    report.values_changed = values_changed
    return df_result, report


fn_cap_outliers_iqr = fn_clip_outliers


def fn_cap_outliers_zscore(df: pd.DataFrame, columns: List[str], params: Dict[str, Any] = None) -> Tuple[pd.DataFrame, ExecutionReport]:
    """Cap outliers using Z-score method (mean +/- threshold * std)."""
    report = ExecutionReport()
    df_result = df.copy()
    values_changed = 0
    threshold = params.get('threshold', 3.0) if params else 3.0

    for col in columns:
        if col not in df_result.columns:
            report.warnings.append(f"Column '{col}' not found, skipping")
            continue
        if not pd.api.types.is_numeric_dtype(df_result[col]):
            report.warnings.append(f"Column '{col}' is not numeric, skipping")
            continue

        clean_data = df_result[col].dropna()
        if len(clean_data) < 2 or clean_data.std() == 0:
            report.warnings.append(f"Column '{col}' has insufficient variance for Z-score outlier capping")
            continue

        mean_val = clean_data.mean()
        std_val = clean_data.std()
        lower_bound = mean_val - threshold * std_val
        upper_bound = mean_val + threshold * std_val

        original_values = df_result[col].copy()
        df_result[col] = df_result[col].clip(lower=lower_bound, upper=upper_bound)

        clipped_count = int(((original_values < lower_bound) | (original_values > upper_bound)).sum())
        values_changed += clipped_count
        report.rows_affected += clipped_count
        report.columns_affected.append(col)

    report.values_changed = values_changed
    return df_result, report


def fn_remove_outliers_iqr(df: pd.DataFrame, columns: List[str], params: Dict[str, Any] = None) -> Tuple[pd.DataFrame, ExecutionReport]:
    """Remove rows where values are outliers based on IQR bounds."""
    report = ExecutionReport()
    df_result = df.copy()
    multiplier = params.get('multiplier', 1.5) if params else 1.5
    original_rows = len(df_result)

    valid_cols = []
    for col in columns:
        if col not in df_result.columns:
            report.warnings.append(f"Column '{col}' not found, skipping")
            continue
        if not pd.api.types.is_numeric_dtype(df_result[col]):
            report.warnings.append(f"Column '{col}' is not numeric, skipping")
            continue

        clean_data = df_result[col].dropna()
        if len(clean_data) < 4:
            report.warnings.append(f"Column '{col}' has insufficient data for IQR calculation")
            continue

        q1 = clean_data.quantile(0.25)
        q3 = clean_data.quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            report.warnings.append(f"Column '{col}' has zero IQR, skipping")
            continue

        lower_bound = q1 - multiplier * iqr
        upper_bound = q3 + multiplier * iqr

        valid_cols.append(col)
        mask = (df_result[col] >= lower_bound) & (df_result[col] <= upper_bound) | df_result[col].isna()
        df_result = df_result[mask]

    rows_removed = original_rows - len(df_result)
    report.rows_affected = rows_removed
    report.values_changed = rows_removed
    report.columns_affected = valid_cols

    if rows_removed > 0:
        report.warnings.append(f"Removed {rows_removed} outlier rows")

    return df_result, report


def fn_standard_scale(df: pd.DataFrame, columns: List[str], params: Dict[str, Any] = None) -> Tuple[pd.DataFrame, ExecutionReport]:
    """Standard scale (z-score normalization) numeric columns."""
    report = ExecutionReport()
    df_result = df.copy()

    for col in columns:
        if col not in df_result.columns:
            report.warnings.append(f"Column '{col}' not found, skipping")
            continue
        if not pd.api.types.is_numeric_dtype(df_result[col]):
            report.warnings.append(f"Column '{col}' is not numeric, skipping")
            continue

        clean_data = df_result[col].dropna()
        if len(clean_data) < 2 or clean_data.std() == 0:
            report.warnings.append(f"Column '{col}' has insufficient variance for scaling")
            continue

        mean_val = df_result[col].mean()
        std_val = df_result[col].std()
        df_result[col] = (df_result[col] - mean_val) / std_val
        report.columns_affected.append(col)
        report.rows_affected += len(clean_data)

    return df_result, report


def fn_min_max_scale(df: pd.DataFrame, columns: List[str], params: Dict[str, Any] = None) -> Tuple[pd.DataFrame, ExecutionReport]:
    """Min-max scale numeric columns to [0, 1] range."""
    report = ExecutionReport()
    df_result = df.copy()
    feature_range = params.get('feature_range', (0, 1)) if params else (0, 1)

    for col in columns:
        if col not in df_result.columns:
            report.warnings.append(f"Column '{col}' not found, skipping")
            continue
        if not pd.api.types.is_numeric_dtype(df_result[col]):
            report.warnings.append(f"Column '{col}' is not numeric, skipping")
            continue

        clean_data = df_result[col].dropna()
        if len(clean_data) < 2 or clean_data.max() == clean_data.min():
            report.warnings.append(f"Column '{col}' has insufficient variance for scaling")
            continue

        min_val = df_result[col].min()
        max_val = df_result[col].max()
        df_result[col] = (df_result[col] - min_val) / (max_val - min_val)

        # Scale to custom range if needed
        if feature_range != (0, 1):
            df_result[col] = df_result[col] * (feature_range[1] - feature_range[0]) + feature_range[0]

        report.columns_affected.append(col)
        report.rows_affected += len(clean_data)

    return df_result, report


fn_minmax_scale = fn_min_max_scale


def fn_one_hot_encode(df: pd.DataFrame, columns: List[str], params: Dict[str, Any] = None) -> Tuple[pd.DataFrame, ExecutionReport]:
    """One-hot encode categorical columns."""
    report = ExecutionReport()
    df_result = df.copy()
    drop_first = params.get('drop_first', False) if params else False

    new_columns_created = []
    for col in columns:
        if col not in df_result.columns:
            report.warnings.append(f"Column '{col}' not found, skipping")
            continue

        dummies = pd.get_dummies(df_result[col], prefix=col, drop_first=drop_first)
        new_columns_created.extend(dummies.columns.tolist())
        df_result = pd.concat([df_result, dummies], axis=1)
        report.columns_affected.append(col)

    # Drop original columns
    df_result = df_result.drop(columns=columns, errors='ignore')
    report.columns_affected.extend(new_columns_created)
    report.rows_affected = len(df_result)

    return df_result, report


def fn_label_encode(df: pd.DataFrame, columns: List[str], params: Dict[str, Any] = None) -> Tuple[pd.DataFrame, ExecutionReport]:
    """Label encode categorical columns."""
    report = ExecutionReport()
    df_result = df.copy()

    from sklearn.preprocessing import LabelEncoder

    for col in columns:
        if col not in df_result.columns:
            report.warnings.append(f"Column '{col}' not found, skipping")
            continue

        le = LabelEncoder()
        # Handle NaN values by converting to string first
        col_data = df_result[col].astype(str)
        df_result[col] = le.fit_transform(col_data)
        report.columns_affected.append(col)
        report.rows_affected += len(df_result)

    return df_result, report


def fn_create_missing_flag(df: pd.DataFrame, columns: List[str], params: Dict[str, Any] = None) -> Tuple[pd.DataFrame, ExecutionReport]:
    """Create binary flag columns indicating missingness."""
    report = ExecutionReport()
    df_result = df.copy()
    suffix = params.get('suffix', '_missing') if params else '_missing'

    for col in columns:
        if col not in df_result.columns:
            report.warnings.append(f"Column '{col}' not found, skipping")
            continue

        flag_col = f"{col}{suffix}"
        df_result[flag_col] = df_result[col].isnull().astype(int)
        report.columns_affected.append(flag_col)
        report.rows_affected += len(df_result)
        report.warnings.append(f"Created flag column '{flag_col}'")

    return df_result, report


def fn_create_date_features(df: pd.DataFrame, columns: List[str], params: Dict[str, Any] = None) -> Tuple[pd.DataFrame, ExecutionReport]:
    """Create date features from datetime columns."""
    report = ExecutionReport()
    df_result = df.copy()
    features = params.get('features', ['year', 'month', 'day', 'dayofweek']) if params else ['year', 'month', 'day', 'dayofweek']

    for col in columns:
        if col not in df_result.columns:
            report.warnings.append(f"Column '{col}' not found, skipping")
            continue

        try:
            dt_series = pd.to_datetime(df_result[col], errors='coerce')

            if 'year' in features:
                df_result[f"{col}_year"] = dt_series.dt.year
                report.columns_affected.append(f"{col}_year")
            if 'month' in features:
                df_result[f"{col}_month"] = dt_series.dt.month
                report.columns_affected.append(f"{col}_month")
            if 'day' in features:
                df_result[f"{col}_day"] = dt_series.dt.day
                report.columns_affected.append(f"{col}_day")
            if 'dayofweek' in features:
                df_result[f"{col}_dayofweek"] = dt_series.dt.dayofweek
                report.columns_affected.append(f"{col}_dayofweek")
            if 'hour' in features:
                df_result[f"{col}_hour"] = dt_series.dt.hour
                report.columns_affected.append(f"{col}_hour")

            report.rows_affected += len(df_result)
        except Exception as e:
            report.warnings.append(f"Failed to create date features for '{col}': {str(e)}")

    return df_result, report


fn_extract_datetime_features = fn_create_date_features


def fn_to_datetime(df: pd.DataFrame, columns: List[str], params: Dict[str, Any] = None) -> Tuple[pd.DataFrame, ExecutionReport]:
    """Convert specified columns to datetime."""
    report = ExecutionReport()
    df_result = df.copy()
    date_format = params.get('format', None) if params else None

    for col in columns:
        if col not in df_result.columns:
            report.warnings.append(f"Column '{col}' not found, skipping")
            continue

        try:
            df_result[col] = pd.to_datetime(df_result[col], format=date_format, errors='coerce')
            report.columns_affected.append(col)
            report.rows_affected += len(df_result)
        except Exception as e:
            report.warnings.append(f"Failed to convert column '{col}' to datetime: {str(e)}")

    return df_result, report


def fn_create_interaction(df: pd.DataFrame, columns: List[str], params: Dict[str, Any] = None) -> Tuple[pd.DataFrame, ExecutionReport]:
    """Create interaction terms between columns."""
    report = ExecutionReport()
    df_result = df.copy()
    operation = params.get('operation', 'multiply') if params else 'multiply'
    output_suffix = params.get('output_suffix', '_interaction') if params else '_interaction'

    if len(columns) < 2:
        report.warnings.append("Need at least 2 columns to create interaction")
        return df_result, report

    # Check all columns exist and are numeric
    valid_cols = []
    for col in columns:
        if col not in df_result.columns:
            report.warnings.append(f"Column '{col}' not found, skipping")
            continue
        if not pd.api.types.is_numeric_dtype(df_result[col]):
            report.warnings.append(f"Column '{col}' is not numeric, skipping")
            continue
        valid_cols.append(col)

    if len(valid_cols) < 2:
        report.warnings.append("Need at least 2 valid numeric columns to create interaction")
        return df_result, report

    interaction_name = "_".join(valid_cols) + output_suffix

    if operation == 'multiply':
        df_result[interaction_name] = df_result[valid_cols[0]]
        for col in valid_cols[1:]:
            df_result[interaction_name] *= df_result[col]
    elif operation == 'add':
        df_result[interaction_name] = df_result[valid_cols].sum(axis=1)
    elif operation == 'divide' and len(valid_cols) == 2:
        df_result[interaction_name] = df_result[valid_cols[0]] / df_result[valid_cols[1]]
    else:
        report.warnings.append(f"Unknown operation '{operation}', defaulting to multiply")
        df_result[interaction_name] = df_result[valid_cols[0]]
        for col in valid_cols[1:]:
            df_result[interaction_name] *= df_result[col]

    report.columns_affected.append(interaction_name)
    report.rows_affected += len(df_result)

    return df_result, report



def fn_robust_scale(df: pd.DataFrame, columns: List[str], params: Dict[str, Any] = None) -> Tuple[pd.DataFrame, ExecutionReport]:
    """Robust scale using median and IQR — outlier-resistant alternative to standard scaling."""
    report = ExecutionReport()
    df_result = df.copy()

    for col in columns:
        if col not in df_result.columns:
            report.warnings.append(f"Column '{col}' not found, skipping")
            continue
        if not pd.api.types.is_numeric_dtype(df_result[col]):
            report.warnings.append(f"Column '{col}' is not numeric, skipping")
            continue

        clean_data = df_result[col].dropna()
        if len(clean_data) < 4:
            report.warnings.append(f"Column '{col}' has insufficient data for robust scaling")
            continue

        median_val = clean_data.median()
        q1 = clean_data.quantile(0.25)
        q3 = clean_data.quantile(0.75)
        iqr = q3 - q1

        if iqr == 0:
            report.warnings.append(f"Column '{col}' has zero IQR, skipping")
            continue

        df_result[col] = (df_result[col] - median_val) / iqr
        report.columns_affected.append(col)
        report.rows_affected += int(clean_data.notna().sum())

    return df_result, report


def fn_yeo_johnson_transform(df: pd.DataFrame, columns: List[str], params: Dict[str, Any] = None) -> Tuple[pd.DataFrame, ExecutionReport]:
    """Apply Yeo-Johnson power transformation — handles negative values, reduces skew."""
    from scipy.stats import yeojohnson
    report = ExecutionReport()
    df_result = df.copy()
    values_changed = 0

    for col in columns:
        if col not in df_result.columns:
            report.warnings.append(f"Column '{col}' not found, skipping")
            continue
        if not pd.api.types.is_numeric_dtype(df_result[col]):
            report.warnings.append(f"Column '{col}' is not numeric, skipping")
            continue

        clean_data = df_result[col].dropna()
        if len(clean_data) < 4:
            report.warnings.append(f"Column '{col}' has insufficient data for transformation")
            continue

        try:
            non_null_mask = df_result[col].notna()
            transformed, lmbda = yeojohnson(df_result[col][non_null_mask].astype(float))
            df_result.loc[non_null_mask, col] = transformed
            values_changed += int(non_null_mask.sum())
            report.rows_affected += int(non_null_mask.sum())
            report.columns_affected.append(col)
            report.warnings.append(f"Applied Yeo-Johnson transform to '{col}' (lambda={lmbda:.4f})")
        except Exception as e:
            report.warnings.append(f"Yeo-Johnson transform failed for '{col}': {str(e)}")

    report.values_changed = values_changed
    return df_result, report


def fn_winsorize(df: pd.DataFrame, columns: List[str], params: Dict[str, Any] = None) -> Tuple[pd.DataFrame, ExecutionReport]:
    """Winsorize: cap values at chosen percentile bounds — softer than IQR clipping."""
    report = ExecutionReport()
    df_result = df.copy()
    values_changed = 0
    lower_pct = params.get('lower_percentile', 5) if params else 5
    upper_pct = params.get('upper_percentile', 95) if params else 95

    for col in columns:
        if col not in df_result.columns:
            report.warnings.append(f"Column '{col}' not found, skipping")
            continue
        if not pd.api.types.is_numeric_dtype(df_result[col]):
            report.warnings.append(f"Column '{col}' is not numeric, skipping")
            continue

        clean_data = df_result[col].dropna()
        if len(clean_data) < 4:
            report.warnings.append(f"Column '{col}' has insufficient data for winsorizing")
            continue

        lower_bound = clean_data.quantile(lower_pct / 100)
        upper_bound = clean_data.quantile(upper_pct / 100)

        original_values = df_result[col].copy()
        df_result[col] = df_result[col].clip(lower=lower_bound, upper=upper_bound)

        clipped_count = int(((original_values < lower_bound) | (original_values > upper_bound)).sum())
        values_changed += clipped_count
        report.rows_affected += clipped_count
        report.columns_affected.append(col)

    report.values_changed = values_changed
    return df_result, report


def fn_knn_impute(df: pd.DataFrame, columns: List[str], params: Dict[str, Any] = None) -> Tuple[pd.DataFrame, ExecutionReport]:
    """KNN imputation — uses neighbor values from correlated columns, smarter than mean/median."""
    from sklearn.impute import KNNImputer
    report = ExecutionReport()
    df_result = df.copy()
    values_changed = 0
    n_neighbors = params.get('n_neighbors', 5) if params else 5

    # KNN imputer works on all numeric columns simultaneously for best neighbor quality
    numeric_cols = df_result.select_dtypes(include=['number']).columns.tolist()
    target_cols = [col for col in columns if col in df_result.columns and col in numeric_cols]

    if not target_cols:
        report.warnings.append("No valid numeric columns for KNN imputation")
        return df_result, report

    # Count missing before
    missing_before = {col: int(df_result[col].isnull().sum()) for col in target_cols}

    try:
        imputer = KNNImputer(n_neighbors=n_neighbors)
        numeric_df = df_result[numeric_cols].copy()
        imputed_array = imputer.fit_transform(numeric_df)
        imputed_df = pd.DataFrame(imputed_array, columns=numeric_cols, index=df_result.index)

        for col in target_cols:
            if missing_before[col] > 0:
                df_result[col] = imputed_df[col]
                values_changed += missing_before[col]
                report.rows_affected += missing_before[col]
                report.columns_affected.append(col)

        report.values_changed = values_changed
    except Exception as e:
        report.warnings.append(f"KNN imputation failed: {str(e)}")

    return df_result, report


# ============================================================================
# FUNCTION REGISTRY
# ============================================================================

FUNCTION_REGISTRY = {
    "impute_mean": fn_impute_mean,
    "impute_median": fn_impute_median,
    "impute_mode": fn_impute_mode,
    "impute_constant": fn_impute_constant,
    "forward_fill": fn_forward_fill,
    "delete_column": fn_delete_column,
    "drop_rows_where_null": fn_drop_rows_where_null,
    "drop_na_rows": fn_drop_na_rows,
    "drop_duplicate_rows": fn_drop_duplicate_rows,
    "log_transform": fn_log_transform,
    "clip_outliers": fn_clip_outliers,
    "cap_outliers_iqr": fn_cap_outliers_iqr,
    "cap_outliers_zscore": fn_cap_outliers_zscore,
    "remove_outliers_iqr": fn_remove_outliers_iqr,
    "standard_scale": fn_standard_scale,
    "min_max_scale": fn_min_max_scale,
    "minmax_scale": fn_minmax_scale,
    "one_hot_encode": fn_one_hot_encode,
    "label_encode": fn_label_encode,
    "to_datetime": fn_to_datetime,
    "create_date_features": fn_create_date_features,
    "extract_datetime_features": fn_extract_datetime_features,
    "create_missing_flag": fn_create_missing_flag,
    "create_interaction": fn_create_interaction,
    "robust_scale": fn_robust_scale,
    "yeo_johnson_transform": fn_yeo_johnson_transform,
    "winsorize": fn_winsorize,
    "knn_impute": fn_knn_impute
}


# Type compatibility mapping
TYPE_COMPATIBILITY = {
    "impute_mean": ["integer", "float"],
    "impute_median": ["integer", "float"],
    "impute_constant": ["integer", "float", "categorical", "identifier"],
    "forward_fill": ["integer", "float"],  # Special handling for is_time_series check elsewhere
    "log_transform": ["integer", "float"],
    "clip_outliers": ["integer", "float"],
    "cap_outliers_iqr": ["integer", "float"],
    "cap_outliers_zscore": ["integer", "float"],
    "remove_outliers_iqr": ["integer", "float"],
    "standard_scale": ["integer", "float"],
    "min_max_scale": ["integer", "float"],
    "minmax_scale": ["integer", "float"],
    "one_hot_encode": ["categorical"],
    "label_encode": ["categorical"],
    "to_datetime": ["integer", "float", "categorical", "identifier", "datetime"],
    "impute_mode": ["integer", "float", "categorical", "identifier"],
    "create_missing_flag": ["integer", "float", "categorical", "identifier"],
    "delete_column": ["integer", "float", "categorical", "identifier"],
    "drop_rows_where_null": ["integer", "float", "categorical", "identifier"],
    "drop_na_rows": ["integer", "float", "categorical", "identifier"],
    "drop_duplicate_rows": ["integer", "float", "categorical", "identifier"],
    "create_date_features": ["integer", "float", "categorical", "identifier"],  # Will be converted to datetime
    "extract_datetime_features": ["integer", "float", "categorical", "identifier"],
    "create_interaction": ["integer", "float"],
    "robust_scale": ["integer", "float"],
    "yeo_johnson_transform": ["integer", "float"],
    "winsorize": ["integer", "float"],
    "knn_impute": ["integer", "float"]
}


def validate_plan(actions: List[Dict[str, Any]], df: pd.DataFrame, profile_data: Optional[Dict[str, Any]] = None) -> ValidationReport:
    """
    Validate the full action list before execution.

    For each action:
    1. function_name in FUNCTION_REGISTRY → else: SKIP + log "unknown function"
    2. each column in target_columns exists in df → else: SKIP + log "column not found: {col}"
    3. column dtype compatible with function → else: SKIP + log "type mismatch: {fn} on {dtype}"
    4. if action would drop rows: compute percentage → if > 40%: flag REQUIRES_CONFIRMATION
    5. if action is delete_column on leakage_risk > 0.8 column: flag LEAKAGE_PROTECTION

    Returns ValidationReport with approved, skipped, and confirmation-required actions.
    """
    result = ValidationReport()

    for action in actions:
        action_id = action.get("action_id", "unknown")
        function_name = action.get("function_name", "")
        target_columns = action.get("target_columns", []) or action.get("column", [])
        if isinstance(target_columns, str):
            target_columns = [target_columns]

        validation = ValidationResult(action_id=action_id, approved=True)

        # 1. Check function exists
        if function_name not in FUNCTION_REGISTRY:
            validation.approved = False
            validation.reason = f"Unknown function: {function_name}"
            result.skipped_actions.append({**action, "skip_reason": validation.reason})
            continue

        # 2. Check columns exist
        missing_cols = [col for col in target_columns if col not in df.columns]
        if missing_cols:
            validation.approved = False
            validation.reason = f"Column(s) not found: {', '.join(missing_cols)}"
            result.skipped_actions.append({**action, "skip_reason": validation.reason})
            continue

        # 3. Check type compatibility
        compatible_types = TYPE_COMPATIBILITY.get(function_name, [])
        if compatible_types and target_columns:
            for col in target_columns:
                col_type = _get_column_type(df, col, profile_data)
                if col_type not in compatible_types:
                    # Special case: forward_fill requires is_time_series
                    if function_name == "forward_fill":
                        is_ts = _is_time_series(col, profile_data)
                        if not is_ts:
                            validation.approved = False
                            validation.reason = f"forward_fill requires is_time_series=true for column '{col}'"
                            break

                    if col_type not in compatible_types:
                        validation.approved = False
                        validation.reason = f"Type mismatch: {function_name} requires {compatible_types}, but '{col}' is {col_type}"
                        break

            if not validation.approved:
                result.skipped_actions.append({**action, "skip_reason": validation.reason})
                continue

        # 4. Check row drop percentage
        if function_name == "drop_rows_where_null":
            null_counts = df[target_columns].isnull().sum()
            rows_with_null = (df[target_columns].isnull().any(axis=1)).sum()
            drop_pct = (rows_with_null / len(df)) * 100 if len(df) > 0 else 0

            if drop_pct > 40:
                validation.confirmation_required = True
                validation.confirmation_reason = f"This action will drop {rows_with_null} rows ({drop_pct:.1f}%), exceeding 40% threshold"

        if function_name == "delete_column" and len(target_columns) > 0:
            # Check if deleting many columns
            if len(target_columns) > len(df.columns) * 0.3:
                validation.confirmation_required = True
                validation.confirmation_reason = f"Deleting {len(target_columns)} columns ({len(target_columns)/len(df.columns)*100:.1f}% of all columns)"

        # 5. Check leakage protection
        if function_name == "delete_column" and profile_data:
            columns_profile = profile_data.get("columns", {})
            for col in target_columns:
                col_profile = columns_profile.get(col, {})
                leakage_risk = col_profile.get("leakage_risk_score", 0) or 0
                if leakage_risk > 0.8:
                    validation.leakage_protection_flag = True
                    result.leakage_protected_actions.append({
                        **action,
                        "leakage_risk_score": leakage_risk,
                        "warning": f"Column '{col}' has high leakage risk ({leakage_risk:.2f}). Deletion may remove important predictive signal."
                    })

        # Add to appropriate list
        if validation.confirmation_required:
            result.confirmation_required_actions.append({**action, "confirmation_reason": validation.confirmation_reason})
        else:
            result.approved_actions.append(action)

    return result


def _get_column_type(df: pd.DataFrame, col: str, profile_data: Optional[Dict[str, Any]] = None) -> str:
    """Get column type from profile or infer from dtype."""
    if profile_data and "columns" in profile_data:
        col_profile = profile_data["columns"].get(col, {})
        if col_profile.get("data_type"):
            return col_profile["data_type"]

    dtype = df[col].dtype
    if pd.api.types.is_integer_dtype(dtype):
        return "integer"
    elif pd.api.types.is_float_dtype(dtype):
        return "float"
    elif pd.api.types.is_datetime64_any_dtype(dtype):
        return "datetime"
    else:
        return "categorical"


def _is_time_series(col: str, profile_data: Optional[Dict[str, Any]] = None) -> bool:
    """Check if column is marked as time series in profile."""
    if profile_data and "columns" in profile_data:
        col_profile = profile_data["columns"].get(col, {})
        return col_profile.get("is_time_series", False)
    return False


def execute_transactionally(
    df: pd.DataFrame,
    approved_actions: List[Dict[str, Any]],
    dataset_name: str,
    profile_data: Optional[Dict[str, Any]] = None,
    redis_client: Optional[Redis] = None
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Execute actions transactionally with full rollback on failure.

    Process:
    1. df_snapshot = df.copy()  # rollback point
    2. execution_log = []
    3. for action in approved_actions:
         try:
           df, report = FUNCTION_REGISTRY[action.function_name](df, action.columns, action.params)
           execution_log.append({action_id, status: SUCCESS, report})
         except Exception as e:
           execution_log.append({action_id, status: FAILED, error: str(e)})
           df = df_snapshot  # full rollback
           break
    4. if all success:
         write df to csv
         dispatch profile_dataset task (background re-profile)
         store audit entry

    Returns: (final_dataframe, execution_summary)
    """
    df_snapshot = df.copy()
    execution_log = []
    rows_before = len(df)
    columns_before = len(df.columns)

    source_profile_id = profile_data.get("profile_id") if profile_data else None

    try:
        for action in approved_actions:
            action_id = action.get("action_id", "unknown")
            function_name = action.get("function_name", "")
            target_columns = action.get("target_columns", []) or action.get("column", [])
            if isinstance(target_columns, str):
                target_columns = [target_columns]
            params = action.get("recommended_params", {}) or action.get("params", {})

            if function_name not in FUNCTION_REGISTRY:
                execution_log.append({
                    "action_id": action_id,
                    "status": "FAILED",
                    "error": f"Unknown function: {function_name}"
                })
                break

            try:
                df, report = FUNCTION_REGISTRY[function_name](df, target_columns, params)
                execution_log.append({
                    "action_id": action_id,
                    "status": "SUCCESS",
                    "report": report.to_dict()
                })
            except Exception as e:
                execution_log.append({
                    "action_id": action_id,
                    "status": "FAILED",
                    "error": str(e)
                })
                # Full rollback
                df = df_snapshot
                break

        # Check if all actions succeeded
        all_success = all(log["status"] == "SUCCESS" for log in execution_log)

        if all_success and len(execution_log) > 0:
            rows_after = len(df)
            columns_after = len(df.columns)

            execution_summary = {
                "execution_id": str(uuid.uuid4()),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "plan_source": "ai_backlog",
                "actions_applied": [log["action_id"] for log in execution_log],
                "actions_skipped": [],
                "rows_before": rows_before,
                "rows_after": rows_after,
                "columns_before": columns_before,
                "columns_after": columns_after,
                "source_profile_id": source_profile_id,
                "result_profile_id": None,  # Will be set after re-profiling
                "applied_by": "user",
                "execution_log": execution_log
            }

            # Store audit trail
            if redis_client:
                audit_key = f"audit:{dataset_name}"
                redis_client.rpush(audit_key, json.dumps(execution_summary))
                # Keep only last 100 audit entries, expire after 30 days (P1-7)
                redis_client.ltrim(audit_key, -100, -1)
                redis_client.expire(audit_key, 60 * 60 * 24 * 30)

            return df, execution_summary
        else:
            # Rollback occurred
            execution_summary = {
                "execution_id": str(uuid.uuid4()),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "plan_source": "ai_backlog",
                "actions_applied": [],
                "actions_skipped": [log["action_id"] for log in execution_log],
                "rows_before": rows_before,
                "rows_after": rows_before,  # No change due to rollback
                "columns_before": columns_before,
                "columns_after": columns_before,
                "source_profile_id": source_profile_id,
                "result_profile_id": None,
                "applied_by": "user",
                "execution_log": execution_log,
                "rollback_performed": True
            }

            if redis_client:
                audit_key = f"audit:{dataset_name}"
                redis_client.rpush(audit_key, json.dumps(execution_summary))
                redis_client.ltrim(audit_key, -100, -1)

            return df_snapshot, execution_summary

    except Exception as e:
        # Catch-all rollback
        df = df_snapshot
        execution_summary = {
            "execution_id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "plan_source": "ai_backlog",
            "actions_applied": [],
            "actions_skipped": [a.get("action_id", "unknown") for a in approved_actions],
            "rows_before": rows_before,
            "rows_after": rows_before,
            "columns_before": columns_before,
            "columns_after": columns_before,
            "source_profile_id": source_profile_id,
            "result_profile_id": None,
            "applied_by": "user",
            "execution_log": execution_log,
            "rollback_performed": True,
            "critical_error": str(e)
        }

        if redis_client:
            audit_key = f"audit:{dataset_name}"
            redis_client.rpush(audit_key, json.dumps(execution_summary))
            redis_client.ltrim(audit_key, -100, -1)
            redis_client.expire(audit_key, 60 * 60 * 24 * 30)  # P1-7

        return df_snapshot, execution_summary