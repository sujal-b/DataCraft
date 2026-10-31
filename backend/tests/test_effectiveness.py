import pytest
import pandas as pd
import numpy as np
from celery_worker import _compute_effectiveness_score


# ============================================================================
# 1. IMPORT & CALLABILITY TEST
# ============================================================================

def test_import_compute_effectiveness_score():
    """Verify _compute_effectiveness_score is importable and callable."""
    assert callable(_compute_effectiveness_score)


# ============================================================================
# 2. IMPROVED DATASET: POSITIVE DELTA & BOUNDS [0.0, 1.0]
# ============================================================================

def test_improved_dataset_yields_positive_delta_and_valid_bounds():
    """
    Test with synthetic before/after data:
    - Before: has missing values (30 missing cells), high skew (3.5), leakage risk.
    - After: missing values imputed (0 missing cells), skewness normalized (~0.0), no leakage.
    - ML improvement score: 0.25 lift.
    Assert improved dataset yields positive delta and all scores are strictly between 0.0 and 1.0.
    """
    n_rows = 100
    before_profile = {
        "row_count": n_rows,
        "column_count": 2,
        "columns": {
            "feature_skewed": {
                "missing_count": 20,
                "missing_pct": 20.0,
                "skewness": 3.5,
                "data_type": "float"
            },
            "feature_clean": {
                "missing_count": 10,
                "missing_pct": 10.0,
                "skewness": 0.05,
                "data_type": "float"
            }
        }
    }

    # Uncleaned baseline dataset (identical to before state with leakage and 0 ML lift)
    uncleaned_df = pd.DataFrame({
        "feature_skewed": [np.nan] * 20 + list(np.exp(np.linspace(0, 3, 80))),
        "feature_clean": [np.nan] * 10 + list(np.linspace(0, 10, 90))
    })
    baseline_result = _compute_effectiveness_score(
        before_profile=before_profile,
        after_df=uncleaned_df,
        ml_improvement_score=0.0,
        leakage_warnings=["Warning: high leakage risk detected on column 'feature_skewed'"]
    )

    # Cleaned and improved dataset (missing values imputed, skew normalized, ML lift, no leakage)
    cleaned_df = pd.DataFrame({
        "feature_skewed": np.linspace(0, 10, n_rows),  # skewness is ~0.0
        "feature_clean": np.linspace(0, 10, n_rows)
    })
    improved_result = _compute_effectiveness_score(
        before_profile=before_profile,
        after_df=cleaned_df,
        ml_improvement_score=0.25,
        leakage_warnings=[]
    )

    # 1. Delta between improved and baseline must be positive
    delta = improved_result["cleaning_effectiveness"] - baseline_result["cleaning_effectiveness"]
    assert delta > 0, f"Expected positive effectiveness delta, got {delta}"

    # 2. All scores and components must be strictly bounded in [0.0, 1.0]
    score_keys = [
        "cleaning_effectiveness",
        "missing_reduction_score",
        "skew_reduction_score",
        "ml_improvement_score",
        "leakage_absence_score",
        "quality_improvement",
        "skew_reduction",
        "ml_improvement",
        "leakage_prevention"
    ]
    for key in score_keys:
        val = improved_result[key]
        assert 0.0 <= val <= 1.0, f"Improved score '{key}' = {val} is outside [0.0, 1.0]"
        base_val = baseline_result[key]
        assert 0.0 <= base_val <= 1.0, f"Baseline score '{key}' = {base_val} is outside [0.0, 1.0]"


# ============================================================================
# 3. IDENTICAL BEFORE / AFTER DATA TEST
# ============================================================================

def test_identical_before_after_data():
    """
    Test when dataset has had no improvements (identical before and after):
    - Same missing count
    - Same skewness
    - 0 ML improvement
    - Leakage warning present
    Expect missing_reduction = 0.0, skew_reduction = 0.0, ml_improvement = 0.0, leakage = 0.0.
    """
    n_rows = 50
    # Values with intentional skew and missing values
    raw_vals = [np.nan] * 10 + [float(i**2) for i in range(40)]
    df_raw = pd.DataFrame({"metric": raw_vals})
    actual_skew = float(df_raw["metric"].dropna().skew())

    before_profile = {
        "row_count": n_rows,
        "column_count": 1,
        "columns": {
            "metric": {
                "missing_count": 10,
                "missing_pct": 20.0,
                "skewness": actual_skew,
                "data_type": "float"
            }
        }
    }

    result = _compute_effectiveness_score(
        before_profile=before_profile,
        after_df=df_raw,
        ml_improvement_score=0.0,
        leakage_warnings=["Unresolved leakage risk"]
    )

    assert result["quality_improvement"] == 0.0
    assert result["missing_reduction_score"] == 0.0
    assert pytest.approx(result["skew_reduction"], abs=1e-4) == 0.0
    assert result["ml_improvement"] == 0.0
    assert result["leakage_prevention"] == 0.0
    assert result["cleaning_effectiveness"] == 0.0


# ============================================================================
# 4. COMPONENT BREAKDOWN TESTS
# ============================================================================

def test_component_breakdown_presence():
    """Verify all four component breakdown keys are present in the output dictionary."""
    before_profile = {
        "row_count": 10,
        "column_count": 1,
        "columns": {"col": {"missing_count": 2, "missing_pct": 20.0, "skewness": 1.0}}
    }
    after_df = pd.DataFrame({"col": [1.0] * 10})
    res = _compute_effectiveness_score(before_profile, after_df, 0.1, [])

    required_components = [
        "quality_improvement",
        "ml_improvement",
        "leakage_prevention",
        "skew_reduction"
    ]
    for comp in required_components:
        assert comp in res, f"Missing required component '{comp}' in effectiveness score result"
        assert 0.0 <= res[comp] <= 1.0


def test_quality_improvement_component():
    """Test quality_improvement isolates missing value reduction."""
    before_profile = {
        "row_count": 100,
        "column_count": 1,
        "columns": {"feat": {"missing_count": 50, "missing_pct": 50.0, "skewness": 0.0}}
    }
    # Case A: 100% missing values resolved
    df_clean = pd.DataFrame({"feat": [1.0] * 100})
    res_clean = _compute_effectiveness_score(before_profile, df_clean, 0.0, ["leakage"])
    assert res_clean["quality_improvement"] == 1.0

    # Case B: 50% of missing values resolved (from 50 down to 25)
    df_half = pd.DataFrame({"feat": [np.nan] * 25 + [1.0] * 75})
    res_half = _compute_effectiveness_score(before_profile, df_half, 0.0, ["leakage"])
    assert pytest.approx(res_half["quality_improvement"], abs=1e-4) == 0.5


def test_ml_improvement_component():
    """Test ml_improvement reflects model metric lift and clamps properly."""
    before_profile = {"row_count": 10, "column_count": 1, "columns": {}}
    df = pd.DataFrame({"a": [1] * 10})

    # Within bounds [0, 1]
    res = _compute_effectiveness_score(before_profile, df, 0.42, ["leakage"])
    assert res["ml_improvement"] == 0.42

    # Negative clamped to 0.0
    res_neg = _compute_effectiveness_score(before_profile, df, -0.5, ["leakage"])
    assert res_neg["ml_improvement"] == 0.0

    # > 1.0 clamped to 1.0
    res_high = _compute_effectiveness_score(before_profile, df, 1.8, ["leakage"])
    assert res_high["ml_improvement"] == 1.0


def test_leakage_prevention_component():
    """Test leakage_prevention is 1.0 when no warnings, 0.0 when warnings exist."""
    before_profile = {"row_count": 10, "column_count": 1, "columns": {}}
    df = pd.DataFrame({"a": [1] * 10})

    # No leakage warnings
    res_safe = _compute_effectiveness_score(before_profile, df, 0.0, [])
    assert res_safe["leakage_prevention"] == 1.0

    # Leakage warnings present
    res_warn = _compute_effectiveness_score(before_profile, df, 0.0, ["Target leakage in feature_x"])
    assert res_warn["leakage_prevention"] == 0.0


def test_skew_reduction_component():
    """Test skew_reduction measures the reduction in skewness."""
    # Before: highly skewed data
    before_profile = {
        "row_count": 100,
        "column_count": 1,
        "columns": {
            "skewed_col": {"missing_count": 0, "missing_pct": 0.0, "skewness": 4.0}
        }
    }
    # After: symmetrically distributed data (skew ~0.0)
    df_symmetric = pd.DataFrame({"skewed_col": np.linspace(-5, 5, 100)})
    res = _compute_effectiveness_score(before_profile, df_symmetric, 0.0, ["leakage"])
    assert res["skew_reduction"] > 0.8
    assert res["skew_reduction"] <= 1.0


def test_composite_formula_weights():
    """
    Verify the composite effectiveness matches the weighted sum of components:
    0.30 * quality_improvement + 0.20 * skew_reduction + 0.40 * ml_improvement + 0.10 * leakage_prevention
    """
    before_profile = {
        "row_count": 100,
        "column_count": 1,
        "columns": {
            "x": {"missing_count": 20, "missing_pct": 20.0, "skewness": 3.0}
        }
    }
    after_df = pd.DataFrame({"x": np.linspace(1, 10, 100)})
    res = _compute_effectiveness_score(
        before_profile=before_profile,
        after_df=after_df,
        ml_improvement_score=0.5,
        leakage_warnings=[]
    )

    expected = round(
        0.30 * res["quality_improvement"] +
        0.20 * res["skew_reduction"] +
        0.40 * res["ml_improvement"] +
        0.10 * res["leakage_prevention"],
        4
    )
    assert res["cleaning_effectiveness"] == expected
