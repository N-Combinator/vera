"""
Vera-Describe — opt-in AI alt-text quality module (WCAG 1.1.1, Non-text Content).

Pipeline per <img>:
  extract (tag + a11y context) → classify role (decorative is never described)
  → load image (httpx / local, validated via Pillow) → Claude Vision evaluates the
  *existing* alt against the real pixels by a rubric → verdict pass | weak | missing
  (+ suggested_alt).

Guarantees:
  * Opt-in only (caller passes the flag; no behaviour change otherwise).
  * SUGGEST-ONLY — this module never writes files and never auto-applies alt text.
  * Decorative images (aria-hidden, explicit empty alt, role=presentation/none) are
    classified and skipped, never described — over-describing decoration is itself a
    WCAG failure.

Out of MVP scope (skipped gracefully, never crash): data: URIs, CSS backgrounds,
<svg>/<canvas>, bundler imports (`import x from './a.png'`), auto-PR, batch crawl.
"""

from __future__ import annotations

import base64
import logging
import re
from enum import Enum
from pathlib import Path
from typing import List, Optional
from urllib.parse import urljoin, urlparse

from pydantic import BaseModel, Field

logger = logging.getLogger("vera.describe")

# ── Constants ──────────────────────────────────────────────────────────────────

MAX_IMAGE_BYTES = 5 * 1024 * 1024          # Claude vision practical limit
SUPPORTED_FORMATS = {"png", "jpeg", "jpg", "gif", "webp"}
_NEARBY_TEXT_CHARS = 160                     # context window around the tag


# ── Models ─────────────────────────────────────────────────────────────────────

class ImageRole(str, Enum):
    DECORATIVE  = "decorative"   # conveys nothing; must be skipped (never described)
    INFORMATIVE = "informative"  # conveys content; needs descriptive alt
    FUNCTIONAL  = "functional"   # inside a link/button; alt must describe the action
    COMPLEX     = "complex"      # chart/diagram; needs short alt + long description


class AltVerdict(str, Enum):
    PASS    = "pass"      # existing alt is adequate
    WEAK    = "weak"      # alt present but low quality (filename/generic/inaccurate)
    MISSING = "missing"   # no usable alt on a non-decorative image
    SKIPPED = "skipped"   # decorative or out-of-scope source — intentionally untouched


class ImageRef(BaseModel):
    """A single <img> occurrence plus the accessibility context around it."""
    src: str
    raw_tag: str
    file: str
    line: int = 0
    has_alt_attr: bool = False          # distinguishes alt="" from no alt at all
    alt: Optional[str] = None           # the attribute value (may be "")
    aria_hidden: bool = False
    role: Optional[str] = None
    in_link_or_button: bool = False
    in_figure: bool = False
    figcaption: Optional[str] = None
    nearby_text: str = ""


class AltEvaluation(BaseModel):
    """Result of evaluating one image's alt text (suggest-only)."""
    src: str
    file: str
    line: int = 0
    role: ImageRole
    verdict: AltVerdict
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    reasons: List[str] = []
    existing_alt: Optional[str] = None
    suggested_alt: Optional[str] = None
    note: Optional[str] = None          # e.g. why it was skipped


class DescribeReport(BaseModel):
    target: str
    images_found: int = 0
    evaluations: List[AltEvaluation] = []

    @property
    def passed(self) -> int:
        return sum(1 for e in self.evaluations if e.verdict == AltVerdict.PASS)

    @property
    def weak(self) -> int:
        return sum(1 for e in self.evaluations if e.verdict == AltVerdict.WEAK)

    @property
    def missing(self) -> int:
        return sum(1 for e in self.evaluations if e.verdict == AltVerdict.MISSING)

    @property
    def skipped(self) -> int:
        return sum(1 for e in self.evaluations if e.verdict == AltVerdict.SKIPPED)

    def human_summary(self) -> str:
        lines = [
            f"Vera-Describe — {self.target}",
            f"  images: {self.images_found} | "
            f"pass: {self.passed} | weak: {self.weak} | "
            f"missing: {self.missing} | skipped: {self.skipped}",
        ]
        for e in self.evaluations:
            if e.verdict in (AltVerdict.WEAK, AltVerdict.MISSING):
                tag = "✗" if e.verdict == AltVerdict.MISSING else "△"
                lines.append(f"  {tag} [{e.verdict.value}] {e.src} ({e.role.value})")
                if e.suggested_alt:
                    lines.append(f'      suggested: alt="{e.suggested_alt}"')
        return "\n".join(lines)


# ── Extraction ─────────────────────────────────────────────────────────────────
#
# Lesson from the Vera audit (bug B1): detectors must operate on the whole content,
# NOT line-by-line, or multi-line tags are silently missed. `[^>]` matches newlines,
# so a single finditer over the full text catches multi-line <img ...> reliably.

_IMG_RE = re.compile(r"<img\b[^>]*?/?>", re.IGNORECASE | re.DOTALL)
_ATTR_RE = re.compile(
    r"""([a-zA-Z_:][-a-zA-Z0-9_:]*)\s*=\s*("([^"]*)"|'([^']*)'|\{([^}]*)\})""",
)
_FIGURE_OPEN_RE = re.compile(r"<figure\b", re.IGNORECASE)
_FIGURE_CLOSE_RE = re.compile(r"</figure>", re.IGNORECASE)
_FIGCAPTION_RE = re.compile(
    r"<figcaption\b[^>]*>(.*?)</figcaption>", re.IGNORECASE | re.DOTALL
)
_LINKBTN_OPEN_RE = re.compile(r"<(a|button)\b", re.IGNORECASE)
_LINKBTN_CLOSE_RE = re.compile(r"</(a|button)>", re.IGNORECASE)
_TAG_STRIP_RE = re.compile(r"<[^>]+>")


def _parse_attrs(tag: str) -> dict:
    """Return {attr: value}. JSX expression values ({...}) are kept as the raw
    expression string so we can tell `alt={x}` (dynamic) from `alt=""`/missing."""
    attrs: dict = {}
    for m in _ATTR_RE.finditer(tag):
        name = m.group(1).lower()
        if m.group(3) is not None:
            val = m.group(3)
        elif m.group(4) is not None:
            val = m.group(4)
        else:
            val = "{" + (m.group(5) or "") + "}"   # JSX expression, marked
        attrs[name] = val
    return attrs


def _enclosed(content: str, pos: int, open_re: re.Pattern, close_re: re.Pattern) -> bool:
    """True if `pos` sits inside the nearest open/close pair of the given element."""
    last_open = None
    for m in open_re.finditer(content, 0, pos):
        last_open = m.start()
    if last_open is None:
        return False
    close = close_re.search(content, last_open, pos)
    return close is None  # opened before pos and not yet closed → still inside


def extract_images(content: str, filepath: str = "unknown") -> List[ImageRef]:
    """Find every <img> in HTML/JSX content with its accessibility context."""
    refs: List[ImageRef] = []
    for m in _IMG_RE.finditer(content):
        tag = m.group(0)
        attrs = _parse_attrs(tag)
        line = content[: m.start()].count("\n") + 1

        has_alt = "alt" in attrs
        alt_val = attrs.get("alt")

        aria_hidden = attrs.get("aria-hidden", "").lower() in ("true", "{true}")
        role = attrs.get("role")

        in_fig = _enclosed(content, m.start(), _FIGURE_OPEN_RE, _FIGURE_CLOSE_RE)
        figcap = None
        if in_fig:
            cap = _FIGCAPTION_RE.search(content, m.start())
            if cap:
                figcap = _TAG_STRIP_RE.sub("", cap.group(1)).strip() or None

        in_link = _enclosed(content, m.start(), _LINKBTN_OPEN_RE, _LINKBTN_CLOSE_RE)

        start = max(0, m.start() - _NEARBY_TEXT_CHARS)
        end = min(len(content), m.end() + _NEARBY_TEXT_CHARS)
        nearby = _TAG_STRIP_RE.sub(" ", content[start:end])
        nearby = re.sub(r"\s+", " ", nearby).strip()

        refs.append(ImageRef(
            src=attrs.get("src", ""),
            raw_tag=tag,
            file=filepath,
            line=line,
            has_alt_attr=has_alt,
            alt=alt_val,
            aria_hidden=aria_hidden,
            role=role,
            in_link_or_button=in_link,
            in_figure=in_fig,
            figcaption=figcap,
            nearby_text=nearby,
        ))
    return refs


# ── Role Classification ────────────────────────────────────────────────────────
#
# Conservative by design: an image is only described when we are confident it is
# NOT decorative. False "informative" wastes a vision call; false "decorative"
# would hide real content from screen-reader users — so when unsure we lean
# informative, but explicit decoration markers always win.

def classify_role(img: ImageRef) -> ImageRole:
    # Explicit decoration markers — authoritative, never described.
    if img.aria_hidden:
        return ImageRole.DECORATIVE
    if (img.role or "").lower() in ("presentation", "none"):
        return ImageRole.DECORATIVE
    # Explicit empty alt is the author declaring the image decorative (WCAG technique
    # H67). Respect it — re-describing would contradict an intentional decision.
    if img.has_alt_attr and img.alt == "":
        return ImageRole.DECORATIVE

    # Functional: the image IS the label of a link/button.
    if img.in_link_or_button:
        return ImageRole.FUNCTIONAL

    # Complex: charts/diagrams need a short alt + a long description.
    haystack = f"{img.src} {img.alt or ''} {img.figcaption or ''}".lower()
    if any(k in haystack for k in ("chart", "graph", "diagram", "plot", "infographic", "map")):
        return ImageRole.COMPLEX

    return ImageRole.INFORMATIVE


# ── Source scope check ─────────────────────────────────────────────────────────

def is_in_scope_src(src: str) -> bool:
    """MVP handles literal URL / local-path string srcs only."""
    if not src:
        return False
    if src.startswith("{"):            # JSX dynamic expression / bundler import
        return False
    if src.startswith("data:"):        # inline data URI — out of scope
        return False
    return True
