"""
Canonical column-type vocabulary.

WHY THIS MODULE EXISTS
----------------------
Column types were previously produced by two independent oracles with two different
vocabularies, and consumed by a third that understood neither of them fully:

  1. ``data_type_detector.detect_data_type()``
     -> integer | float | identifier | date | categorical | text | empty
  2. ``execution_engine._get_column_type()``
     -> integer | float | datetime | categorical
  3. ``execution_engine.TYPE_COMPATIBILITY``
     -> integer | float | categorical | identifier | datetime

The detector never emits ``datetime``; the compatibility table never lists ``date``,
``text`` or ``empty``. The concrete, user-visible consequences were:

  * ``to_datetime`` could never run on a real date column. The detector labelled such a
    column ``date``, and ``date`` was absent from the compatibility list, so the one action
    built for dates rejected every date column it was meant to fix.
  * Any column labelled ``text`` or ``empty`` was rejected by *every* action, because
    neither string appeared in any compatibility list at all.
  * The ``datetime`` entry in the compatibility table was unreachable in production,
    because it could only be produced by the dtype fallback, which the profiler normally
    bypasses.

This module replaces that arrangement with a single source of truth:

  * one closed set of canonical type names (:data:`CANONICAL_TYPES`),
  * one normaliser that absorbs legacy aliases and junk (:func:`normalize_type`),
  * one compatibility table that is **total** -- every action declares an opinion about
    every type, so no type can be silently rejected everywhere (:data:`ACTION_TYPE_COMPATIBILITY`).

The table's totality is not enforced by convention; it is enforced by
``tests/test_column_types.py``, which fails if an action in ``FUNCTION_REGISTRY`` is
missing an entry or if any entry omits a canonical type.

FAIL-SAFE DIRECTION
-------------------
Anything unrecognised normalises to :data:`TEXT`, and :data:`TEXT` is permitted for
type-agnostic actions while being rejected by every numeric-only action. An unknown type
therefore degrades to "generic operations allowed, risky statistical operations blocked",
which is the safe direction to fail in.
"""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, Iterable, Tuple

import pandas as pd

# --- Canonical vocabulary ----------------------------------------------------

INTEGER = "integer"
FLOAT = "float"
IDENTIFIER = "identifier"
DATETIME = "datetime"
CATEGORICAL = "categorical"
TEXT = "text"
EMPTY = "empty"

CANONICAL_TYPES: FrozenSet[str] = frozenset(
    {INTEGER, FLOAT, IDENTIFIER, DATETIME, CATEGORICAL, TEXT, EMPTY}
)

#: Type names that have appeared in stored profiles, cached payloads, LLM output or
#: dtype introspection. Mapped onto the canonical vocabulary so that historical data
#: does not need migrating.
LEGACY_ALIASES: Dict[str, str] = {
    # datetime family
    "date": DATETIME,
    "datetime64": DATETIME,
    "datetime64[ns]": DATETIME,
    "timestamp": DATETIME,
    "time": DATETIME,
    # numeric family
    "int": INTEGER,
    "int64": INTEGER,
    "int32": INTEGER,
    "integer64": INTEGER,
    "float64": FLOAT,
    "float32": FLOAT,
    "double": FLOAT,
    "numeric": FLOAT,
    "number": FLOAT,
    "continuous": FLOAT,
    # identifier family
    "id": IDENTIFIER,
    "unique": IDENTIFIER,
    # categorical / text family
    "string": TEXT,
    "str": TEXT,
    "object": TEXT,
    "textual": TEXT,
    "free_text": TEXT,
    "unknown": TEXT,
    "none": TEXT,
    "null": TEXT,
    "nan": TEXT,
    # empty family
    "all_null": EMPTY,
    "all_na": EMPTY,
}


def normalize_type(value: Any) -> str:
    """
    Coerce any historical or third-party type label to a canonical type name.

    Unrecognised input becomes :data:`TEXT`, which is the permissive-for-safe-actions,
    restrictive-for-risky-actions default. ``None`` and blank strings do the same.
    """
    if value is None:
        return TEXT
    key = str(value).strip().lower()
    if not key:
        return TEXT
    if key in CANONICAL_TYPES:
        return key
    return LEGACY_ALIASES.get(key, TEXT)


def infer_type_from_dtype(dtype: Any) -> str:
    """
    Infer a canonical type from a pandas dtype, for callers with no profile available.

    Boolean columns map to :data:`INTEGER` because they are already stored as 0/1 and
    numeric-only transforms are valid on them. This preserves the pre-existing behaviour
    of the detector rather than introducing a new ``boolean`` type that every action
    would then have to handle.
    """
    try:
        if pd.api.types.is_bool_dtype(dtype):
            return INTEGER
        if pd.api.types.is_integer_dtype(dtype):
            return INTEGER
        if pd.api.types.is_float_dtype(dtype):
            return FLOAT
        if pd.api.types.is_datetime64_any_dtype(dtype):
            return DATETIME
        if pd.api.types.is_numeric_dtype(dtype):
            return FLOAT
    except (TypeError, AttributeError):  # pragma: no cover - defensive
        return TEXT
    return CATEGORICAL


# --- Action compatibility ----------------------------------------------------

_NUMERIC: Tuple[str, ...] = (INTEGER, FLOAT)

#: Free-text is treated as categorical-like for encoding purposes.
_CATEGORICAL_LIKE: Tuple[str, ...] = (CATEGORICAL, TEXT)

#: Anything a date can plausibly be parsed out of.
_DATETIME_LIKE: Tuple[str, ...] = (DATETIME, INTEGER, FLOAT, CATEGORICAL, TEXT, IDENTIFIER)

#: Type-agnostic operations. Safe on any column, including all-null ones.
_ANY: Tuple[str, ...] = tuple(sorted(CANONICAL_TYPES))

#: Deliberately excludes EMPTY: there is nothing to fill or scale in an all-null column.
_ANY_FILLABLE: Tuple[str, ...] = (INTEGER, FLOAT, IDENTIFIER, DATETIME, CATEGORICAL, TEXT)

#: Numeric plus datetimes -- a time-ordered column of either kind can be carried forward.
_FORWARD_FILLABLE: Tuple[str, ...] = (INTEGER, FLOAT, DATETIME)

#: ``one_hot_encode`` deliberately excludes IDENTIFIER: one-hot encoding a near-unique
#: identifier produces one column per row, which is never what the user wants.
#: ``label_encode`` permits it, because factorising an identifier is a legitimate step.
_ENCODABLE_ONE_HOT: Tuple[str, ...] = _CATEGORICAL_LIKE
_ENCODABLE_LABEL: Tuple[str, ...] = _CATEGORICAL_LIKE + (IDENTIFIER,)


ACTION_TYPE_COMPATIBILITY: Dict[str, Tuple[str, ...]] = {
    # --- numeric-only statistical transforms ---
    "impute_mean": _NUMERIC,
    "impute_median": _NUMERIC,
    "log_transform": _NUMERIC,
    "clip_outliers": _NUMERIC,
    "cap_outliers_iqr": _NUMERIC,
    "cap_outliers_zscore": _NUMERIC,
    "remove_outliers_iqr": _NUMERIC,
    "standard_scale": _NUMERIC,
    "min_max_scale": _NUMERIC,
    "minmax_scale": _NUMERIC,
    "robust_scale": _NUMERIC,
    "yeo_johnson_transform": _NUMERIC,
    "winsorize": _NUMERIC,
    "knn_impute": _NUMERIC,
    "create_interaction": _NUMERIC,
    # --- temporal ---
    "forward_fill": _FORWARD_FILLABLE,
    "to_datetime": _DATETIME_LIKE,
    "create_date_features": _DATETIME_LIKE,
    "extract_datetime_features": _DATETIME_LIKE,
    # --- categorical encoders ---
    "one_hot_encode": _ENCODABLE_ONE_HOT,
    "label_encode": _ENCODABLE_LABEL,
    # --- type-agnostic ---
    "impute_constant": _ANY_FILLABLE,
    "impute_mode": _ANY_FILLABLE,
    "create_missing_flag": _ANY,
    "delete_column": _ANY,
    "drop_rows_where_null": _ANY,
    "drop_na_rows": _ANY,
    "drop_duplicate_rows": _ANY,
}


def action_accepts(action_name: str, column_type: Any) -> bool:
    """
    Return whether ``action_name`` may be applied to a column of ``column_type``.

    Unknown actions fail closed (``False``). Callers are expected to have validated the
    action name against ``FUNCTION_REGISTRY`` first; this is defence in depth.
    """
    allowed: Iterable[str] | None = ACTION_TYPE_COMPATIBILITY.get(action_name)
    if allowed is None:
        return False
    return normalize_type(column_type) in allowed


def describe_action_types(action_name: str) -> str:
    """Human-readable list of accepted types, for validation messages."""
    allowed = ACTION_TYPE_COMPATIBILITY.get(action_name)
    if not allowed:
        return "no known column types"
    return ", ".join(sorted(allowed))
