"""
Vera — PR-comment integration: post accessibility findings as inline review
comments on a GitHub pull request (GitHub Actions native).

Three layers (each independently testable):
  * diff mapping  — map a source line to its position in a PR file's unified diff,
    and know which lines are even commentable (added lines inside a hunk).
  * GitHub client — fetch PR files/patches + existing comments, create a review.
  * reporter      — turn scan violations into a review: inline where the line is in
    the diff, otherwise bucketed into a summary; de-duplicated across re-runs.

Design notes grounded in the Vera audit:
  * B4 — LLM-detected violations carry line=0; they can never be placed inline, so
    they always fall through to the summary bucket (never silently dropped).
  * Re-runs must not spam: a comment identical to one already on the PR is skipped.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Set

# ── Diff position mapping ──────────────────────────────────────────────────────
#
# GitHub review comments accept a `position`: the 1-based offset of a line within
# a file's unified-diff `patch`, counting every line after the first `@@` hunk
# header (context, additions, deletions, and subsequent hunk headers all count).
# The line directly below the first `@@` is position 1.

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


class DiffMap:
    """Parsed view of one file's patch.

    new_line_to_position: new-file line number → diff position (added + context).
    added_lines:          new-file line numbers introduced by this PR ('+' lines).
    """

    def __init__(self, patch: str):
        self.new_line_to_position: Dict[int, int] = {}
        self.added_lines: Set[int] = set()
        self._parse(patch or "")

    def _parse(self, patch: str) -> None:
        position = 0
        new_line = 0
        seen_hunk = False

        for raw in patch.split("\n"):
            m = _HUNK_RE.match(raw)
            if m:
                new_line = int(m.group(1))
                if not seen_hunk:
                    seen_hunk = True
                    position = 0          # the next line is position 1
                else:
                    position += 1         # subsequent hunk headers occupy a slot
                continue

            if not seen_hunk:
                continue                  # preamble ("diff --git", "+++", etc.)

            position += 1

            if raw.startswith("+"):
                self.new_line_to_position[new_line] = position
                self.added_lines.add(new_line)
                new_line += 1
            elif raw.startswith(" "):
                self.new_line_to_position[new_line] = position
                new_line += 1
            elif raw.startswith("-"):
                pass                       # deletion: advances position, not new_line
            # a stray line (e.g. "\ No newline at end of file") still consumed a slot

    def position_for(self, line: int) -> Optional[int]:
        """Diff position for a new-file line, or None if it is not in the diff."""
        return self.new_line_to_position.get(line)

    def is_commentable(self, line: int) -> bool:
        """True only for lines this PR actually added — where an inline comment
        is meaningful (we don't annotate untouched context lines)."""
        return line in self.added_lines


def build_diff_maps(files: List[dict]) -> Dict[str, DiffMap]:
    """From the GitHub 'list PR files' payload → {filename: DiffMap}.

    Files without a patch (binary, too large, pure rename) are skipped.
    """
    maps: Dict[str, DiffMap] = {}
    for f in files:
        patch = f.get("patch")
        if patch:
            maps[f["filename"]] = DiffMap(patch)
    return maps


# ── GitHub PR client ───────────────────────────────────────────────────────────

_GH_API = "https://api.github.com"


class GitHubPRClient:
    """Minimal GitHub PR client. `request(method, path, json)` is injectable so
    the reporter is testable without network or a token."""

    def __init__(self, token: str, repo: str, request=None):
        self.token = token
        self.repo = repo                      # "owner/name"
        self._request = request or self._http_request

    def _http_request(self, method: str, path: str, json=None):
        import httpx
        resp = httpx.request(
            method, f"{_GH_API}{path}",
            headers={
                "Authorization": f"token {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json=json, timeout=30,
        )
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    def get_pr_files(self, pr: int) -> List[dict]:
        files, page = [], 1
        while True:
            batch = self._request("GET", f"/repos/{self.repo}/pulls/{pr}/files?per_page=100&page={page}")
            if not batch:
                break
            files.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return files

    def get_review_comments(self, pr: int) -> List[dict]:
        comments, page = [], 1
        while True:
            batch = self._request("GET", f"/repos/{self.repo}/pulls/{pr}/comments?per_page=100&page={page}")
            if not batch:
                break
            comments.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return comments

    def create_review(self, pr: int, body: str, comments: List[dict], event: str = "COMMENT"):
        payload = {"body": body, "event": event}
        if comments:
            payload["comments"] = comments
        return self._request("POST", f"/repos/{self.repo}/pulls/{pr}/reviews", json=payload)


# ── Reporter ───────────────────────────────────────────────────────────────────

_MARKER = "<!-- vera-a11y -->"   # identifies our comments for idempotent re-runs


def _normalize(path: str) -> str:
    return path.lstrip("./").replace("\\", "/")


def _match_diff_file(vfile: str, diff_files: List[str]) -> Optional[str]:
    """Map a violation's file path onto a PR diff path (repo-relative).

    Scans run from the repo root in CI, but paths may carry a leading ./ or a
    workspace prefix — match exact-normalized first, then unique suffix.
    """
    nv = _normalize(vfile)
    if nv in diff_files:
        return nv
    cands = [d for d in diff_files if nv.endswith(d) or d.endswith(nv)]
    return cands[0] if len(cands) == 1 else None


def format_comment(v: dict) -> str:
    rule = v.get("rule", "?")
    sev = v.get("severity", "")
    desc = v.get("description", "")
    sug = v.get("suggestion", "")
    wcag = v.get("wcag_criterion")
    out = [f"{_MARKER}", f"**♿ Vera · `{rule}`** ({sev})", "", desc]
    if sug:
        out += ["", f"**Fix:** {sug}"]
    if wcag:
        out += ["", f"WCAG {wcag}"]
    return "\n".join(out)


def _comment_key(path: str, position: int, rule: str) -> str:
    return f"{path}:{position}:{rule}"


def build_review(
    violations: List[dict],
    diff_maps: Dict[str, DiffMap],
    existing_comments: Optional[List[dict]] = None,
) -> dict:
    """Build a {body, comments, inline_count, summary_count} review payload.

    Inline when the violation sits on a line this PR added; otherwise the finding
    goes into the summary body (incl. audit-B4 line=0 LLM findings). Comments that
    already exist on the PR (same path+position+rule) are skipped — re-run safe.
    """
    diff_files = list(diff_maps.keys())

    # Index existing Vera comments so re-runs don't duplicate.
    existing_keys: Set[str] = set()
    for c in (existing_comments or []):
        if _MARKER in (c.get("body") or "") and c.get("position") is not None:
            rule = _rule_from_body(c.get("body", ""))
            existing_keys.add(_comment_key(c.get("path", ""), c["position"], rule))

    inline: List[dict] = []
    summary: List[dict] = []
    seen_new: Set[str] = set()

    for v in violations:
        loc = v.get("location") or {}
        vfile = loc.get("file") if isinstance(loc, dict) else None
        line = loc.get("line", 0) if isinstance(loc, dict) else 0

        target = _match_diff_file(vfile, diff_files) if vfile else None
        if target and line and diff_maps[target].is_commentable(line):
            pos = diff_maps[target].position_for(line)
            key = _comment_key(target, pos, v.get("rule", "?"))
            if key in existing_keys or key in seen_new:
                continue                      # already commented (or dup in batch)
            seen_new.add(key)
            inline.append({"path": target, "position": pos, "body": format_comment(v)})
        else:
            summary.append(v)                 # not in diff / line=0 → summary

    body = _render_summary(summary, inline_count=len(inline))
    return {
        "body": body,
        "comments": inline,
        "inline_count": len(inline),
        "summary_count": len(summary),
    }


def _rule_from_body(body: str) -> str:
    m = re.search(r"`([a-z0-9-]+)`", body)
    return m.group(1) if m else "?"


def _render_summary(summary: List[dict], inline_count: int) -> str:
    lines = [_MARKER, "## ♿ Vera accessibility review", ""]
    lines.append(f"- {inline_count} issue(s) flagged inline on changed lines.")
    if summary:
        lines.append(f"- {len(summary)} issue(s) not on changed lines (listed below):")
        lines.append("")
        for v in summary:
            loc = v.get("location") or {}
            where = ""
            if isinstance(loc, dict) and loc.get("file"):
                where = f"`{_normalize(loc['file'])}`"
                if loc.get("line"):
                    where += f":{loc['line']}"
            sev = v.get("severity", "")
            lines.append(f"  - **{v.get('rule','?')}** ({sev}) {where} — {v.get('description','')}")
    if not inline_count and not summary:
        lines.append("")
        lines.append("✅ No accessibility issues found.")
    return "\n".join(lines)


# ── Orchestration + GitHub Actions entry point ─────────────────────────────────

async def _scan_violations(scan_path: str) -> List[dict]:
    """Run Vera's scanner and return violations as plain dicts."""
    from .config_loader import load_config
    from .scanner import Scanner

    cfg = load_config()
    scanner = Scanner(config=cfg, llm=None)     # heuristics only in CI by default
    result = await scanner.scan(scan_path)
    return [v.model_dump() for v in result.violations]


async def run(
    *,
    repo: str,
    pr_number: int,
    token: str,
    scan_path: str = ".",
    client: Optional[GitHubPRClient] = None,
    violations: Optional[List[dict]] = None,
) -> dict:
    """Scan, map findings onto the PR diff, and post a single review.

    `client` and `violations` are injectable so the whole flow is unit-testable
    without GitHub or a real scan.
    """
    client = client or GitHubPRClient(token, repo)
    if violations is None:
        violations = await _scan_violations(scan_path)

    files = client.get_pr_files(pr_number)
    diff_maps = build_diff_maps(files)
    existing = client.get_review_comments(pr_number)
    review = build_review(violations, diff_maps, existing)

    # Only call the API when there is something new to say (avoids empty reviews
    # on every re-run once all findings are already commented).
    if review["comments"] or review["summary_count"] or not existing:
        client.create_review(pr_number, review["body"], review["comments"])

    review["violations"] = violations
    return review


def _pr_number_from_env() -> Optional[int]:
    """Resolve the PR number from the GitHub Actions event payload or refs."""
    import json
    import os

    path = os.getenv("GITHUB_EVENT_PATH")
    if path and os.path.exists(path):
        try:
            with open(path) as f:
                event = json.load(f)
            if "pull_request" in event:
                return int(event["pull_request"]["number"])
            if "number" in event:
                return int(event["number"])
        except Exception:
            pass
    ref = os.getenv("GITHUB_REF", "")          # refs/pull/<n>/merge
    m = re.search(r"refs/pull/(\d+)/", ref)
    return int(m.group(1)) if m else None


def main() -> int:
    import asyncio
    import logging
    import os

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    log = logging.getLogger("vera.pr_report")

    token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPOSITORY")      # "owner/name"
    scan_path = os.getenv("VERA_SCAN_PATH", ".")
    pr_number = _pr_number_from_env()

    if not (token and repo and pr_number):
        log.error("[vera] need GITHUB_TOKEN, GITHUB_REPOSITORY and a PR context; skipping.")
        return 0                                # no-op on non-PR events

    review = asyncio.run(run(repo=repo, pr_number=pr_number, token=token, scan_path=scan_path))
    log.info(f"[vera] posted {review['inline_count']} inline + "
             f"{review['summary_count']} summary finding(s) on PR #{pr_number}")

    if os.getenv("VERA_FAIL_ON_CRITICAL", "").lower() in ("1", "true", "yes"):
        criticals = [v for v in review.get("violations", []) if v.get("severity") == "critical"]
        if criticals:
            log.error(f"[vera] {len(criticals)} critical accessibility issue(s) — failing.")
            return 1
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
