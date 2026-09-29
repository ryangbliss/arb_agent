"""Tests for Kalshi auth header generation."""
import base64
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from unittest.mock import patch, MagicMock
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization


def _gen_key_pem() -> bytes:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _make_exchange(tmp_path):
    pem = _gen_key_pem()
    key_file = tmp_path / "test_key.pem"
    key_file.write_bytes(pem)
    # Patch config to avoid .env requirement
    with patch.dict(os.environ, {
        "KALSHI_KEY_ID": "test-uuid",
        "KALSHI_PRIVATE_KEY_PATH": str(key_file),
        "ANTHROPIC_API_KEY": "",
    }):
        import importlib, config
        importlib.reload(config)
        from exchanges.kalshi import KalshiExchange
        return KalshiExchange("test-uuid", str(key_file))


def test_headers_have_required_fields(tmp_path):
    ex = _make_exchange(tmp_path)
    h = ex._headers("GET", "/trade-api/v2/markets")
    assert "KALSHI-ACCESS-KEY" in h
    assert "KALSHI-ACCESS-TIMESTAMP" in h
    assert "KALSHI-ACCESS-SIGNATURE" in h
    assert h["KALSHI-ACCESS-KEY"] == "test-uuid"


def test_signature_is_base64(tmp_path):
    ex = _make_exchange(tmp_path)
    h = ex._headers("GET", "/some/path")
    sig = h["KALSHI-ACCESS-SIGNATURE"]
    # Should decode without error
    decoded = base64.b64decode(sig)
    assert len(decoded) > 0


def test_timestamp_is_milliseconds(tmp_path):
    import time
    ex = _make_exchange(tmp_path)
    h = ex._headers("GET", "/path")
    ts = int(h["KALSHI-ACCESS-TIMESTAMP"])
    now_ms = int(time.time() * 1000)
    # Timestamp should be within 5 seconds of now
    assert abs(ts - now_ms) < 5000


def test_different_paths_produce_different_signatures(tmp_path):
    ex = _make_exchange(tmp_path)
    h1 = ex._headers("GET", "/path/one")
    h2 = ex._headers("GET", "/path/two")
    assert h1["KALSHI-ACCESS-SIGNATURE"] != h2["KALSHI-ACCESS-SIGNATURE"]
