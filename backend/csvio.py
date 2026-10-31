"""
CSV ingestion helper (P1-10).

A data-quality product must never silently drop malformed rows. pandas'
`on_bad_lines='skip'` discards them invisibly; `on_bad_lines='error'` fails the
whole file. Strategy here:

1. Try a strict read (C engine, fast path). Most files parse cleanly.
2. On ParserError, fall back to the python engine with a counting callback so
   we still get a DataFrame AND an exact count of skipped rows to surface
   upstream (profile field `rows_skipped`, UI banner).
"""
from typing import Tuple
import urllib.parse

import pandas as pd


def read_csv_strict(file_path: str, **kwargs) -> Tuple[pd.DataFrame, int]:
    """
    Returns (df, rows_skipped). rows_skipped > 0 means malformed lines were
    dropped by the parser fallback and MUST be surfaced to the user.
    """
    kwargs.setdefault("low_memory", False)
    try:
        return pd.read_csv(file_path, on_bad_lines="error", **kwargs), 0
    except pd.errors.ParserError:
        skipped: list[int] = []

        def _count_bad_line(_bad_line):
            skipped.append(1)
            return None  # skip the line; pandas keeps the rest

        df = pd.read_csv(
            file_path,
            on_bad_lines=_count_bad_line,
            engine="python",
            **{k: v for k, v in kwargs.items() if k != "low_memory"},
        )
        return df, sum(skipped)


def parse_warnings_message(dataset_name: str, rows_skipped: int) -> str:
    safe = urllib.parse.quote(dataset_name)
    return (
        f"{rows_skipped} malformed row(s) were skipped while reading '{safe}'. "
        "The profile covers only the parseable rows."
    )
