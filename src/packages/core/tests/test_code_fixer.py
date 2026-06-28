"""Unit tests for the deterministic code fixer (no network, no API key).

Covers the fix-quality rebuild: correct label derivation, decorative-only alt,
real id resolution for label association, and multi-line tag safety (B1).
"""

from vera.code_fixer import RuleFixer, _find_tag, _line_start_offset
from vera.models import CodeLocation, RuleId, Severity, Violation


def _violation(rule, line, element="", description="", file="f.html"):
    return Violation(
        rule=rule,
        severity=Severity.SERIOUS,
        element=element,
        description=description or rule,
        suggestion="fix it",
        location=CodeLocation(file=file, line=line, column=0),
    )


fixer = RuleFixer()


# ── tag-region helpers (B1 multi-line) ────────────────────────────────────────

def test_find_tag_multiline():
    content = '<img\n  src="a.png"\n  width="120"\n>'
    span = _find_tag(content, 0, ["img"])
    assert span is not None
    s, e = span
    assert content[s:e].startswith("<img")
    assert content[s:e].endswith(">")
    assert "width" in content[s:e]  # spans all three lines


def test_find_tag_ignores_gt_inside_attr():
    content = '<input value="a > b">'
    span = _find_tag(content, 0, ["input"])
    assert span is not None
    assert content[span[0]:span[1]] == content  # whole tag, not cut at the inner >


def test_line_start_offset():
    content = "line1\nline2\nline3"
    assert content[_line_start_offset(content, 2):].startswith("line2")


# ── missing-label: derive real label, never generic "Field" ───────────────────

def test_missing_label_uses_placeholder():
    content = '<input type="text" name="search" placeholder="Search the catalog">'
    out = fixer.fix(_violation(RuleId.MISSING_LABEL, 1), content)
    assert out is not None
    assert 'aria-label="Search the catalog"' in out
    assert "Field" not in out


def test_missing_label_falls_back_to_name_humanized():
    content = '<input type="email" name="user_email">'
    out = fixer.fix(_violation(RuleId.MISSING_LABEL, 1), content)
    assert out is not None
    assert 'aria-label="User email"' in out


def test_missing_label_skips_when_no_source():
    # no placeholder/title/name → don't invent a generic label, defer instead
    content = '<input type="text">'
    out = fixer.fix(_violation(RuleId.MISSING_LABEL, 1), content)
    assert out is None


def test_missing_label_skips_when_already_labelled():
    content = '<input type="text" name="q" aria-label="Query">'
    assert fixer.fix(_violation(RuleId.MISSING_LABEL, 1), content) is None


def test_missing_label_escapes_quotes():
    content = '<input name="x" placeholder=\'say "hi"\'>'
    out = fixer.fix(_violation(RuleId.MISSING_LABEL, 1), content)
    assert out is not None
    assert "&quot;" in out


# ── missing-alt: decorative only, never hide informative content ──────────────

def test_missing_alt_tracking_pixel_gets_empty_alt():
    content = '<img height="1" width="1" src="https://www.facebook.com/tr?id=1&noscript=1">'
    out = fixer.fix(_violation(RuleId.MISSING_ALT, 1), content)
    assert out is not None
    assert 'alt=""' in out


def test_missing_alt_role_presentation_gets_empty_alt():
    content = '<img src="divider.png" role="presentation">'
    out = fixer.fix(_violation(RuleId.MISSING_ALT, 1), content)
    assert out is not None
    assert 'alt=""' in out


def test_missing_alt_informative_is_deferred_not_hidden():
    # an informative content image must NOT be silently marked decorative
    content = '<img src="https://site.com/promo/summer-set.png" style="width:500px">'
    out = fixer.fix(_violation(RuleId.MISSING_ALT, 1), content)
    assert out is None


def test_missing_alt_skips_when_alt_present():
    content = '<img src="a.png" alt="cat">'
    assert fixer.fix(_violation(RuleId.MISSING_ALT, 1), content) is None


# ── label-association: resolve a REAL id, no dangling for ──────────────────────

def test_label_association_reuses_existing_input_id():
    content = '<label>Email</label>\n<input id="email-field" type="email">'
    out = fixer.fix(_violation(RuleId.LABEL_ASSOCIATED, 1), content)
    assert out is not None
    assert 'for="email-field"' in out
    # did not invent a new id
    assert out.count('id="email-field"') == 1


def test_label_association_injects_shared_id():
    content = '<label>Phone</label>\n<input type="tel" name="phone">'
    out = fixer.fix(_violation(RuleId.LABEL_ASSOCIATED, 1), content)
    assert out is not None
    # the for target and the injected input id must match
    import re
    m = re.search(r'for="(input-[0-9a-f]+)"', out)
    assert m, out
    shared = m.group(1)
    assert f'id="{shared}"' in out


def test_label_association_skips_when_no_control():
    content = '<label>Orphan label</label>\n<p>no input here</p>'
    assert fixer.fix(_violation(RuleId.LABEL_ASSOCIATED, 1), content) is None


def test_label_association_skips_when_for_present():
    content = '<label for="x">Email</label>\n<input id="x">'
    assert fixer.fix(_violation(RuleId.LABEL_ASSOCIATED, 1), content) is None


# ── missing-role / empty-heading: framework-correct output (B2) ───────────────

def test_missing_role_html_uses_lowercase_tabindex():
    content = '<div class="btn">Click</div>'
    out = fixer.fix(_violation(RuleId.MISSING_ROLE, 1, file="page.html"), content)
    assert out is not None
    assert 'tabindex="0"' in out
    assert 'role="button"' in out


def test_missing_role_jsx_uses_camelcase_tabindex():
    content = '<div className="btn">Click</div>'
    out = fixer.fix(_violation(RuleId.MISSING_ROLE, 1, file="Button.jsx"), content)
    assert out is not None
    assert "tabIndex={0}" in out


def test_empty_heading_jsx_uses_jsx_comment():
    content = "<h2></h2>"
    out = fixer.fix(_violation(RuleId.EMPTY_HEADING, 1, file="Page.tsx"), content)
    assert out is not None
    assert "{/*" in out and "<!--" not in out


def test_empty_heading_html_uses_html_comment():
    content = "<h2></h2>"
    out = fixer.fix(_violation(RuleId.EMPTY_HEADING, 1, file="page.html"), content)
    assert out is not None
    assert "<!--" in out


# ── multi-line regression: a fix must apply on a tag spanning lines (B1) ───────

def test_missing_label_multiline_tag():
    content = '<input\n  type="text"\n  placeholder="Multi line"\n>'
    out = fixer.fix(_violation(RuleId.MISSING_LABEL, 1), content)
    assert out is not None
    assert 'aria-label="Multi line"' in out
