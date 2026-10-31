import os
import tempfile
import pandas as pd
import pytest

from csvio import read_csv_strict


def test_clean_csv_returns_df_and_zero_skipped():
    with tempfile.TemporaryDirectory() as tmp_dir:
        csv_file = os.path.join(tmp_dir, "clean.csv")
        with open(csv_file, "w", encoding="utf-8") as f:
            f.write("col_a,col_b,col_c\n1,2,3\n4,5,6\n")

        df, skipped = read_csv_strict(csv_file)

        assert isinstance(df, pd.DataFrame)
        assert skipped == 0
        assert len(df) == 2
        assert list(df.columns) == ["col_a", "col_b", "col_c"]


def test_csv_with_bad_lines_returns_df_and_skipped_count():
    with tempfile.TemporaryDirectory() as tmp_dir:
        csv_file = os.path.join(tmp_dir, "bad_lines.csv")
        # Header: 3 cols. Row 1: 3 cols. Row 2: 5 cols (bad line). Row 3: 3 cols.
        content = "col_a,col_b,col_c\n1,2,3\n4,5,6,7,extra\n8,9,10\n"
        with open(csv_file, "w", encoding="utf-8") as f:
            f.write(content)

        df, skipped = read_csv_strict(csv_file)

        assert isinstance(df, pd.DataFrame)
        assert skipped > 0
        assert skipped == 1
        assert len(df) == 2
