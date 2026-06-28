"""
Vera — Scanner: static analysis + optional LLM pass for accessibility violations.
Supports: HTML, JSX, TSX, Vue SFCs.

The heuristic pass is built on a real parsed element tree (stdlib ``html.parser``),
not line-by-line regex. Detectors walk the tree, so they are multi-line-tag safe,
attribute-order independent, and nesting-aware (a label that *wraps* its input, a
heading whose text lives in a child span) — the things regex got wrong (audit B1/C1).
"""

from __future__ import annotations
import logging
import time
import uuid
from html.parser import HTMLParser
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

# HTML void elements — they never get pushed onto the open-element stack.
_VOID_TAGS = {
    "img", "input", "br", "hr", "meta", "link", "area",
    "base", "col", "embed", "source", "track", "wbr",
}

# input types that don't need a visible label
_UNLABELLED_INPUT_TYPES = {"hidden", "submit", "button", "reset", "image"}

# attributes that signal an element handles a click (HTML, JSX, Vue, Angular)
_CLICK_ATTRS = ("onclick", "on-click", "v-on:click", "@click", "(click)")

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

_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


# ── Parsed element tree ───────────────────────────────────────────────────────

class _Node:
    """A single parsed element with its position, attributes, and children."""
    __slots__ = ("tag", "attrs", "line", "children", "parent", "text")

    def __init__(self, tag: str, attrs: Dict[str, str], line: int, parent: Optional["_Node"]):
        self.tag = tag
        self.attrs = attrs
        self.line = line
        self.parent = parent
        self.children: List["_Node"] = []
        self.text = ""        # direct text content of this element

    def has(self, attr: str) -> bool:
        return attr in self.attrs

    def descendants(self):
        for c in self.children:
            yield c
            yield from c.descendants()

    def descendant_text(self) -> str:
        parts = [self.text]
        for d in self.descendants():
            parts.append(d.text)
        return "".join(parts).strip()


class _TreeBuilder(HTMLParser):
    """Build a lightweight element tree, tolerant of JSX/Vue-ish markup."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", {}, 0, None)
        self.stack: List[_Node] = [self.root]
        self.nodes: List[_Node] = []   # every element, in document order

    @staticmethod
    def _to_dict(attrs) -> Dict[str, str]:
        d: Dict[str, str] = {}
        for k, v in attrs:
            d[k.lower()] = v if v is not None else ""
        return d

    def _open(self, tag: str, attrs, self_closing: bool):
        line = self.getpos()[0]
        node = _Node(tag.lower(), self._to_dict(attrs), line, self.stack[-1])
        self.stack[-1].children.append(node)
        self.nodes.append(node)
        if not self_closing and tag.lower() not in _VOID_TAGS:
            self.stack.append(node)

    def handle_starttag(self, tag, attrs):
        self._open(tag, attrs, self_closing=False)

    def handle_startendtag(self, tag, attrs):
        self._open(tag, attrs, self_closing=True)

    def handle_endtag(self, tag):
        tag = tag.lower()
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        if data.strip():
            self.stack[-1].text += data


def _build_tree(content: str) -> _TreeBuilder:
    builder = _TreeBuilder()
    try:
        builder.feed(content)
        builder.close()
    except Exception as e:   # malformed markup must never crash a scan
        logger.warning(f"[Scanner] parse stopped early: {e}")
    return builder


# ── Heuristic Rules ───────────────────────────────────────────────────────────

class HeuristicScanner:
    """Fast, tree-based accessibility checks. Runs without an LLM."""

    def scan(self, content: str, filepath: str) -> List[Violation]:
        tree = _build_tree(content)
        nodes = tree.nodes
        violations: List[Violation] = []
        violations.extend(self._check_missing_alt(nodes, filepath))
        violations.extend(self._check_empty_heading(nodes, filepath))
        violations.extend(self._check_aria_hidden_body(nodes, filepath))
        violations.extend(self._check_duplicate_ids(nodes, filepath))
        violations.extend(self._check_missing_label(nodes, filepath))
        violations.extend(self._check_label_association(nodes, filepath))
        violations.extend(self._check_interactive(nodes, filepath))
        return violations

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

    def _check_missing_alt(self, nodes: List[_Node], fp: str) -> List[Violation]:
        out = []
        for n in nodes:
            if n.tag == "img" and not n.has("alt"):
                out.append(self._make_violation(
                    rule=RuleId.MISSING_ALT,
                    element="img",
                    description=f"Image element is missing an `alt` attribute (line {n.line})",
                    suggestion='Add alt="descriptive text" or alt="" for decorative images',
                    filepath=fp, line=n.line,
                ))
        return out

    def _check_empty_heading(self, nodes: List[_Node], fp: str) -> List[Violation]:
        out = []
        for n in nodes:
            if n.tag not in _HEADING_TAGS:
                continue
            # A heading is fine if it has any text (even nested) or an image that
            # carries an accessible name (img with non-empty alt).
            if n.descendant_text():
                continue
            if any(d.tag == "img" and d.attrs.get("alt") for d in n.descendants()):
                continue
            out.append(self._make_violation(
                rule=RuleId.EMPTY_HEADING,
                element=n.tag,
                description=f"Heading <{n.tag}> is empty (line {n.line})",
                suggestion="Add meaningful text content to the heading or remove it",
                filepath=fp, line=n.line,
            ))
        return out

    def _check_aria_hidden_body(self, nodes: List[_Node], fp: str) -> List[Violation]:
        out = []
        for n in nodes:
            if n.tag == "body" and n.attrs.get("aria-hidden", "").lower() in ("true", "{true}"):
                out.append(self._make_violation(
                    rule=RuleId.ARIA_HIDDEN_BODY,
                    element="body",
                    description="<body> has aria-hidden='true' which hides all content from screen readers",
                    suggestion="Remove aria-hidden='true' from the <body> element",
                    filepath=fp, line=n.line, confidence=1.0,
                ))
        return out

    def _check_duplicate_ids(self, nodes: List[_Node], fp: str) -> List[Violation]:
        out = []
        seen: Dict[str, int] = {}
        for n in nodes:
            id_val = n.attrs.get("id")
            if not id_val or id_val.startswith("{"):   # skip JSX dynamic ids
                continue
            if id_val in seen:
                out.append(self._make_violation(
                    rule=RuleId.DUPLICATE_ID,
                    element=f'[id="{id_val}"]',
                    description=f'Duplicate id="{id_val}" found (first at line {seen[id_val]}, again at line {n.line})',
                    suggestion=f'Rename one of the elements with id="{id_val}" to a unique value',
                    filepath=fp, line=n.line,
                ))
            else:
                seen[id_val] = n.line
        return out

    def _check_missing_label(self, nodes: List[_Node], fp: str) -> List[Violation]:
        out = []
        for n in nodes:
            if n.tag != "input":
                continue
            if n.attrs.get("type", "").lower() in _UNLABELLED_INPUT_TYPES:
                continue
            if n.has("aria-label") or n.has("aria-labelledby") or n.has("title"):
                continue
            # an id lets a <label for> name it (handled by label-association);
            # being wrapped by a label with text also names it.
            if n.has("id"):
                continue
            if self._wrapped_by_label_with_text(n):
                continue
            out.append(self._make_violation(
                rule=RuleId.MISSING_LABEL,
                element="input",
                description=f"Form input is missing an accessible label (line {n.line})",
                suggestion='Add aria-label="description" or associate a <label> element via id/for',
                filepath=fp, line=n.line,
            ))
        return out

    @staticmethod
    def _wrapped_by_label_with_text(n: _Node) -> bool:
        p = n.parent
        while p is not None:
            if p.tag == "label" and p.descendant_text():
                return True
            p = p.parent
        return False

    def _check_label_association(self, nodes: List[_Node], fp: str) -> List[Violation]:
        out = []
        for n in nodes:
            if n.tag != "label" or n.has("for"):
                continue
            # OK if it wraps its control (implicit association).
            if any(d.tag in ("input", "select", "textarea") for d in n.descendants()):
                continue
            out.append(self._make_violation(
                rule=RuleId.LABEL_ASSOCIATED,
                element="label",
                description=f"<label> is not associated with an input via for/id (line {n.line})",
                suggestion='Add for="input-id" to the <label> and id="input-id" to the input',
                filepath=fp, line=n.line, confidence=0.85,
            ))
        return out

    def _check_interactive(self, nodes: List[_Node], fp: str) -> List[Violation]:
        """<div>/<span> with a click handler but no role/tabindex — keyboard-inaccessible."""
        out = []
        for n in nodes:
            if n.tag not in ("div", "span"):
                continue
            if not any(n.has(a) for a in _CLICK_ATTRS):
                continue
            # attribute-order independent (fixes audit C1): check the element's own attrs
            if n.has("role") or n.has("tabindex"):
                continue
            out.append(self._make_violation(
                rule=RuleId.MISSING_ROLE,
                element=n.tag,
                description=f"Interactive <{n.tag}> with click handler is missing role and tabIndex (line {n.line})",
                suggestion='Replace with <button> or add role="button" tabIndex="0" and a keyboard handler',
                filepath=fp, line=n.line, confidence=0.8,
            ))
        return out


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
                if any(part in ignore for part in p.parts):
                    continue
                files.append(p)
                if len(files) >= self.config.max_files:
                    break

        return files

    def _chunk_content(self, content: str) -> List[str]:
        """Split large files into chunks for the LLM."""
        lines = content.split("\n")
        return ["\n".join(lines[i:i + CHUNK_SIZE]) for i in range(0, len(lines), CHUNK_SIZE)]

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
            all_violations.extend(self.heuristic.scan(content, rel_path))

            # LLM pass (optional)
            if llm_available and self.config.llm and self.llm:
                for chunk in self._chunk_content(content):
                    try:
                        raw_violations = await self.llm.detect_violations(chunk, rel_path)
                        for rv in raw_violations:
                            if rv.get("confidence", 0) < self.config.confidence_threshold:
                                continue
                            rule = rv.get("rule", "unknown")
                            severity = SEVERITY_MAP.get(rule, Severity.MODERATE)
                            all_violations.append(Violation(
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
                            ))
                    except Exception as e:
                        logger.warning(f"[Scanner] LLM pass failed for {filepath}: {e}")

        deduped = self._dedupe(all_violations)

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

    @staticmethod
    def _dedupe(violations: List[Violation]) -> List[Violation]:
        """Drop exact (rule, file, line) repeats. Violations with no real location
        (e.g. LLM findings at line 0) keep their own id in the key so distinct
        findings are never silently merged (audit C2)."""
        seen: Set[str] = set()
        out: List[Violation] = []
        for v in violations:
            if v.location and v.location.line > 0:
                key = f"{v.rule}:{v.location.file}:{v.location.line}"
            else:
                key = f"{v.rule}:noloc:{v.id}"
            if key not in seen:
                seen.add(key)
                out.append(v)
        return out
