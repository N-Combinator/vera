"""Unit tests for Vera-Describe (no network, no API key)."""

import asyncio
from io import BytesIO

from PIL import Image

from vera.describe import (
    AltVerdict,
    ImageLoader,
    ImageRole,
    VisionEvaluator,
    classify_role,
    describe_content,
    extract_images,
    is_in_scope_src,
)


def _png_bytes(size=(8, 8), color=(255, 0, 0)):
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()

# ── Extraction ─────────────────────────────────────────────────────────────────

def test_extract_single_line_img():
    imgs = extract_images('<img src="a.png" alt="A cat">', "f.html")
    assert len(imgs) == 1
    assert imgs[0].src == "a.png"
    assert imgs[0].has_alt_attr is True
    assert imgs[0].alt == "A cat"


def test_extract_multiline_img_not_missed():
    # Regression for audit bug B1: multi-line tags must still be found.
    content = (
        "<img\n"
        '  src="logo.png"\n'
        "  width={120}\n"
        "/>"
    )
    imgs = extract_images(content, "App.jsx")
    assert len(imgs) == 1
    assert imgs[0].src == "logo.png"
    assert imgs[0].has_alt_attr is False
    assert imgs[0].line == 1


def test_missing_alt_vs_empty_alt_distinguished():
    no_alt = extract_images('<img src="a.png">')[0]
    empty = extract_images('<img src="b.png" alt="">')[0]
    assert no_alt.has_alt_attr is False and no_alt.alt is None
    assert empty.has_alt_attr is True and empty.alt == ""


def test_jsx_dynamic_alt_and_src_marked():
    img = extract_images("<img src={logo} alt={caption} />")[0]
    assert img.src.startswith("{")
    assert img.alt.startswith("{")


def test_figure_and_figcaption_captured():
    content = (
        "<figure>"
        '<img src="chart.png">'
        "<figcaption>Quarterly <b>revenue</b></figcaption>"
        "</figure>"
    )
    img = extract_images(content)[0]
    assert img.in_figure is True
    assert img.figcaption == "Quarterly revenue"


def test_img_inside_link_is_functional_context():
    img = extract_images('<a href="/home"><img src="home.png"></a>')[0]
    assert img.in_link_or_button is True


def test_img_outside_link_not_flagged():
    content = '<a href="/x">text</a><img src="a.png">'
    img = extract_images(content)[0]
    assert img.in_link_or_button is False


# ── Classification ─────────────────────────────────────────────────────────────

def test_aria_hidden_is_decorative():
    img = extract_images('<img src="a.png" aria-hidden="true">')[0]
    assert classify_role(img) == ImageRole.DECORATIVE


def test_role_presentation_is_decorative():
    img = extract_images('<img src="a.png" role="presentation">')[0]
    assert classify_role(img) == ImageRole.DECORATIVE


def test_explicit_empty_alt_is_decorative():
    img = extract_images('<img src="a.png" alt="">')[0]
    assert classify_role(img) == ImageRole.DECORATIVE


def test_link_img_is_functional():
    img = extract_images('<a href="/"><img src="home.png"></a>')[0]
    assert classify_role(img) == ImageRole.FUNCTIONAL


def test_chart_is_complex():
    img = extract_images('<img src="sales-chart.png">')[0]
    assert classify_role(img) == ImageRole.COMPLEX


def test_plain_img_is_informative():
    img = extract_images('<img src="photo.png">')[0]
    assert classify_role(img) == ImageRole.INFORMATIVE


# ── Scope ──────────────────────────────────────────────────────────────────────

def test_scope_rejects_data_and_dynamic():
    assert is_in_scope_src("https://x/a.png") is True
    assert is_in_scope_src("./a.png") is True
    assert is_in_scope_src("data:image/png;base64,xxxx") is False
    assert is_in_scope_src("{logo}") is False
    assert is_in_scope_src("") is False


# ── Image loader ───────────────────────────────────────────────────────────────

def test_loader_accepts_valid_png_via_injected_http():
    loader = ImageLoader(http_get=lambda url: _png_bytes())
    loaded = loader.load("https://x/a.png")
    assert loaded is not None
    assert loaded.media_type == "image/png"
    assert (loaded.width, loaded.height) == (8, 8)
    assert loaded.b64


def test_loader_rejects_non_image():
    loader = ImageLoader(http_get=lambda url: b"<html>not an image</html>")
    assert loader.load("https://x/a.png") is None


def test_loader_rejects_oversized():
    big = _png_bytes(size=(2, 2)) + b"\x00" * (6 * 1024 * 1024)
    loader = ImageLoader(http_get=lambda url: big)
    assert loader.load("https://x/a.png") is None


def test_loader_skips_out_of_scope_src():
    loader = ImageLoader(http_get=lambda url: _png_bytes())
    assert loader.load("data:image/png;base64,zzz") is None
    assert loader.load("{logo}") is None


def test_loader_reads_local_file(tmp_path):
    p = tmp_path / "pic.png"
    p.write_bytes(_png_bytes())
    loader = ImageLoader()
    loaded = loader.load("pic.png", base_dir=tmp_path)
    assert loaded is not None and loaded.media_type == "image/png"


# ── Vision evaluator (fake completer) ──────────────────────────────────────────

def _fake_vision(json_text):
    async def _c(prompt, image_b64, media_type):
        return json_text
    return _c


def test_vision_eval_parses_weak_verdict():
    ev = VisionEvaluator(_fake_vision(
        '{"verdict":"weak","score":0.3,"reasons":["filename used"],'
        '"suggested_alt":"Red square logo"}'
    ))
    img = extract_images('<img src="logo.png" alt="logo.png">')[0]
    loaded = ImageLoader(http_get=lambda u: _png_bytes()).load("https://x/logo.png")
    res = asyncio.run(ev.evaluate(img, loaded, ImageRole.INFORMATIVE))
    assert res.verdict == AltVerdict.WEAK
    assert res.suggested_alt == "Red square logo"
    assert res.reasons == ["filename used"]


def test_vision_eval_pass_drops_suggestion():
    ev = VisionEvaluator(_fake_vision(
        'Here you go:\n{"verdict":"pass","score":0.95,"suggested_alt":"x"}'
    ))
    img = extract_images('<img src="a.png" alt="A red square">')[0]
    loaded = ImageLoader(http_get=lambda u: _png_bytes()).load("https://x/a.png")
    res = asyncio.run(ev.evaluate(img, loaded, ImageRole.INFORMATIVE))
    assert res.verdict == AltVerdict.PASS
    assert res.suggested_alt is None      # nothing to suggest when it passes


def test_vision_eval_handles_bad_json_gracefully():
    ev = VisionEvaluator(_fake_vision("the model rambled, no json"))
    img = extract_images('<img src="a.png">')[0]
    loaded = ImageLoader(http_get=lambda u: _png_bytes()).load("https://x/a.png")
    res = asyncio.run(ev.evaluate(img, loaded, ImageRole.INFORMATIVE))
    # No usable alt + unparseable response → missing, not a crash.
    assert res.verdict == AltVerdict.MISSING


# ── Orchestrator ───────────────────────────────────────────────────────────────

def test_orchestrator_skips_decorative_without_loading():
    # If a decorative image were loaded/evaluated this fake would explode.
    def boom(url):
        raise AssertionError("decorative image must not be fetched")
    loader = ImageLoader(http_get=boom)
    ev = VisionEvaluator(_fake_vision('{"verdict":"pass"}'))
    content = '<img src="bg.png" aria-hidden="true">'
    res = asyncio.run(describe_content(content, "f.html", loader=loader, evaluator=ev))
    assert len(res) == 1
    assert res[0].verdict == AltVerdict.SKIPPED
    assert res[0].role == ImageRole.DECORATIVE


def test_orchestrator_evaluates_informative_image():
    loader = ImageLoader(http_get=lambda u: _png_bytes())
    ev = VisionEvaluator(_fake_vision('{"verdict":"missing","suggested_alt":"A red square"}'))
    content = '<img src="https://x/photo.png">'
    res = asyncio.run(describe_content(content, "f.html", loader=loader, evaluator=ev))
    assert res[0].verdict == AltVerdict.MISSING
    assert res[0].suggested_alt == "A red square"


def test_orchestrator_no_evaluator_marks_skipped():
    loader = ImageLoader(http_get=lambda u: _png_bytes())
    content = '<img src="https://x/photo.png">'
    res = asyncio.run(describe_content(content, "f.html", loader=loader, evaluator=None))
    assert res[0].verdict == AltVerdict.SKIPPED
    assert "evaluator unavailable" in (res[0].note or "")


# ── Integration over a realistic fixture ───────────────────────────────────────

import os
from vera.describe import ImageRole as _Role


def _load_fixture():
    here = os.path.dirname(__file__)
    with open(os.path.join(here, "fixtures", "describe_sample.html")) as f:
        return f.read()


def test_fixture_decoratives_skipped_and_never_fetched():
    fetched = []

    def track(url):
        fetched.append(url)
        return _png_bytes()

    loader = ImageLoader(http_get=track)
    ev = VisionEvaluator(_fake_vision('{"verdict":"weak","suggested_alt":"x"}'))
    res = asyncio.run(describe_content(_load_fixture(), "fix.html", loader=loader, evaluator=ev))

    # 3 decorative + 1 data-uri are skipped; none of those srcs were fetched.
    skipped = [e for e in res if e.verdict == AltVerdict.SKIPPED]
    assert len(skipped) >= 4
    assert not any("spacer" in u or "divider" in u or "bg-texture" in u for u in fetched)
    assert not any(u.startswith("data:") for u in fetched)


def test_fixture_roles_classified():
    loader = ImageLoader(http_get=lambda u: _png_bytes())
    ev = VisionEvaluator(_fake_vision('{"verdict":"weak","suggested_alt":"x"}'))
    res = asyncio.run(describe_content(_load_fixture(), "fix.html", loader=loader, evaluator=ev))
    roles = {e.src: e.role for e in res}
    assert roles["https://example.com/home-icon.png"] == _Role.FUNCTIONAL
    assert roles["https://example.com/sales-chart.png"] == _Role.COMPLEX
    assert roles["https://example.com/team-photo.jpg"] == _Role.INFORMATIVE


def test_fixture_multiline_banner_found():
    loader = ImageLoader(http_get=lambda u: _png_bytes())
    ev = VisionEvaluator(_fake_vision('{"verdict":"missing"}'))
    res = asyncio.run(describe_content(_load_fixture(), "fix.html", loader=loader, evaluator=ev))
    assert any("banner.png" in e.src for e in res)
