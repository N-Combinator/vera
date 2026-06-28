# Vera — Code Audit (2026-06-28)

An honest read of the repository: what's solid, and what's worth fixing. Scope:
`src/packages/core/vera/*.py` (Python backend) and `src/packages/cli/src/**` (TS CLI).
This is a review, **not** a refactor — nothing here is changed by this document.

Findings are verified against the code (file:line quoted), de-duplicated across three
independent passes (security / dead-code+duplication / correctness), and cross-checked
against open PR #29 (`feat/fix-quality`) so already-fixed items aren't re-raised.

**Overall:** the architecture is clean and the recently-rebuilt `describe` and `fix`
paths are solid. The real risk concentrates in the FastAPI backend, which is written as
a trusted-local-developer tool but has no guards if ever exposed. No fabricated issues;
where something is actually safe it's stated.

---

## Already addressed in PR #29 (pending merge) — not re-raised

The `code_fixer.py` rebuild on `feat/fix-quality` already fixes: multi-line tag handling
(B1), JSX-vs-HTML output (`tabIndex={0}` no longer injected into HTML), dangling
`for="input-<random>"`, generic `aria-label="Field"`, and blind `alt=""` on informative
images. Those are excluded below.

---

## Security

| # | Sev | Location | Issue |
|---|-----|----------|-------|
| S1 | **High** | `describe.py:288-293` | **SSRF.** `ImageLoader._fetch_bytes` does `httpx.get(src, follow_redirects=True)` on any `http(s)` `src` pulled from scanned HTML. `is_in_scope_src` (`describe.py:249`) only filters JSX/`data:`/empty — it does **not** block `localhost`, private ranges, or cloud metadata `169.254.169.254`. Attacker-supplied HTML can make the server fetch internal endpoints. Mitigated only by `describe` being opt-in + key-gated. **Fix:** resolve host, reject private/loopback/link-local IPs; pin scheme to http(s); cap redirects. |
| S2 | **High** | `code_fixer.py:214-264` (`/fix` → `api.py:126`) | **Arbitrary file write.** `fix_scan` writes `path.write_text(...)` to whatever `filepath` the violations carry, with no sandbox/root jail. A crafted scan/fix request can overwrite files outside the project. **Fix:** resolve paths and confirm they stay under an allowed root before writing. |
| S3 | Med | `api.py:67-73` | **Wildcard CORS** (`allow_origins=["*"]`, `allow_credentials=True`) on `/scan`, `/fix`, `/describe`. Fine for localhost-only; dangerous if bound to `0.0.0.0`. **Resolution:** Vera is a local developer tool — default-bind `127.0.0.1` and restrict CORS to loopback origins. No authentication: it is not a network service. |
| S4 | Med | `describe.py:301-307` | **Local path traversal.** Relative `src` is joined to `base_dir` without normalization, so `src="../../../etc/…"` escapes the base dir. Only reads image bytes (and Pillow will reject non-images), so impact is limited, but still. **Fix:** `resolve()` and verify the result is under `base_dir`. |
| S5 | Low | `api.py:202`, `llm_bridge.py` | API keys may be accepted in request bodies and reach `logger.error(..., exc_info=True)` on failure. No key is deliberately logged, but stack traces can carry header context. **Fix:** prefer env/header over body; redact keys in error paths. |
| S6 | Low | `cli/.../ui.ts:104-110`, `:128-135` | Dashboard static server joins `req.url` without a traversal guard; `openBrowser` builds a shell string. Both are localhost-dev only and the port is numeric, so exploitability is marginal — worth a `resolve()`-under-dir check and `spawn` (array args) for hygiene. |
| S7 | Low | `pr_report.py:181-192` | PR-comment text embeds LLM `description`/`suggestion` into Markdown unescaped. GitHub sandboxes MD, so this is cosmetic-injection at worst. **Fix:** escape before posting if it ever matters. |

---

## Correctness bugs

| # | Sev | Location | Issue |
|---|-----|----------|-------|
| C1 | Med | `scanner.py:217-218` | **Interactive-div false positives.** The `role/tabIndex` negative lookahead sits *after* the `onClick` match, so it only inspects the tag tail. `<div role="button" onClick=…>` (role before handler) is still flagged. **Fix:** anchor the lookahead at the tag start: `<(div\|span)(?![^>]*\b(?:role\|tabindex)\s*=)[^>]*onClick…`. |
| C2 | Med | `scanner.py:330` | **Dedup drops distinct violations.** Key is `rule:file:line`; LLM findings often have no location → key collapses to `rule::0`, so multiple real violations on the same rule are silently merged to one. **Fix:** fall back to `v.id` (or a content hash) when `location` is missing. |
| C3 | Med | `api.py:108` | **Global config mutation.** `cfg = … _config` then `cfg.rules = req.rules` mutates the shared global config, so a `rules` filter from one request leaks into all later scans. **Fix:** copy the config per request before mutating. |
| C4 | Med | `api.py:100-103` | **Connection leak.** A per-request `LLMBridge(custom_llm_cfg)` (and its `httpx.AsyncClient`) is created when `llm_provider` is overridden but never `close()`d. Repeated calls exhaust the pool. **Fix:** close it in a `finally`, or cache bridges by provider. |
| C5 | Low | `config_loader.py:55,66-67` | `int()/float()` on raw config values with no guard — a malformed `.verarc.json` (`"max_files":"abc"`) crashes startup. **Fix:** wrap in try/except with the default. |
| C6 | Low | `describe.py:407-413` | A failed vision call returns `SKIPPED` even when the image has **no** alt — a genuinely missing alt reads as "decorative/ok". **Fix:** return `MISSING` when `not img.has_alt_attr`, else `SKIPPED`. |
| C7 | Nit | `llm_bridge.py:305-309` | JSON-array slice relies on `end > start` while `end` can be `-1`; works today but fragile. Add an explicit `end != -1` check. |

---

## Dead code & inconsistencies

| # | Location | Issue |
|---|----------|-------|
| D1 | `models.py` `RuleId.KEYBOARD_TRAP`, `FOCUSABLE_HIDDEN` | Advertised in the rule/severity/WCAG maps **and the README table**, but `HeuristicScanner.scan` (`scanner.py:61-67`) never checks them and there's no fixer. They can only appear via the LLM. Either implement, or mark them LLM-only in docs. |
| D2 | `scanner.py` `color-contrast` | Same: listed in `WCAG_MAP`/`SEVERITY_MAP` and README, but there is **no** heuristic detector (`grep contrast scanner.py` → none). Contrast needs real luminance math; today it's LLM-only. Document that, or implement it. |
| D3 | `scanner.py:71` `_find_line()` | Defined, **zero** callers in the repo. Dead — remove. |
| D4 | `scanner.py:7`, `api.py:7` | `import asyncio` — unused in both files. Remove. |
| D5 | `models.py:65` `Violation.code_snippet` | Field declared but never populated by scanner/fixer nor read by API/CLI. Wire it up or drop it. |
| D6 | `describe.py:322-323,335-336` | `from io import BytesIO` / `from PIL import Image` imported twice inside one method — hoist to module top. |
| D7 | `llm_bridge.py` provider methods | `_ollama/_openai/_anthropic/_openrouter_complete` repeat the same post-payload-parse shape 4×; OpenRouter also omits `max_tokens` that the others send. Candidate for one `_call_provider` helper (also closes the inconsistency). |
| D8 | `llm_bridge.py` ↔ `describe.py` | Identical "parse JSON, else slice `{…}`" logic in both — extract a shared `_safe_json_parse`. |
| D9 | `cli/.../init.ts:72` | Default Anthropic model is the dated `claude-3-haiku-20240307`. Refresh to a current id. |

---

## Bottom line

Nothing here blocks the current `describe`/`fix` work. Priorities if/when this backend is
exposed beyond localhost: **S1 (SSRF)** and **S2 (arbitrary write)** first, then the
backend hygiene set **S3/C3/C4**. The dead-rule items (**D1/D2**) are low-effort but matter
for honesty — the tool currently advertises three WCAG rules it doesn't actually detect
without an LLM.
