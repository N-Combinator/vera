"""
Vera — Scanner: static analysis + optional LLM pass for accessibility violations.
Supports: HTML, JSX, TSX, Vue SFCs.
"""

from __future__ import annotations
import asyncio
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .models import (
    CodeLocation,
    RuleId,
    Severity,
    SEVERITY_MAP,
    ScanResult,
    Violation,
    VeraConfig,
)
from .llm_bridge import LLMBridge

logger = logging.getLogger("vera.scanner")

# ── File Extensions ───────────────────────────────────────────────────────────

SCANNABLE_EXTENSIONS = {".html", ".htm", ".jsx", ".tsx", ".vue", ".svelte", ".js", ".ts"}
CHUNK_SIZE = 120  # lines per LLM chunk

# ── WCAG Criterion Map ────────────────────────────────────────────────────────

WCAG_MAP: Dict[str, str] = {
    RuleId.MISSING_ALT:      "1.1.1",
    RuleId.MISSING_LABEL:    "1.3.1",
    RuleId.COLOR_CONTRAST:   "1.4.3",
    RuleId.ARIA_HIDDEN_BODY: "4.1.2",
    RuleId.DUPLICATE_ID:     "4.1.1",
    RuleId.EMPTY_HEADING:    "2.4.6",
    RuleId.LABEL_ASSOCIATED: "1.3.1",
    RuleId.MISSING_ROLE:     "4.1.2",
    RuleId.KEYBOARD_TRAP:    "2.1.2",
    RuleId.FOCUSABLE_HIDDEN: "4.1.2",
}


# ── Heuristic Rules ───────────────────────────────────────────────────────────

class HeuristicScanner:
    """
    Fast regex/pattern-based accessibility checks.
    Runs without LLM — catches obvious violations reliably.
    """

    def scan(self, content: str, filepath: str) -> List[Violation]:
        violations: List[Violation] = []
        lines = content.split("\n")

        violations.extend(self._check_missing_alt(content, lines, filepath))
        violations.extend(self._check_empty_heading(content, lines, filepath))
        violations.extend(self._check_aria_hidden_body(content, lines, filepath))
        violations.extend(self._check_duplicate_ids(content, lines, filepath))
        violations.extend(self._check_missing_label(content, lines, filepath))
        violations.extend(self._check_label_association(content, lines, filepath))
        violations.extend(self._check_interactive_div(content, lines, filepath))

        return violations

    def _find_line(self, lines: List[str], pattern: re.Pattern, start: int = 0) -> int:
        for i, line in enumerate(lines[start:], start=start):
            if pattern.search(line):
                return i + 1  # 1-indexed
        return 0

    def _make_violation(
        self,
        rule: str,
        element: str,
        description: str,
        suggestion: str,
        filepath: str,
        line: int = 0,
        confidence: float = 0.95,
    ) -> Violation:
        severity = SEVERITY_MAP.get(RuleId(rule), Severity.MODERATE)
        return Violation(
            id=str(uuid.uuid4())[:8],
            rule=rule,
            severity=severity,
            element=element,
            description=description,
            suggestion=suggestion,
            location=CodeLocation(file=filepath, line=line, column=0) if line else None,
            confidence=confidence,
            fix_available=True,
            ai_generated=False,
            wcag_criterion=WCAG_MAP.get(rule),
        )

    def _check_missing_alt(self, content: str, lines: List[str], fp: str) -> List[Violation]:
        violations = []
        # Match <img> tags that don't have alt attribute
        pattern = re.compile(r'<img\b(?![^>]*\balt\s*=)[^>]*/?>', re.IGNORECASE)
        for m in pattern.finditer(content):
            line_num = content[:m.start()].count("\n") + 1
            violations.append(self._make_violation(
                rule=RuleId.MISSING_ALT,
                element="img",
                description=f"Image element is missing an `alt` attribute (line {line_num})",
                suggestion='Add alt="descriptive text" or alt="" for decorative images',
                filepath=fp,
                line=line_num,
            ))
        return violations

    def _check_empty_heading(self, content: str, lines: List[str], fp: str) -> List[Violation]:
        violations = []
        pattern = re.compile(r'<(h[1-6])\b[^>]*>\s*</(h[1-6])>', re.IGNORECASE)
        for m in pattern.finditer(content):
            line_num = content[:m.start()].count("\n") + 1
            violations.append(self._make_violation(
                rule=RuleId.EMPTY_HEADING,
                element=m.group(1),
                description=f"Heading <{m.group(1)}> is empty (line {line_num})",
                suggestion="Add meaningful text content to the heading or remove it",
                filepath=fp,
                line=line_num,
            ))
        return violations

    def _check_aria_hidden_body(self, content: str, lines: List[str], fp: str) -> List[Violation]:
        violations = []
        pattern = re.compile(r'<body\b[^>]*aria-hidden\s*=\s*["\']true["\'][^>]*>', re.IGNORECASE)
        for m in pattern.finditer(content):
            line_num = content[:m.start()].count("\n") + 1
            violations.append(self._make_violation(
                rule=RuleId.ARIA_HIDDEN_BODY,
                element="body",
                description=f"<body> has aria-hidden='true' which hides all content from screen readers",
                suggestion="Remove aria-hidden='true' from the <body> element",
                filepath=fp,
                line=line_num,
                confidence=1.0,
            ))
        return violations

    def _check_duplicate_ids(self, content: str, lines: List[str], fp: str) -> List[Violation]:
        violations = []
        pattern = re.compile(r'\bid\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
        seen: Dict[str, int] = {}
        for m in pattern.finditer(content):
            id_val = m.group(1)
            line_num = content[:m.start()].count("\n") + 1
            if id_val in seen:
                violations.append(self._make_violation(
                    rule=RuleId.DUPLICATE_ID,
                    element=f'[id="{id_val}"]',
                    description=f'Duplicate id="{id_val}" found (first at line {seen[id_val]}, again at line {line_num})',
                    suggestion=f'Rename one of the elements with id="{id_val}" to a unique value',
                    filepath=fp,
                    line=line_num,
                ))
            else:
                seen[id_val] = line_num
        return violations

    def _check_missing_label(self, content: str, lines: List[str], fp: str) -> List[Violation]:
        violations = []
        # Inputs without aria-label, aria-labelledby, or id (for label association)
        input_pattern = re.compile(
            r'<input\b(?![^>]*(?:type\s*=\s*["\'](?:hidden|submit|button|reset|image)["\']))'
            r'(?![^>]*(?:aria-label|aria-labelledby|title)\s*=)[^>]*/?>',
            re.IGNORECASE,
        )
        for m in input_pattern.finditer(content):
            # Check if it has an id for label association (checked separately)
            tag = m.group(0)
            has_id = re.search(r'\bid\s*=\s*["\'][^"\']+["\']', tag, re.IGNORECASE)
            if not has_id:
                line_num = content[:m.start()].count("\n") + 1
                violations.append(self._make_violation(
                    rule=RuleId.MISSING_LABEL,
                    element="input",
                    description=f"Form input is missing an accessible label (line {line_num})",
                    suggestion='Add aria-label="description" or associate a <label> element via id/for',
                    filepath=fp,
                    line=line_num,
                ))
        return violations

    def _check_label_association(self, content: str, lines: List[str], fp: str) -> List[Violation]:
        violations = []
        # <label> without a `for` attribute and no nested input
        label_pattern = re.compile(r'<label\b(?![^>]*\bfor\s*=)[^>]*>(.*?)</label>', re.IGNORECASE | re.DOTALL)
        for m in label_pattern.finditer(content):
            inner = m.group(1)
            # If label wraps an input, it's OK
            if re.search(r'<input\b', inner, re.IGNORECASE):
                continue
            line_num = content[:m.start()].count("\n") + 1
            violations.append(self._make_violation(
                rule=RuleId.LABEL_ASSOCIATED,
                element="label",
                description=f"<label> is not associated with an input via for/id (line {line_num})",
                suggestion='Add for="input-id" to the <label> and id="input-id" to the input',
                filepath=fp,
                line=line_num,
                confidence=0.85,
            ))
        return violations

    def _check_interactive_div(self, content: str, lines: List[str], fp: str) -> List[Violation]:
        """Detect <div onClick> or <span onClick> without role/tabIndex."""
        violations = []
        pattern = re.compile(
            r'<(div|span)\b[^>]*(?:onClick|on-click|v-on:click)[^>]*(?![^>]*(?:role|tabIndex|tabindex))[^>]*>',
            re.IGNORECASE,
        )
        for m in pattern.finditer(content):
            line_num = content[:m.start()].count("\n") + 1
            tag = m.group(1)
            violations.append(self._make_violation(
                rule=RuleId.MISSING_ROLE,
                element=tag,
                description=f"Interactive <{tag}> with click handler is missing role and tabIndex (line {line_num})",
                suggestion=f'Replace with <button> or add role="button" tabIndex="0" and keyboard handler',
                filepath=fp,
                line=line_num,
                confidence=0.8,
            ))
        return violations


# ── Main Scanner ──────────────────────────────────────────────────────────────

class Scanner:
    def __init__(self, config: VeraConfig, llm: Optional[LLMBridge] = None):
        self.config = config
        self.llm = llm
        self.heuristic = HeuristicScanner()

    def _collect_files(self, target: str) -> List[Path]:
        """Recursively collect scannable files from a path."""
        root = Path(target)
        files: List[Path] = []

        if root.is_file():
            if root.suffix in SCANNABLE_EXTENSIONS:
                return [root]
            return []

        ignore = set(self.config.ignore_paths)

        for p in root.rglob("*"):
            if p.is_file() and p.suffix in SCANNABLE_EXTENSIONS:
                # Skip ignored paths
                if any(part in ignore for part in p.parts):
                    continue
                files.append(p)
                if len(files) >= self.config.max_files:
                    break

        return files

    def _chunk_content(self, content: str) -> List[str]:
        """Split large files into overlapping chunks for LLM."""
        lines = content.split("\n")
        chunks = []
        for i in range(0, len(lines), CHUNK_SIZE):
            chunk = "\n".join(lines[i:i + CHUNK_SIZE])
            chunks.append(chunk)
        return chunks

    async def scan(self, target: str) -> ScanResult:
        start = time.time()
        files = self._collect_files(target)
        all_violations: List[Violation] = []

        llm_available = self.llm and await self.llm.is_available()
        llm_provider = self.config.llm.provider if llm_available else None

        logger.info(f"[Scanner] Scanning {len(files)} files in {target} | LLM: {llm_provider or 'disabled'}")

        for filepath in files:
            try:
                content = filepath.read_text(encoding="utf-8", errors="ignore")
            except OSError as e:
                logger.warning(f"[Scanner] Cannot read {filepath}: {e}")
                continue

            rel_path = str(filepath)

            # Heuristic pass (always)
            h_violations = self.heuristic.scan(content, rel_path)
            all_violations.extend(h_violations)

            # LLM pass (optional)
            if llm_available and self.config.llm and self.llm:
                chunks = self._chunk_content(content)
                for chunk in chunks:
                    try:
                        raw_violations = await self.llm.detect_violations(chunk, rel_path)
                        for rv in raw_violations:
                            if rv.get("confidence", 0) < self.config.confidence_threshold:
                                continue
                            rule = rv.get("rule", "unknown")
                            severity = SEVERITY_MAP.get(rule, Severity.MODERATE)
                            v = Violation(
                                rule=rule,
                                severity=severity,
                                element=rv.get("element", "unknown"),
                                description=rv.get("description", ""),
                                suggestion=rv.get("suggestion", ""),
                                confidence=float(rv.get("confidence", 0.7)),
                                fix_available=True,
                                ai_generated=True,
                                wcag_criterion=rv.get("wcag_criterion"),
                                location=CodeLocation(file=rel_path, line=0, column=0),
                            )
                            all_violations.append(v)
                    except Exception as e:
                        logger.warning(f"[Scanner] LLM pass failed for {filepath}: {e}")

        # Deduplicate by (rule, file, line)
        seen_keys: Set[str] = set()
        deduped: List[Violation] = []
        for v in all_violations:
            key = f"{v.rule}:{v.location.file if v.location else ''}:{v.location.line if v.location else 0}"
            if key not in seen_keys:
                seen_keys.add(key)
                deduped.append(v)

        # Filter by requested rules
        if self.config.rules:
            deduped = [v for v in deduped if v.rule in self.config.rules]

        duration_ms = int((time.time() - start) * 1000)

        return ScanResult(
            target=target,
            framework=self.config.framework,
            violations=deduped,
            total_files_scanned=len(files),
            scan_duration_ms=duration_ms,
            llm_provider=llm_provider,
            created_at=__import__("datetime").datetime.utcnow().isoformat() + "Z",
        )
