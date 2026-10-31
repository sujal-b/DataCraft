import os
from unittest.mock import MagicMock
import pytest
from fastapi import HTTPException

import config
from security import resolve_dataset, sanitize_filename, RateLimiter


@pytest.mark.parametrize(
    "traversal_path",
    [
        r"..\secret.csv",
        "../../etc/passwd",
        "valid/../../escape.csv",
        r"C:\Windows\win.ini",
    ],
)
def test_resolve_dataset_path_traversal(traversal_path):
    with pytest.raises(HTTPException) as exc_info:
        resolve_dataset(traversal_path)
    assert exc_info.value.status_code == 400


def test_resolve_dataset_non_existent():
    with pytest.raises(HTTPException) as exc_info:
        resolve_dataset("non_existent_dataset_12345.csv")
    assert exc_info.value.status_code == 404


def test_resolve_dataset_valid_file_in_public_dir():
    test_filename = "_test_dummy_dataset_.csv"
    test_path = os.path.join(config.PUBLIC_DIR, test_filename)
    try:
        with open(test_path, "w", encoding="utf-8") as f:
            f.write("col1,col2\nval1,val2\n")
        resolved = resolve_dataset(test_filename)
        assert resolved == os.path.abspath(test_path)
        assert os.path.isfile(resolved)
    finally:
        if os.path.exists(test_path):
            os.remove(test_path)


def test_sanitize_filename():
    assert sanitize_filename("data.csv") == "data.csv"

    for bad_filename in ["test..csv", "hack/data.csv", "data.exe"]:
        with pytest.raises(HTTPException) as exc_info:
            sanitize_filename(bad_filename)
        assert exc_info.value.status_code == 400


def test_rate_limiter_exceed():
    limiter = RateLimiter(per_minute=3)
    request = MagicMock()
    request.client.host = "192.168.1.100"

    # 3 allowed requests within 60s
    limiter.check(request)
    limiter.check(request)
    limiter.check(request)

    # Exceed rate limit within 60s
    with pytest.raises(HTTPException) as exc_info:
        limiter.check(request)
    assert exc_info.value.status_code == 429
