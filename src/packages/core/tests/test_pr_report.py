"""Unit tests for Vera PR-comment integration (no network)."""

from vera.pr_report import (
    DiffMap,
    GitHubPRClient,
    build_diff_maps,
    build_review,
    format_comment,
    run,
)


def _viol(rule, file, line, sev="serious", desc="x", sug="y", wcag="1.1.1"):
    return {
        "rule": rule, "severity": sev, "description": desc, "suggestion": sug,
        "wcag_criterion": wcag, "location": {"file": file, "line": line},
    }

# A two-hunk patch. New-file line numbers per the +N,M hunk headers.
PATCH = (
    "@@ -1,3 +1,4 @@\n"
    " import React from 'react';\n"      # ctx  new line 1, pos 1
    "+import Logo from './logo.png';\n"   # add  new line 2, pos 2
    " \n"                                  # ctx  new line 3, pos 3
    " export default function App() {\n"  # ctx  new line 4, pos 4
    "@@ -10,2 +11,3 @@\n"                  # hunk header           pos 5
    " <main>\n"                            # ctx  new line 11, pos 6
    "-  <img src=\"a.png\" />\n"           # del               pos 7
    "+  <img src=\"a.png\" alt=\"\" />\n"  # add  new line 12, pos 8
)


def test_added_lines_detected():
    dm = DiffMap(PATCH)
    assert dm.added_lines == {2, 12}


def test_position_for_added_lines():
    dm = DiffMap(PATCH)
    assert dm.position_for(2) == 2     # first addition
    assert dm.position_for(12) == 8    # addition after a deletion in 2nd hunk


def test_position_for_context_lines():
    dm = DiffMap(PATCH)
    assert dm.position_for(1) == 1     # line just below the first @@
    assert dm.position_for(4) == 4
    assert dm.position_for(11) == 6    # context line in the second hunk


def test_deletion_does_not_map_to_new_line():
    dm = DiffMap(PATCH)
    # The deleted line advances position but is not a new-file line; line 12
    # (the replacement) is what maps, at position 8.
    assert dm.position_for(12) == 8


def test_line_outside_diff_is_none():
    dm = DiffMap(PATCH)
    assert dm.position_for(99) is None
    assert dm.is_commentable(99) is False


def test_is_commentable_only_added():
    dm = DiffMap(PATCH)
    assert dm.is_commentable(2) is True
    assert dm.is_commentable(12) is True
    assert dm.is_commentable(1) is False   # context line, not added
    assert dm.is_commentable(4) is False


def test_empty_or_missing_patch():
    assert DiffMap("").added_lines == set()
    assert DiffMap("").position_for(1) is None


def test_build_diff_maps_skips_binary_files():
    files = [
        {"filename": "src/App.jsx", "patch": PATCH},
        {"filename": "logo.png"},                       # binary, no patch
        {"filename": "big.min.js", "patch": None},      # too large, no patch
    ]
    maps = build_diff_maps(files)
    assert set(maps.keys()) == {"src/App.jsx"}
    assert maps["src/App.jsx"].added_lines == {2, 12}


def test_single_hunk_simple():
    patch = (
        "@@ -5,0 +6,2 @@\n"
        "+const a = 1;\n"      # new line 6, pos 1
        "+const b = 2;\n"      # new line 7, pos 2
    )
    dm = DiffMap(patch)
    assert dm.added_lines == {6, 7}
    assert dm.position_for(6) == 1
    assert dm.position_for(7) == 2


# ── GitHub client (fake transport) ─────────────────────────────────────────────

def test_client_paginates_and_creates_review():
    calls = []

    def fake(method, path, json=None):
        calls.append((method, path, json))
        if method == "GET" and "/files" in path:
            return [] if "page=2" in path else [{"filename": "a.jsx", "patch": "@@ -1 +1 @@\n+x"}]
        if method == "GET" and "/comments" in path:
            return []
        if method == "POST" and "/reviews" in path:
            return {"id": 1, "state": "COMMENTED"}
        return []

    c = GitHubPRClient("tok", "org/vera", request=fake)
    files = c.get_pr_files(7)
    assert len(files) == 1 and files[0]["filename"] == "a.jsx"
    res = c.create_review(7, "body", [{"path": "a.jsx", "position": 1, "body": "hi"}])
    assert res["state"] == "COMMENTED"
    # last call is the POST review with comments included
    assert calls[-1][0] == "POST" and calls[-1][2]["comments"]


# ── Reporter ───────────────────────────────────────────────────────────────────

DIFF_FILES = [{"filename": "src/App.jsx", "patch": PATCH}]   # added lines {2, 12}


def test_reporter_inlines_violation_on_added_line():
    maps = build_diff_maps(DIFF_FILES)
    review = build_review([_viol("missing-alt", "src/App.jsx", 12)], maps)
    assert review["inline_count"] == 1
    assert review["summary_count"] == 0
    c = review["comments"][0]
    assert c["path"] == "src/App.jsx" and c["position"] == 8
    assert "missing-alt" in c["body"]


def test_reporter_buckets_violation_off_diff():
    maps = build_diff_maps(DIFF_FILES)
    # line 4 is a context line (not added) → summary, not inline
    review = build_review([_viol("missing-alt", "src/App.jsx", 4)], maps)
    assert review["inline_count"] == 0
    assert review["summary_count"] == 1


def test_reporter_line_zero_goes_to_summary():
    # audit B4: LLM violations have line=0 and can never be inline
    maps = build_diff_maps(DIFF_FILES)
    review = build_review([_viol("color-contrast", "src/App.jsx", 0)], maps)
    assert review["inline_count"] == 0
    assert review["summary_count"] == 1
    assert "color-contrast" in review["body"]


def test_reporter_dedup_against_existing():
    maps = build_diff_maps(DIFF_FILES)
    existing = [{
        "path": "src/App.jsx", "position": 8,
        "body": format_comment(_viol("missing-alt", "src/App.jsx", 12)),
    }]
    review = build_review([_viol("missing-alt", "src/App.jsx", 12)], maps, existing)
    assert review["inline_count"] == 0     # already commented → skipped


def test_reporter_dedup_within_batch():
    maps = build_diff_maps(DIFF_FILES)
    v = _viol("missing-alt", "src/App.jsx", 12)
    review = build_review([v, v], maps)
    assert review["inline_count"] == 1     # same finding twice → one comment


def test_reporter_path_normalization():
    maps = build_diff_maps(DIFF_FILES)
    review = build_review([_viol("missing-alt", "./src/App.jsx", 12)], maps)
    assert review["inline_count"] == 1     # leading ./ normalized


def test_reporter_clean_pr_message():
    maps = build_diff_maps(DIFF_FILES)
    review = build_review([], maps)
    assert "No accessibility issues" in review["body"]


# ── End-to-end run() with a fake client ────────────────────────────────────────

import asyncio


class FakeClient:
    def __init__(self, files, existing=None):
        self._files = files
        self._existing = existing or []
        self.posted = None

    def get_pr_files(self, pr):
        return self._files

    def get_review_comments(self, pr):
        return self._existing

    def create_review(self, pr, body, comments, event="COMMENT"):
        self.posted = {"pr": pr, "body": body, "comments": comments}
        return {"id": 99}


def test_run_posts_inline_and_summary():
    client = FakeClient(DIFF_FILES)
    violations = [
        _viol("missing-alt", "src/App.jsx", 12),    # on added line → inline
        _viol("color-contrast", "src/App.jsx", 0),  # line=0 → summary (B4)
    ]
    review = asyncio.run(run(
        repo="org/vera", pr_number=7, token="t",
        client=client, violations=violations,
    ))
    assert review["inline_count"] == 1
    assert review["summary_count"] == 1
    assert client.posted is not None
    assert client.posted["comments"][0]["position"] == 8
    assert "color-contrast" in client.posted["body"]


def test_run_rerun_is_idempotent():
    # Existing comment already covers the only inline finding → nothing new posted.
    existing = [{
        "path": "src/App.jsx", "position": 8,
        "body": format_comment(_viol("missing-alt", "src/App.jsx", 12)),
    }]
    client = FakeClient(DIFF_FILES, existing=existing)
    review = asyncio.run(run(
        repo="org/vera", pr_number=7, token="t",
        client=client, violations=[_viol("missing-alt", "src/App.jsx", 12)],
    ))
    assert review["inline_count"] == 0
    # No summary findings + comment already exists → no new review posted.
    assert client.posted is None
