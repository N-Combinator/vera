"""Security regression tests — S1 (SSRF), S2 (path traversal), C3 (config isolation).

These are pure-function / unit tests; no network calls, no API server running.
"""

import os
import tempfile
from pathlib import Path

import pytest

from vera.describe import remote_fetch_blocked
from vera.code_fixer import _resolve_root, _within_root


# ── S1: SSRF guard (remote_fetch_blocked) ────────────────────────────────────

def test_ssrf_blocks_loopback():
    # localhost resolves to 127.0.0.1
    result = remote_fetch_blocked("http://localhost/secret")
    assert result is not None and "blocked" in result


def test_ssrf_blocks_127():
    result = remote_fetch_blocked("http://127.0.0.1/anything")
    assert result is not None and "blocked" in result


def test_ssrf_blocks_private_10():
    result = remote_fetch_blocked("http://10.0.0.1/internal")
    assert result is not None and "blocked" in result


def test_ssrf_blocks_cloud_metadata():
    # 169.254.169.254 is the AWS/GCP metadata endpoint
    result = remote_fetch_blocked("http://169.254.169.254/latest/meta-data/")
    assert result is not None and "blocked" in result


def test_ssrf_blocks_private_192():
    result = remote_fetch_blocked("http://192.168.1.1/admin")
    assert result is not None and "blocked" in result


def test_ssrf_rejects_non_http_scheme():
    result = remote_fetch_blocked("ftp://example.com/file")
    assert result is not None and "scheme" in result


def test_ssrf_rejects_file_scheme():
    result = remote_fetch_blocked("file:///etc/passwd")
    assert result is not None and "scheme" in result


def test_ssrf_rejects_no_host():
    result = remote_fetch_blocked("http:///no-host")
    assert result is not None


def test_ssrf_public_ip_allowed():
    # 1.1.1.1 is Cloudflare's public DNS — not private/loopback/link-local
    result = remote_fetch_blocked("http://1.1.1.1/")
    assert result is None


# ── S2: root jail (_resolve_root / _within_root) ─────────────────────────────

def test_within_root_accepts_child():
    with tempfile.TemporaryDirectory() as root:
        child = Path(root) / "sub" / "file.html"
        child.parent.mkdir(parents=True, exist_ok=True)
        child.touch()
        assert _within_root(child, Path(root)) is True


def test_within_root_blocks_traversal():
    with tempfile.TemporaryDirectory() as root:
        with tempfile.TemporaryDirectory() as outside:
            outside_file = Path(outside) / "passwd"
            outside_file.touch()
            assert _within_root(outside_file, Path(root)) is False


def test_within_root_blocks_dotdot():
    with tempfile.TemporaryDirectory() as root:
        # Construct a path that tries to escape via ..
        escape_attempt = Path(root) / ".." / "etc" / "passwd"
        # After resolve() it will be outside; should return False
        assert _within_root(escape_attempt, Path(root)) is False


def test_within_root_accepts_root_itself():
    with tempfile.TemporaryDirectory() as root:
        assert _within_root(Path(root), Path(root)) is True


def test_resolve_root_returns_dir_for_directory():
    with tempfile.TemporaryDirectory() as d:
        result = _resolve_root(d)
        assert result == Path(d).resolve()


def test_resolve_root_returns_parent_for_file():
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "index.html"
        f.touch()
        result = _resolve_root(str(f))
        assert result == Path(d).resolve()


def test_resolve_root_none_for_empty():
    assert _resolve_root(None) is None
    assert _resolve_root("") is None


# ── C3: config isolation — per-request rules must not mutate the shared global ─

def test_config_copy_does_not_mutate_original():
    from vera.config_loader import load_config
    cfg = load_config()
    original_rules = list(cfg.rules)

    # Simulate what the /scan endpoint does: deep copy then mutate
    per_req = cfg.model_copy(deep=True)
    per_req.rules = ["missing-alt"]

    # Original must be unchanged
    assert cfg.rules == original_rules, (
        "per-request rule override leaked into the shared global config"
    )
