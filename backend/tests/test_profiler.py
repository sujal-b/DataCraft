import os
import tempfile
from unittest.mock import patch, MagicMock
import pytest
import pandas as pd

from celery_worker import profile_dataset
import config

def test_profile_dataset_weather():
    """Verify profile_dataset executes without UnboundLocalError on weather.csv."""
    weather_csv = os.path.join(config.PUBLIC_DIR, "weather.csv")
    if not os.path.isfile(weather_csv):
        pytest.skip("weather.csv not found in public dir")

    mock_redis = MagicMock()
    mock_redis.get.return_value = None

    with patch("celery_worker.redis_cache", mock_redis):
        result = profile_dataset(weather_csv)
        assert result["status"] == "SUCCESS"
        assert "result" in result
        profile = result["result"]
        assert profile["dataset_name"] == "weather.csv"
        assert profile["row_count"] > 0
        assert profile["column_count"] > 0
        # Verify mode is populated without UnboundLocalError
        for col_name, col_stats in profile["columns"].items():
            assert "mode" in col_stats
            assert "missing_count" in col_stats
            assert "data_type" in col_stats

def test_profile_dataset_mode_computation():
    """Verify mode calculation works for both numeric and categorical columns."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_csv = os.path.join(tmp_dir, "test_data.csv")
        df = pd.DataFrame({
            "num_col": [1, 2, 2, 3, None],
            "cat_col": ["apple", "banana", "banana", "cherry", None]
        })
        df.to_csv(test_csv, index=False)

        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        with patch("celery_worker.redis_cache", mock_redis):
            result = profile_dataset(test_csv)
            assert result["status"] == "SUCCESS"
            cols = result["result"]["columns"]
            assert cols["num_col"]["mode"] == 2.0
            assert cols["cat_col"]["mode"] == "banana"
