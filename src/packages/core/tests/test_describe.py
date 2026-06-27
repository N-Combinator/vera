"""Unit tests for Vera-Describe extraction + role classification (no network)."""

from vera.describe import (
    AltVerdict,
    ImageRole,
    classify_role,
    extract_images,
    is_in_scope_src,
)

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
