"""
Vera — Code Fixer: applies accessibility fixes to source files.

Deterministic, standards-aware fixes. The guiding rule is *never emit a fix that
is wrong* — a fixer that cannot produce a correct, WCAG-valid result for a given
violation returns ``None`` (the violation is left for ``vera describe`` or a human)
rather than writing a plausible-but-harmful change. Optional LLM-generated fixes
fill the gaps when a bridge is configured.
"""

from __future__ import annotations
import difflib
import logging
import re
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .models import Fix, FixResponse, RuleId, ScanResult, Violation
from .llm_bridge import LLMBridge

logger = logging.getLogger("vera.fixer")


# ── Tag-region helpers (multi-line safe — fixes B1) ───────────────────────────

def _line_start_offset(content: str, line: int) -> int:
    """Character offset of the start of a 1-based line."""
    if line <= 1:
        return 0
    off = 0
    seen = 0
    for i, ch in enumerate(content):
        if ch == "\n":
            seen += 1
            if seen == line - 1:
                return i + 1
    return len(content)


def _find_tag(content: str, search_from: int, tagnames: List[str]) -> Optional[Tuple[int, int]]:
    """
    Locate the earliest opening tag among ``tagnames`` at/after ``search_from`` and
    return ``(start, end)`` offsets spanning the WHOLE opening tag — from ``<tag``
    through its closing ``>`` — even if the tag spans several physical lines.

    Quote-aware so a ``>`` inside an attribute value does not terminate the tag.
    """
    best: Optional[int] = None
    for t in tagnames:
        m = re.compile(r"<" + re.escape(t) + r"\b", re.IGNORECASE).search(content, search_from)
        if m and (best is None or m.start() < best):
            best = m.start()
    if best is None:
        return None

    i = best
    quote: Optional[str] = None
    while i < len(content):
        c = content[i]
        if quote:
            if c == quote:
                quote = None
        elif c in ("\"", "'"):
            quote = c
        elif c == ">":
            return best, i + 1
        i += 1
    return None  # unterminated tag


def _get_attr(tag: str, name: str) -> Optional[str]:
    """Return the value of attribute ``name`` in ``tag`` (quoted forms), else None."""
    m = re.search(
        r"\b" + re.escape(name) + r"\s*=\s*\"([^\"]*)\"",
        tag, re.IGNORECASE,
    ) or re.search(
        r"\b" + re.escape(name) + r"\s*=\s*'([^']*)'",
        tag, re.IGNORECASE,
    )
    return m.group(1) if m else None


def _has_attr(tag: str, name: str) -> bool:
    return re.search(r"\b" + re.escape(name) + r"\s*=", tag, re.IGNORECASE) is not None


def _inject_attr(tag: str, attr: str) -> str:
    """Insert ``attr`` immediately before the tag's closing ``>`` or ``/>``."""
    return re.sub(r"(\s*/?>)\s*$", " " + attr + r"\1", tag, count=1)


def _escape_attr(value: str) -> str:
    """Escape a string for safe use inside a double-quoted HTML attribute."""
    return value.replace("&", "&amp;").replace("\"", "&quot;").replace("<", "&lt;")


def _resolve_root(target: Optional[str]) -> Optional[Path]:
    """The directory writes are jailed to: the target itself if a dir, else its parent."""
    if not target:
        return None
    try:
        p = Path(target).resolve()
    except Exception:
        return None
    return p if p.is_dir() else p.parent


def _within_root(path: Path, root: Path) -> bool:
    """True if ``path`` resolves to a location inside ``root`` (blocks ../ traversal)."""
    try:
        resolved = path.resolve()
    except Exception:
        return False
    return resolved == root or root in resolved.parents


def _is_jsx(filepath: Optional[str]) -> bool:
    return bool(filepath) and filepath.lower().endswith((".jsx", ".tsx"))


# ── Rule-Specific Fixers ──────────────────────────────────────────────────────

class RuleFixer:
    """Apply deterministic, standards-correct fixes for known rules."""

    # hosts whose 1x1 / noscript images are tracking pixels, not content
    _TRACKING_HOSTS = (
        "facebook.com", "google-analytics.com", "googletagmanager.com",
        "doubleclick.net", "google.com/ads", "analytics", "/tr?", "pixel",
    )

    def fix(self, violation: Violation, content: str) -> Optional[str]:
        rule = violation.rule
        try:
            if rule == RuleId.MISSING_ALT:
                return self._fix_missing_alt(content, violation)
            elif rule == RuleId.EMPTY_HEADING:
                return self._fix_empty_heading(content, violation)
            elif rule == RuleId.ARIA_HIDDEN_BODY:
                return self._fix_aria_hidden_body(content)
            elif rule == RuleId.DUPLICATE_ID:
                return self._fix_duplicate_id(content, violation)
            elif rule == RuleId.MISSING_LABEL:
                return self._fix_missing_label(content, violation)
            elif rule == RuleId.LABEL_ASSOCIATED:
                return self._fix_label_association(content, violation)
            elif rule == RuleId.MISSING_ROLE:
                return self._fix_missing_role(content, violation)
        except Exception as e:
            logger.warning(f"[Fixer] Rule fix failed for {rule}: {e}")
        return None

    # ── helpers ───────────────────────────────────────────────────────────────

    def _locate_tag(self, content: str, violation: Violation, tagnames: List[str]) -> Optional[Tuple[int, int]]:
        """Find the tag this violation points at, starting from its line."""
        if not (violation.location and violation.location.line > 0):
            return None
        off = _line_start_offset(content, violation.location.line)
        return _find_tag(content, off, tagnames)

    def _is_decorative_img(self, tag: str) -> bool:
        """
        True only when an <img> is *safe* to mark decorative with alt="".
        Conservative on purpose: an informative image wrongly marked decorative
        is hidden from screen readers, which is worse than the original warning.
        """
        if _get_attr(tag, "role") in ("presentation", "none"):
            return True
        if _get_attr(tag, "aria-hidden") == "true":
            return True
        w, h = _get_attr(tag, "width"), _get_attr(tag, "height")
        if w in ("1", "0") and h in ("1", "0"):
            return True  # tracking pixel
        src = (_get_attr(tag, "src") or "").lower()
        if any(host in src for host in self._TRACKING_HOSTS):
            return True
        return False

    def _derive_label(self, tag: str) -> Optional[str]:
        """
        Derive a meaningful accessible name from the control's own attributes,
        in priority order. Returns None if nothing usable is present (caller then
        skips rather than inventing a generic 'Field').
        """
        for attr in ("placeholder", "title", "name"):
            val = _get_attr(tag, attr)
            if val and val.strip():
                val = val.strip()
                if attr == "name":
                    val = re.sub(r"[_\-\[\]]+", " ", val).strip()
                    if not val:
                        continue
                    val = val[0].upper() + val[1:]
                return val
        return None

    # ── fixers ──────────────────────────────────────────────────────────────--

    def _fix_missing_alt(self, content: str, violation: Violation) -> Optional[str]:
        """
        Add alt="" to a <img> ONLY when the image is decorative (tracking pixel,
        role=presentation, aria-hidden). Informative images are deferred to
        `vera describe` — we never silently hide content behind an empty alt.
        """
        span = self._locate_tag(content, violation, ["img"])
        if not span:
            return None
        s, e = span
        tag = content[s:e]
        if _has_attr(tag, "alt"):
            return None
        if not self._is_decorative_img(tag):
            return None  # informative → defer to describe, do not fake it
        new_tag = _inject_attr(tag, 'alt=""')
        if new_tag == tag:
            return None
        return content[:s] + new_tag + content[e:]

    def _fix_missing_label(self, content: str, violation: Violation) -> Optional[str]:
        """Add an aria-label derived from placeholder/title/name to an unlabelled control."""
        span = self._locate_tag(content, violation, ["input", "select", "textarea"])
        if not span:
            return None
        s, e = span
        tag = content[s:e]
        if _has_attr(tag, "aria-label") or _has_attr(tag, "aria-labelledby") or _has_attr(tag, "title"):
            return None
        label = self._derive_label(tag)
        if not label:
            return None  # no honest label source → leave for describe/human
        new_tag = _inject_attr(tag, f'aria-label="{_escape_attr(label)}"')
        if new_tag == tag:
            return None
        return content[:s] + new_tag + content[e:]

    def _fix_label_association(self, content: str, violation: Violation) -> Optional[str]:
        """
        Wire a <label> to its control with a REAL shared id. Resolves the input
        that follows the label (within a small window); reuses the input's id if it
        has one, otherwise injects one shared id on both. If no control can be
        resolved, returns None instead of emitting a dangling `for`.
        """
        span = self._locate_tag(content, violation, ["label"])
        if not span:
            return None
        ls, le = span
        label_tag = content[ls:le]
        if _has_attr(label_tag, "for"):
            return None

        # find the control this label most likely names: nearest following input
        window = content[le:le + 400]
        ctrl = _find_tag(window, 0, ["input", "select", "textarea"])
        if not ctrl:
            return None
        cs, ce = ctrl[0] + le, ctrl[1] + le
        ctrl_tag = content[cs:ce]

        target_id = _get_attr(ctrl_tag, "id")
        edits: List[Tuple[int, int, str]] = []
        if not target_id:
            target_id = f"input-{uuid.uuid4().hex[:6]}"
            edits.append((cs, ce, _inject_attr(ctrl_tag, f'id="{target_id}"')))
        edits.append((ls, le, _inject_attr(label_tag, f'for="{_escape_attr(target_id)}"')))

        # apply later offsets first so earlier offsets stay valid
        new = content
        for st, en, rep in sorted(edits, key=lambda x: -x[0]):
            new = new[:st] + rep + new[en:]
        return new if new != content else None

    def _fix_missing_role(self, content: str, violation: Violation) -> Optional[str]:
        """Add role='button' + a keyboard-focusable index to an interactive div/span."""
        span = self._locate_tag(content, violation, ["div", "span"])
        if not span:
            return None
        s, e = span
        tag = content[s:e]
        if _has_attr(tag, "role"):
            return None
        # JSX needs camelCase tabIndex={0}; HTML/Vue need tabindex="0"
        fp = violation.location.file if violation.location else None
        tabindex = "tabIndex={0}" if _is_jsx(fp) else 'tabindex="0"'
        new_tag = _inject_attr(tag, f'role="button" {tabindex}')
        if new_tag == tag:
            return None
        return content[:s] + new_tag + content[e:]

    def _fix_empty_heading(self, content: str, violation: Violation) -> Optional[str]:
        """Flag an empty heading with a framework-correct placeholder comment."""
        fp = violation.location.file if violation.location else None
        if _is_jsx(fp):
            todo = "{/* TODO: Add heading text */}"
        else:
            todo = "<!-- TODO: Add heading text -->"
        pattern = re.compile(r"<(h[1-6])(\b[^>]*)>\s*</h[1-6]>", re.IGNORECASE)
        new = pattern.sub(rf"<\1\2>{todo}</\1>", content)
        return new if new != content else None

    def _fix_aria_hidden_body(self, content: str) -> Optional[str]:
        new = re.sub(
            r'(<body\b[^>]*?)\s*aria-hidden\s*=\s*["\']true["\']([^>]*>)',
            r"\1\2",
            content,
            flags=re.IGNORECASE,
        )
        return new if new != content else None

    def _fix_duplicate_id(self, content: str, violation: Violation) -> Optional[str]:
        """Append -2 to the second occurrence of a duplicated id."""
        match = re.search(r'id\s*=\s*["\']([^"\']+)["\']', violation.element or "")
        if not match:
            return None
        target_id = match.group(1)
        pattern = re.compile(
            r'(\bid\s*=\s*["\'])' + re.escape(target_id) + r'(["\'])',
            re.IGNORECASE,
        )
        occurrences = list(pattern.finditer(content))
        if len(occurrences) < 2:
            return None
        second = occurrences[1]
        return content[:second.start()] + f'id="{target_id}-2"' + content[second.end():]


# ── Diff Generation ───────────────────────────────────────────────────────────

def generate_diff(original: str, fixed: str, filename: str = "file") -> str:
    orig_lines = original.splitlines(keepends=True)
    fixed_lines = fixed.splitlines(keepends=True)
    diff = difflib.unified_diff(
        orig_lines,
        fixed_lines,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
        lineterm="",
    )
    return "".join(diff)


# ── Main Fixer ────────────────────────────────────────────────────────────────

class CodeFixer:
    def __init__(self, llm: Optional[LLMBridge] = None):
        self.rule_fixer = RuleFixer()
        self.llm = llm

    async def fix_scan(
        self,
        scan_result: ScanResult,
        violation_ids: Optional[List[str]],
        dry_run: bool = False,
        root: Optional[str] = None,
    ) -> FixResponse:
        """Apply fixes for a set of violations from a scan.

        ``root`` jails all writes: any target file resolving outside it is
        skipped (security S2). Defaults to the scan target's directory.
        """
        violations = scan_result.violations
        if violation_ids is not None:
            violations = [v for v in violations if v.id in violation_ids]

        allowed_root = _resolve_root(root if root is not None else scan_result.target)

        # Group violations by file
        by_file: Dict[str, List[Violation]] = {}
        for v in violations:
            fp = v.location.file if v.location else scan_result.target
            by_file.setdefault(fp, []).append(v)

        all_fixes: List[Fix] = []
        errors: List[str] = []
        applied_count = 0
        skipped_count = 0

        for filepath, file_violations in by_file.items():
            try:
                path = Path(filepath)
                if allowed_root is not None and not _within_root(path, allowed_root):
                    errors.append(f"Refused to fix outside root: {filepath}")
                    skipped_count += len(file_violations)
                    continue
                if not path.exists():
                    errors.append(f"File not found: {filepath}")
                    skipped_count += len(file_violations)
                    continue

                content = path.read_text(encoding="utf-8", errors="ignore")
                current_content = content

                for violation in file_violations:
                    original_snippet = self._extract_snippet(current_content, violation)

                    # Try deterministic fix first
                    fixed_content = self.rule_fixer.fix(violation, current_content)

                    # Fall back to LLM fix if available and deterministic failed
                    if fixed_content is None and self.llm:
                        try:
                            llm_available = await self.llm.is_available()
                            if llm_available:
                                fixed_snippet = await self.llm.generate_fix(
                                    violation, original_snippet
                                )
                                if fixed_snippet and fixed_snippet != original_snippet:
                                    fixed_content = current_content.replace(
                                        original_snippet, fixed_snippet, 1
                                    )
                        except Exception as e:
                            logger.warning(f"[Fixer] LLM fix failed: {e}")

                    if fixed_content is None or fixed_content == current_content:
                        skipped_count += 1
                        continue

                    diff = generate_diff(current_content, fixed_content, path.name)
                    fix = Fix(
                        violation_id=violation.id,
                        file=filepath,
                        original_code=original_snippet,
                        fixed_code=self._extract_snippet(fixed_content, violation),
                        description=f"Auto-fix for: {violation.description}",
                        applied=not dry_run,
                        diff=diff,
                    )
                    all_fixes.append(fix)
                    current_content = fixed_content
                    applied_count += 1

                # Write file if not dry run
                if not dry_run and current_content != content:
                    path.write_text(current_content, encoding="utf-8")
                    logger.info(f"[Fixer] Fixed {applied_count} violations in {filepath}")

            except Exception as e:
                errors.append(f"Error processing {filepath}: {str(e)}")
                logger.error(f"[Fixer] Error processing {filepath}: {e}", exc_info=True)

        return FixResponse(
            fixes_applied=applied_count if not dry_run else 0,
            fixes_skipped=skipped_count,
            fixes=all_fixes,
            errors=errors,
        )

    def _extract_snippet(self, content: str, violation: Violation, context_lines: int = 3) -> str:
        """Extract a code snippet around the violation's location."""
        if not violation.location or violation.location.line == 0:
            return content[:500]  # fallback: first 500 chars

        lines = content.split("\n")
        line_idx = violation.location.line - 1
        start = max(0, line_idx - context_lines)
        end = min(len(lines), line_idx + context_lines + 1)
        return "\n".join(lines[start:end])
