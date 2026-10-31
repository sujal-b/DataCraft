import pytest
import pandas as pd
import numpy as np
from execution_engine import FUNCTION_REGISTRY, execute_transactionally, ExecutionReport


# ============================================================================
# 1. FUNCTION_REGISTRY REGISTRATION TESTS
# ============================================================================

REQUIRED_REGISTRY_FUNCTIONS = [
    "impute_mean",
    "impute_median",
    "impute_mode",
    "impute_constant",
    "drop_na_rows",
    "drop_duplicate_rows",
    "delete_column",
    "standard_scale",
    "minmax_scale",
    "robust_scale",
    "cap_outliers_iqr",
    "cap_outliers_zscore",
    "remove_outliers_iqr",
    "one_hot_encode",
    "label_encode",
    "to_datetime",
    "extract_datetime_features",
]


@pytest.mark.parametrize("func_name", REQUIRED_REGISTRY_FUNCTIONS)
def test_function_registry_contains_required_functions(func_name):
    """Ensure every required function is present in FUNCTION_REGISTRY and callable."""
    assert func_name in FUNCTION_REGISTRY, f"'{func_name}' not found in FUNCTION_REGISTRY"
    assert callable(FUNCTION_REGISTRY[func_name]), f"FUNCTION_REGISTRY['{func_name}'] is not callable"


# ============================================================================
# 2. IMPUTATION TESTS
# ============================================================================

def test_impute_mean():
    df = pd.DataFrame({"a": [10.0, 20.0, np.nan, 30.0]})
    res_df, report = FUNCTION_REGISTRY["impute_mean"](df, ["a"], {})
    assert res_df["a"].isnull().sum() == 0
    assert res_df.loc[2, "a"] == 20.0
    assert report.rows_affected == 1
    assert report.values_changed == 1
    assert "a" in report.columns_affected


def test_impute_median():
    df = pd.DataFrame({"a": [1.0, 2.0, 100.0, np.nan]})
    res_df, report = FUNCTION_REGISTRY["impute_median"](df, ["a"], {})
    assert res_df["a"].isnull().sum() == 0
    assert res_df.loc[3, "a"] == 2.0
    assert report.rows_affected == 1
    assert report.values_changed == 1


def test_impute_mode():
    df = pd.DataFrame({"cat": ["apple", "banana", "apple", None]})
    res_df, report = FUNCTION_REGISTRY["impute_mode"](df, ["cat"], {})
    assert res_df["cat"].isnull().sum() == 0
    assert res_df.loc[3, "cat"] == "apple"
    assert report.rows_affected == 1


def test_impute_constant():
    df = pd.DataFrame({"val": [1.0, np.nan, 3.0]})
    res_df, report = FUNCTION_REGISTRY["impute_constant"](df, ["val"], {"value": -999.0})
    assert res_df["val"].isnull().sum() == 0
    assert res_df.loc[1, "val"] == -999.0
    assert report.rows_affected == 1


# ============================================================================
# 3. ROW & COLUMN DELETION TESTS
# ============================================================================

def test_drop_na_rows():
    df = pd.DataFrame({
        "a": [1.0, 2.0, np.nan, 4.0],
        "b": [10.0, 20.0, 30.0, 40.0]
    })
    # Target specific column
    res_df, report = FUNCTION_REGISTRY["drop_na_rows"](df, ["a"], {})
    assert len(res_df) == 3
    assert report.rows_affected == 1
    assert 2 not in res_df.index

    # All columns when none specified
    df2 = pd.DataFrame({"a": [1.0, np.nan], "b": [np.nan, 2.0]})
    res_df2, report2 = FUNCTION_REGISTRY["drop_na_rows"](df2, [], {})
    assert len(res_df2) == 0
    assert report2.rows_affected == 2


def test_drop_duplicate_rows():
    df = pd.DataFrame({
        "a": [1, 2, 2, 3],
        "b": ["x", "y", "y", "z"]
    })
    res_df, report = FUNCTION_REGISTRY["drop_duplicate_rows"](df, ["a", "b"], {})
    assert len(res_df) == 3
    assert report.rows_affected == 1
    assert report.values_changed == 1


def test_delete_column():
    df = pd.DataFrame({"col_a": [1, 2], "col_b": [3, 4], "col_c": [5, 6]})
    res_df, report = FUNCTION_REGISTRY["delete_column"](df, ["col_b"], {})
    assert "col_b" not in res_df.columns
    assert list(res_df.columns) == ["col_a", "col_c"]
    assert report.columns_affected == ["col_b"]


# ============================================================================
# 4. SCALING TESTS
# ============================================================================

def test_standard_scale():
    df = pd.DataFrame({"num": [10.0, 20.0, 30.0, 40.0, 50.0]})
    res_df, report = FUNCTION_REGISTRY["standard_scale"](df, ["num"], {})
    assert pytest.approx(res_df["num"].mean(), abs=1e-6) == 0.0
    assert pytest.approx(res_df["num"].std(), abs=1e-6) == 1.0
    assert report.columns_affected == ["num"]


def test_minmax_scale():
    df = pd.DataFrame({"num": [10.0, 20.0, 30.0, 40.0, 50.0]})
    res_df, report = FUNCTION_REGISTRY["minmax_scale"](df, ["num"], {})
    assert pytest.approx(res_df["num"].min(), abs=1e-6) == 0.0
    assert pytest.approx(res_df["num"].max(), abs=1e-6) == 1.0
    assert report.columns_affected == ["num"]


def test_robust_scale():
    df = pd.DataFrame({"num": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 100.0]})
    res_df, report = FUNCTION_REGISTRY["robust_scale"](df, ["num"], {})
    assert report.columns_affected == ["num"]
    # Median should become 0
    assert pytest.approx(res_df["num"].median(), abs=1e-6) == 0.0


# ============================================================================
# 5. OUTLIER HANDLING TESTS
# ============================================================================

def test_cap_outliers_iqr():
    df = pd.DataFrame({"num": [10.0, 11.0, 12.0, 10.0, 11.0, 12.0, 100.0, -50.0]})
    res_df, report = FUNCTION_REGISTRY["cap_outliers_iqr"](df, ["num"], {"multiplier": 1.5})
    assert report.values_changed >= 2
    assert res_df["num"].max() < 100.0
    assert res_df["num"].min() > -50.0


def test_cap_outliers_zscore():
    data = [0.0] * 50 + [1000.0]
    df = pd.DataFrame({"num": data})
    res_df, report = FUNCTION_REGISTRY["cap_outliers_zscore"](df, ["num"], {"threshold": 3.0})
    assert report.values_changed == 1
    assert res_df["num"].max() < 1000.0


def test_remove_outliers_iqr():
    df = pd.DataFrame({"num": [10.0, 11.0, 12.0, 10.0, 11.0, 12.0, 100.0, -50.0]})
    original_len = len(df)
    res_df, report = FUNCTION_REGISTRY["remove_outliers_iqr"](df, ["num"], {"multiplier": 1.5})
    assert len(res_df) < original_len
    assert report.rows_affected >= 2
    assert 100.0 not in res_df["num"].values
    assert -50.0 not in res_df["num"].values


# ============================================================================
# 6. ENCODING TESTS
# ============================================================================

def test_one_hot_encode():
    df = pd.DataFrame({"category": ["A", "B", "A", "C"]})
    res_df, report = FUNCTION_REGISTRY["one_hot_encode"](df, ["category"], {"drop_first": False})
    assert "category" not in res_df.columns
    assert "category_A" in res_df.columns
    assert "category_B" in res_df.columns
    assert "category_C" in res_df.columns
    assert res_df["category_A"].tolist() == [1, 0, 1, 0]


def test_label_encode():
    df = pd.DataFrame({"color": ["red", "green", "blue", "red"]})
    res_df, report = FUNCTION_REGISTRY["label_encode"](df, ["color"], {})
    assert "color" in res_df.columns
    assert pd.api.types.is_integer_dtype(res_df["color"])
    assert len(res_df["color"].unique()) == 3


# ============================================================================
# 7. DATETIME TESTS
# ============================================================================

def test_to_datetime():
    df = pd.DataFrame({"dates": ["2023-01-01", "2023-06-15", "2023-12-31"]})
    res_df, report = FUNCTION_REGISTRY["to_datetime"](df, ["dates"], {})
    assert pd.api.types.is_datetime64_any_dtype(res_df["dates"])
    assert report.columns_affected == ["dates"]
    assert res_df["dates"].dt.year.tolist() == [2023, 2023, 2023]


def test_extract_datetime_features():
    df = pd.DataFrame({"dt": pd.to_datetime(["2023-05-10 14:30:00", "2024-11-20 08:00:00"])})
    res_df, report = FUNCTION_REGISTRY["extract_datetime_features"](df, ["dt"], {
        "features": ["year", "month", "day", "dayofweek", "hour"]
    })
    assert "dt_year" in res_df.columns
    assert "dt_month" in res_df.columns
    assert "dt_day" in res_df.columns
    assert "dt_dayofweek" in res_df.columns
    assert "dt_hour" in res_df.columns
    assert res_df["dt_year"].tolist() == [2023, 2024]
    assert res_df["dt_hour"].tolist() == [14, 8]


# ============================================================================
# 8. EDGE CASES: Empty DataFrame, All-NaN, Invalid Type, Non-existent Column
# ============================================================================

@pytest.mark.parametrize("func_name", REQUIRED_REGISTRY_FUNCTIONS)
def test_edge_case_empty_dataframe(func_name):
    """Every function in FUNCTION_REGISTRY must handle an empty DataFrame without raising unhandled exceptions."""
    df_empty = pd.DataFrame({"col_num": pd.Series(dtype=float), "col_str": pd.Series(dtype=str)})
    col = "col_num" if "scale" in func_name or "outlier" in func_name or "mean" in func_name or "median" in func_name else "col_str"
    res_df, report = FUNCTION_REGISTRY[func_name](df_empty, [col], {})
    assert isinstance(res_df, pd.DataFrame)
    assert isinstance(report, ExecutionReport)


@pytest.mark.parametrize("func_name", REQUIRED_REGISTRY_FUNCTIONS)
def test_edge_case_all_nan_column(func_name):
    """Every function must handle an all-NaN column gracefully."""
    df_nan = pd.DataFrame({"target_col": [np.nan, np.nan, np.nan]})
    res_df, report = FUNCTION_REGISTRY[func_name](df_nan, ["target_col"], {})
    assert isinstance(res_df, pd.DataFrame)
    assert isinstance(report, ExecutionReport)


def test_edge_case_invalid_column_type_for_numeric_transforms():
    """Numeric functions applied to string column must log a warning and not crash."""
    df_str = pd.DataFrame({"text_col": ["apple", "banana", "cherry", "date", "elderberry"]})
    numeric_funcs = [
        "standard_scale",
        "minmax_scale",
        "robust_scale",
        "cap_outliers_iqr",
        "cap_outliers_zscore",
        "remove_outliers_iqr",
        "impute_mean",
        "impute_median"
    ]
    for fn_name in numeric_funcs:
        res_df, report = FUNCTION_REGISTRY[fn_name](df_str, ["text_col"], {})
        assert isinstance(res_df, pd.DataFrame)
        assert len(report.warnings) > 0
        assert any("not numeric" in w.lower() for w in report.warnings)


@pytest.mark.parametrize("func_name", REQUIRED_REGISTRY_FUNCTIONS)
def test_edge_case_non_existent_column(func_name):
    """Passing a column name not in the DataFrame must log a warning and not crash."""
    df = pd.DataFrame({"real_col": [1, 2, 3]})
    res_df, report = FUNCTION_REGISTRY[func_name](df, ["missing_col"], {})
    assert isinstance(res_df, pd.DataFrame)
    assert len(report.warnings) > 0
    assert any("missing_col" in w for w in report.warnings)


# ============================================================================
# 9. TRANSACTIONAL EXECUTION & ROLLBACK TESTS
# ============================================================================

def test_execute_transactionally_success():
    """Successful plan applies changes and returns execution summary."""
    df = pd.DataFrame({
        "num": [10.0, 20.0, np.nan, 40.0],
        "cat": ["a", "b", "a", "b"]
    })
    actions = [
        {
            "action_id": "act_001",
            "function_name": "impute_mean",
            "target_columns": ["num"],
            "params": {}
        },
        {
            "action_id": "act_002",
            "function_name": "delete_column",
            "target_columns": ["cat"],
            "params": {}
        }
    ]
    res_df, summary = execute_transactionally(df, actions, "test_dataset")

    assert res_df["num"].isnull().sum() == 0
    assert "cat" not in res_df.columns
    assert summary["actions_applied"] == ["act_001", "act_002"]
    assert summary.get("rollback_performed") is not True
    assert summary["rows_after"] == 4
    assert summary["columns_after"] == 1


def test_execute_transactionally_rollback_on_error():
    """When an action raises an error, all changes are rolled back and original DataFrame is restored."""
    df_original = pd.DataFrame({
        "num": [10.0, 20.0, np.nan, 40.0],
        "cat": ["a", "b", "a", "b"]
    })
    df_input = df_original.copy()

    actions = [
        {
            "action_id": "act_001",
            "function_name": "impute_mean",
            "target_columns": ["num"],
            "params": {}
        },
        {
            "action_id": "act_002",
            "function_name": "unknown_function_that_fails",
            "target_columns": ["cat"],
            "params": {}
        }
    ]

    res_df, summary = execute_transactionally(df_input, actions, "test_dataset")

    # Full rollback check
    assert summary["rollback_performed"] is True
    assert summary["actions_applied"] == []
    # Changes from act_001 must be completely reverted
    pd.testing.assert_frame_equal(res_df, df_original)


def test_execute_transactionally_rollback_on_raised_exception(monkeypatch):
    """When a registered function raises an unexpected exception, rollback restores snapshot."""
    df_original = pd.DataFrame({"val": [1.0, 2.0, np.nan, 4.0]})
    df_input = df_original.copy()

    def failing_fn(df, cols, params):
        raise RuntimeError("Simulated processing disaster")

    # Monkeypatch one function to throw
    monkeypatch.setitem(FUNCTION_REGISTRY, "failing_action", failing_fn)

    actions = [
        {
            "action_id": "act_001",
            "function_name": "impute_mean",
            "target_columns": ["val"],
            "params": {}
        },
        {
            "action_id": "act_002",
            "function_name": "failing_action",
            "target_columns": ["val"],
            "params": {}
        }
    ]

    res_df, summary = execute_transactionally(df_input, actions, "test_dataset")

    assert summary["rollback_performed"] is True
    assert summary["actions_applied"] == []
    pd.testing.assert_frame_equal(res_df, df_original)
