"""
Column-type detection.

Returns names from the canonical vocabulary in :mod:`column_types`, so that the detector,
the profiler and the action-compatibility table all speak the same language. See
``column_types`` for why this matters -- this module previously emitted ``'date'`` while the
compatibility table only understood ``'datetime'``, which made ``to_datetime`` unusable on
every real date column, and caused ``'text'`` / ``'empty'`` columns to be rejected by every
action.

KNOWN LIMITATION (deliberately out of scope here):
``detect_data_type`` tests for numeric content *before* testing for dates, so a date column
written without separators (``20230510``) is classified as an integer rather than a
datetime. Fixing that needs a stricter date heuristic and a decision about ambiguous
columns, so it is tracked separately rather than bundled into this vocabulary change.
"""

import re

import pandas as pd

from column_types import (
    CATEGORICAL,
    DATETIME,
    EMPTY,
    FLOAT,
    IDENTIFIER,
    INTEGER,
    TEXT,
)

DATE_REGEX = re.compile(r"^\d{1,4}[-/.\s]\d{1,2}[-/.\s]\d{1,4}$")


def is_likely_date_column(series: pd.Series) -> bool:
    """
    Heuristic: is this object-dtype column mostly date-shaped strings?

    Only object dtype is considered. A column pandas has already parsed as datetime does
    not reach here -- :func:`detect_data_type` short-circuits it earlier.
    """
    if not pd.api.types.is_object_dtype(series.dtype):
        return False

    sample = series.dropna().head(20)
    if sample.empty:
        return False

    match_count = sample.astype(str).str.match(DATE_REGEX).sum()
    return (match_count / len(sample)) > 0.75


def detect_data_type(series: pd.Series) -> str:
    """Classify a column into one canonical type from :mod:`column_types`."""
    series_cleaned = series.dropna()

    if series_cleaned.empty:
        return EMPTY

    # A column pandas has already parsed as datetime should be reported as such rather
    # than falling through the object-dtype date heuristic below.
    if pd.api.types.is_datetime64_any_dtype(series_cleaned.dtype):
        return DATETIME

    sample = series_cleaned.head(1000)
    numeric_sample = pd.to_numeric(sample, errors="coerce")
    if numeric_sample.notna().sum() / len(sample) > 0.90:
        try:
            numeric_clean = numeric_sample.dropna()
            if (numeric_clean == numeric_clean.astype(int)).all():
                if numeric_clean.nunique() / len(numeric_clean) > 0.95:
                    return IDENTIFIER
                return INTEGER
            return FLOAT
        except (ValueError, TypeError):
            return FLOAT

    if is_likely_date_column(series_cleaned):
        try:
            pd.to_datetime(sample, errors="raise", format="mixed")
            return DATETIME
        except (ValueError, TypeError, AttributeError):
            pass

    unique_count = series_cleaned.nunique()
    total_count = len(series_cleaned)
    unique_ratio = unique_count / total_count if total_count > 0 else 0

    if unique_ratio > 0.95:
        return IDENTIFIER

    if unique_ratio < 0.5 or unique_count < 50:
        return CATEGORICAL

    return TEXT
