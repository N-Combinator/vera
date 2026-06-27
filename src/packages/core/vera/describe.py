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


# ── Image loading ──────────────────────────────────────────────────────────────

class LoadedImage(BaseModel):
    b64: str
    media_type: str          # e.g. "image/png" — what the vision API expects
    width: int
    height: int


def _media_type_for(fmt: str) -> str:
    fmt = fmt.lower()
    return "image/jpeg" if fmt in ("jpg", "jpeg") else f"image/{fmt}"


class ImageLoader:
    """Resolve an <img src> to validated, base64-encoded bytes for the vision API.

    Returns None for anything out of scope or unfetchable — a single bad image
    must never crash the whole run.
    """

    def __init__(self, http_get=None, timeout: int = 15):
        # http_get(url) -> bytes ; injectable for tests / custom clients.
        self._http_get = http_get
        self._timeout = timeout

    def _fetch_bytes(self, src: str, base_dir: Optional[Path]) -> Optional[bytes]:
        parsed = urlparse(src)
        if parsed.scheme in ("http", "https"):
            try:
                if self._http_get is not None:
                    return self._http_get(src)
                import httpx
                resp = httpx.get(src, timeout=self._timeout, follow_redirects=True)
                resp.raise_for_status()
                return resp.content
            except Exception as e:
                logger.warning(f"[describe] fetch failed for {src}: {e}")
                return None
        # Local path (relative to the file that referenced it, else cwd).
        try:
            p = Path(src)
            if not p.is_absolute() and base_dir is not None:
                p = base_dir / src
            if not p.exists():
                logger.warning(f"[describe] local image not found: {p}")
                return None
            return p.read_bytes()
        except Exception as e:
            logger.warning(f"[describe] local read failed for {src}: {e}")
            return None

    def load(self, src: str, base_dir: Optional[Path] = None) -> Optional[LoadedImage]:
        if not is_in_scope_src(src):
            return None
        raw = self._fetch_bytes(src, base_dir)
        if not raw:
            return None
        if len(raw) > MAX_IMAGE_BYTES:
            logger.warning(f"[describe] image exceeds {MAX_IMAGE_BYTES} bytes: {src}")
            return None
        try:
            from io import BytesIO
            from PIL import Image
            im = Image.open(BytesIO(raw))
            im.verify()                      # integrity check
            fmt = (im.format or "").lower()
        except Exception as e:
            logger.warning(f"[describe] not a valid image {src}: {e}")
            return None
        if fmt not in SUPPORTED_FORMATS:
            logger.warning(f"[describe] unsupported format '{fmt}' for {src}")
            return None
        # Re-open for dimensions (verify() leaves the file unusable).
        try:
            from io import BytesIO
            from PIL import Image
            im2 = Image.open(BytesIO(raw))
            w, h = im2.size
        except Exception:
            w = h = 0
        return LoadedImage(
            b64=base64.b64encode(raw).decode("ascii"),
            media_type=_media_type_for(fmt),
            width=w,
            height=h,
        )


# ── Vision evaluation ──────────────────────────────────────────────────────────

VISION_RUBRIC_PROMPT = """\
You are a WCAG 2.2 accessibility expert reviewing alt text against the REAL image.

Context for this <img>:
- role: {role}
- existing alt: {existing_alt}
- nearby text: {nearby_text}
- figure caption: {figcaption}

Evaluate the EXISTING alt against the image by this rubric:
1. accuracy — does it match what the image actually shows?
2. brevity — concise (no "image of"/"picture of" padding)?
3. no-filename — not a filename, "image", or generic placeholder?
4. context-match — appropriate for a {role} image; not duplicating nearby text/caption?

Return ONLY JSON:
{{
  "verdict": "pass" | "weak" | "missing",
  "score": <0.0-1.0>,
  "reasons": ["<short reason>", ...],
  "suggested_alt": "<improved alt, or empty string if existing alt already passes>"
}}
Rules: "missing" if there is no usable alt. "weak" if present but fails the rubric.
For functional images describe the ACTION; for complex images give a short alt and
note that a long description is needed. Never invent details not visible.
"""


def _verdict_from(raw: dict, has_alt: bool) -> AltVerdict:
    v = str(raw.get("verdict", "")).lower()
    if v in ("pass", "weak", "missing"):
        return AltVerdict(v)
    return AltVerdict.MISSING if not has_alt else AltVerdict.WEAK


class VisionEvaluator:
    """Evaluate one image's alt text via a vision-capable LLM.

    `vision_complete(prompt, image_b64, media_type) -> str` is injected so the
    evaluator is fully unit-testable without a live API or key.
    """

    def __init__(self, vision_complete):
        self._complete = vision_complete

    async def evaluate(self, img: ImageRef, loaded: LoadedImage, role: ImageRole) -> AltEvaluation:
        prompt = VISION_RUBRIC_PROMPT.format(
            role=role.value,
            existing_alt=(img.alt if img.has_alt_attr else "<none>"),
            nearby_text=img.nearby_text[:400] or "<none>",
            figcaption=img.figcaption or "<none>",
        )
        import json as _json
        try:
            raw_text = await self._complete(prompt, loaded.b64, loaded.media_type)
            data = _extract_json_obj(raw_text)
        except Exception as e:
            logger.warning(f"[describe] vision eval failed for {img.src}: {e}")
            return AltEvaluation(
                src=img.src, file=img.file, line=img.line, role=role,
                verdict=AltVerdict.SKIPPED, existing_alt=img.alt,
                note=f"vision call failed: {e}",
            )
        verdict = _verdict_from(data, img.has_alt_attr and bool(img.alt))
        suggested = (data.get("suggested_alt") or "").strip() or None
        if verdict == AltVerdict.PASS:
            suggested = None
        return AltEvaluation(
            src=img.src, file=img.file, line=img.line, role=role,
            verdict=verdict,
            score=float(data.get("score", 0.0) or 0.0),
            reasons=[str(r) for r in (data.get("reasons") or [])][:5],
            existing_alt=img.alt,
            suggested_alt=suggested,
        )


def _extract_json_obj(raw: str) -> dict:
    import json as _json
    raw = (raw or "").strip()
    try:
        d = _json.loads(raw)
        if isinstance(d, dict):
            return d
    except Exception:
        pass
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end > start:
        try:
            d = _json.loads(raw[start:end + 1])
            if isinstance(d, dict):
                return d
        except Exception:
            pass
    return {}


# ── Orchestrator ───────────────────────────────────────────────────────────────

async def describe_content(
    content: str,
    filepath: str,
    *,
    loader: ImageLoader,
    evaluator: Optional[VisionEvaluator],
    base_dir: Optional[Path] = None,
) -> List[AltEvaluation]:
    """Evaluate every <img> in one piece of content. Pure orchestration —
    extraction → classify → (skip decorative/out-of-scope) → load → vision."""
    out: List[AltEvaluation] = []
    for img in extract_images(content, filepath):
        role = classify_role(img)

        if role == ImageRole.DECORATIVE:
            out.append(AltEvaluation(
                src=img.src, file=img.file, line=img.line, role=role,
                verdict=AltVerdict.SKIPPED, existing_alt=img.alt,
                note="decorative — intentionally not described",
            ))
            continue

        if not is_in_scope_src(img.src):
            out.append(AltEvaluation(
                src=img.src, file=img.file, line=img.line, role=role,
                verdict=AltVerdict.SKIPPED, existing_alt=img.alt,
                note="src out of MVP scope (dynamic/data-uri/empty)",
            ))
            continue

        loaded = loader.load(img.src, base_dir)
        if loaded is None:
            # Could not fetch the pixels. We still know whether alt is absent.
            verdict = AltVerdict.MISSING if not (img.has_alt_attr and img.alt) else AltVerdict.SKIPPED
            out.append(AltEvaluation(
                src=img.src, file=img.file, line=img.line, role=role,
                verdict=verdict, existing_alt=img.alt,
                note="image could not be loaded; verdict from alt presence only",
            ))
            continue

        if evaluator is None:
            out.append(AltEvaluation(
                src=img.src, file=img.file, line=img.line, role=role,
                verdict=AltVerdict.SKIPPED, existing_alt=img.alt,
                note="vision evaluator unavailable (no API key)",
            ))
            continue

        out.append(await evaluator.evaluate(img, loaded, role))
    return out


# ── Top-level entry point ──────────────────────────────────────────────────────

_DESCRIBE_EXTENSIONS = {".html", ".htm", ".jsx", ".tsx", ".vue"}


def _build_default_evaluator(api_key: Optional[str], model: Optional[str]):
    """Wire a real Claude-Vision evaluator, or None when no key is available
    (the run still reports structure/decoration; it just can't grade pixels)."""
    if not api_key:
        return None
    from .llm_bridge import LLMBridge
    from .models import LLMConfig

    bridge = LLMBridge(LLMConfig(provider="anthropic", api_key=api_key,
                                 model=model or "claude-sonnet-4-6"))

    async def vision_complete(prompt: str, image_b64: str, media_type: str) -> str:
        return await bridge.vision_complete(prompt, image_b64, media_type, model=model)

    return VisionEvaluator(vision_complete)


async def run_describe(
    target: str,
    *,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    loader: Optional[ImageLoader] = None,
    evaluator: Optional[VisionEvaluator] = "default",
) -> DescribeReport:
    """Run Vera-Describe over a URL, a single HTML/JSX file, or a directory.

    SUGGEST-ONLY: produces a report; never writes to disk or alters source.
    """
    loader = loader or ImageLoader()
    if evaluator == "default":
        evaluator = _build_default_evaluator(api_key, model)

    report = DescribeReport(target=target)

    # 1) Remote page.
    if target.startswith("http://") or target.startswith("https://"):
        try:
            import httpx
            resp = httpx.get(target, timeout=20, follow_redirects=True)
            resp.raise_for_status()
            content = resp.text
        except Exception as e:
            logger.error(f"[describe] could not fetch page {target}: {e}")
            return report
        evals = await describe_content(content, target, loader=loader,
                                       evaluator=evaluator, base_dir=None)
        report.evaluations.extend(evals)
        report.images_found = len(extract_images(content, target))
        return report

    # 2) Local file or directory.
    path = Path(target)
    files: List[Path] = []
    if path.is_file():
        files = [path]
    elif path.is_dir():
        files = [p for p in path.rglob("*")
                 if p.is_file() and p.suffix.lower() in _DESCRIBE_EXTENSIONS]
    else:
        logger.error(f"[describe] target not found: {target}")
        return report

    for f in files:
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
        except OSError as e:
            logger.warning(f"[describe] cannot read {f}: {e}")
            continue
        report.images_found += len(extract_images(content, str(f)))
        evals = await describe_content(content, str(f), loader=loader,
                                       evaluator=evaluator, base_dir=f.parent)
        report.evaluations.extend(evals)

    return report

