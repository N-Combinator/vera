"""
Vera — Code Fixer: applies accessibility fixes to source files.
Uses targeted regex/string replacement + optional LLM-generated fixes.
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


# ── Rule-Specific Fixers ──────────────────────────────────────────────────────

class RuleFixer:
    """Apply deterministic fixes for known rules."""

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

    def _fix_missing_alt(self, content: str, violation: Violation) -> str:
        """Add alt="" to img tags missing alt attribute."""
        # Target the specific line if we have location info
        if violation.location and violation.location.line > 0:
            lines = content.split("\n")
            line_idx = violation.location.line - 1
            if line_idx < len(lines):
                line = lines[line_idx]
                # Add alt attribute before the closing > or />
                fixed_line = re.sub(
                    r'(<img\b(?![^>]*\balt\s*=)[^>]*?)(\s*/?>)',
                    r'\1 alt=""\2',
                    line,
                    flags=re.IGNORECASE,
                )
                if fixed_line != line:
                    lines[line_idx] = fixed_line
                    return "\n".join(lines)

        # Fallback: replace all missing-alt imgs in file
        return re.sub(
            r'(<img\b(?![^>]*\balt\s*=)[^>]*?)(\s*/?>)',
            r'\1 alt=""\2',
            content,
            flags=re.IGNORECASE,
        )

    def _fix_empty_heading(self, content: str, violation: Violation) -> str:
        """Replace empty headings with a TODO comment."""
        pattern = re.compile(r'<(h[1-6])(\b[^>]*)>\s*</h[1-6]>', re.IGNORECASE)
        return pattern.sub(
            r'<\1\2><!-- TODO: Add heading text --></\1>',
            content,
        )

    def _fix_aria_hidden_body(self, content: str) -> str:
        """Remove aria-hidden='true' from body element."""
        return re.sub(
            r'(<body\b[^>]*?)\s*aria-hidden\s*=\s*["\']true["\']([^>]*>)',
            r'\1\2',
            content,
            flags=re.IGNORECASE,
        )

    def _fix_duplicate_id(self, content: str, violation: Violation) -> str:
        """Append -2 suffix to the second occurrence of a duplicate id."""
        match = re.search(r'id\s*=\s*["\']([^"\']+)["\']', violation.element or "")
        if not match:
            return content

        target_id = match.group(1)
        pattern = re.compile(
            r'(\bid\s*=\s*["\'])' + re.escape(target_id) + r'(["\'])',
            re.IGNORECASE,
        )
        occurrences = list(pattern.finditer(content))
        if len(occurrences) < 2:
            return content

        # Fix second occurrence only
        second = occurrences[1]
        return content[:second.start()] + f'id="{target_id}-2"' + content[second.end():]

    def _fix_missing_label(self, content: str, violation: Violation) -> str:
        """Add aria-label to inputs missing accessible labels."""
        if violation.location and violation.location.line > 0:
            lines = content.split("\n")
            line_idx = violation.location.line - 1
            if line_idx < len(lines):
                line = lines[line_idx]
                # Add aria-label before closing bracket
                fixed_line = re.sub(
                    r'(<input\b(?![^>]*(?:aria-label|aria-labelledby|title))[^>]*?)(\s*/?>)',
                    r'\1 aria-label="Field"\2',
                    line,
                    flags=re.IGNORECASE,
                )
                if fixed_line != line:
                    lines[line_idx] = fixed_line
                    return "\n".join(lines)
        return content

    def _fix_label_association(self, content: str, violation: Violation) -> str:
        """Add for attribute to label elements not associated with inputs."""
        if violation.location and violation.location.line > 0:
            lines = content.split("\n")
            line_idx = violation.location.line - 1
            if line_idx < len(lines):
                line = lines[line_idx]
                uid = f"input-{str(uuid.uuid4())[:6]}"
                fixed_line = re.sub(
                    r'(<label\b(?![^>]*\bfor\s*=)[^>]*?)>',
                    f'\\1 for="{uid}">',
                    line,
                    flags=re.IGNORECASE,
                    count=1,
                )
                if fixed_line != line:
                    lines[line_idx] = fixed_line
                    return "\n".join(lines)
        return content

    def _fix_missing_role(self, content: str, violation: Violation) -> str:
        """Add role='button' and tabIndex to interactive divs/spans."""
        if violation.location and violation.location.line > 0:
            lines = content.split("\n")
            line_idx = violation.location.line - 1
            if line_idx < len(lines):
                line = lines[line_idx]
                fixed_line = re.sub(
                    r'(<(?:div|span)\b(?![^>]*\brole\s*=)[^>]*?)(>)',
                    r'\1 role="button" tabIndex={0}\2',
                    line,
                    flags=re.IGNORECASE,
                    count=1,
                )
                if fixed_line != line:
                    lines[line_idx] = fixed_line
                    return "\n".join(lines)
        return content


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
    ) -> FixResponse:
        """Apply fixes for a set of violations from a scan."""
        violations = scan_result.violations
        if violation_ids is not None:
            violations = [v for v in violations if v.id in violation_ids]

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
