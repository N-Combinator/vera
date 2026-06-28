"""Unit tests for the tree-based heuristic scanner (no network, no API key)."""

from vera.scanner import HeuristicScanner

scan = HeuristicScanner().scan


def _rules(content, fp="f.html"):
    return [v.rule for v in scan(content, fp)]


def _by_rule(content, rule, fp="f.html"):
    return [v for v in scan(content, fp) if v.rule == rule]


# ── missing-alt ───────────────────────────────────────────────────────────────

def test_missing_alt_flagged():
    assert "missing-alt" in _rules('<img src="a.png">')


def test_missing_alt_ok_with_alt():
    assert "missing-alt" not in _rules('<img src="a.png" alt="cat">')


def test_missing_alt_multiline_tag():
    # B1 regression: a tag spanning lines must still be detected.
    content = '<img\n  src="a.png"\n  width="120"\n>'
    v = _by_rule(content, "missing-alt")
    assert len(v) == 1
    assert v[0].location.line == 1  # reported at the tag's start line


# ── empty-heading ─────────────────────────────────────────────────────────────

def test_empty_heading_flagged():
    assert "empty-heading" in _rules("<h2></h2>")


def test_heading_with_nested_text_is_ok():
    # tree-aware: text inside a child element counts (regex missed this)
    assert "empty-heading" not in _rules("<h2><span>Title</span></h2>")


def test_heading_with_img_alt_is_ok():
    assert "empty-heading" not in _rules('<h1><img src="logo.png" alt="Acme"></h1>')


# ── aria-hidden body ──────────────────────────────────────────────────────────

def test_aria_hidden_body_flagged():
    assert "aria-hidden-body" in _rules('<body aria-hidden="true"><p>x</p></body>')


# ── duplicate-id ──────────────────────────────────────────────────────────────

def test_duplicate_id_flagged_once():
    content = '<div id="x"></div><div id="x"></div>'
    v = _by_rule(content, "duplicate-id")
    assert len(v) == 1


def test_unique_ids_ok():
    assert "duplicate-id" not in _rules('<div id="a"></div><div id="b"></div>')


# ── missing-label ─────────────────────────────────────────────────────────────

def test_missing_label_flagged():
    assert "missing-label" in _rules('<input type="text">')


def test_input_with_aria_label_ok():
    assert "missing-label" not in _rules('<input type="text" aria-label="Name">')


def test_hidden_input_not_flagged():
    assert "missing-label" not in _rules('<input type="hidden" name="csrf">')


def test_input_wrapped_by_label_with_text_ok():
    # nesting-aware improvement: implicit label association
    assert "missing-label" not in _rules("<label>Email <input type=\"email\"></label>")


# ── label-associated ──────────────────────────────────────────────────────────

def test_label_without_for_flagged():
    assert "label-associated" in _rules("<label>Name</label><input type='text'>")


def test_label_with_for_ok():
    assert "label-associated" not in _rules('<label for="n">Name</label>')


def test_label_wrapping_input_ok():
    assert "label-associated" not in _rules("<label>Name <input type='text'></label>")


# ── interactive div / missing-role (audit C1) ─────────────────────────────────

def test_interactive_div_without_role_flagged():
    assert "missing-role" in _rules("<div onClick={f}>Click</div>")


def test_interactive_div_with_role_after_onclick_is_ok():
    # C1 regression: role appearing AFTER the click handler must NOT be flagged.
    assert "missing-role" not in _rules('<div onClick={f} role="button" tabIndex={0}>Go</div>')


def test_interactive_div_with_role_before_onclick_is_ok():
    assert "missing-role" not in _rules('<div role="button" tabindex="0" onClick={f}>Go</div>')


def test_vue_click_handler_flagged():
    assert "missing-role" in _rules('<span @click="go">Go</span>')


# ── dedupe (audit C2) ─────────────────────────────────────────────────────────

def test_dedupe_keeps_distinct_lineless_violations():
    from vera.scanner import Scanner
    from vera.models import Violation, Severity
    vs = [
        Violation(rule="color-contrast", severity=Severity.SERIOUS, element="a",
                  description="one", suggestion="", location=None),
        Violation(rule="color-contrast", severity=Severity.SERIOUS, element="b",
                  description="two", suggestion="", location=None),
    ]
    out = Scanner._dedupe(vs)
    assert len(out) == 2  # distinct findings with no location must both survive


# ── honesty: heuristic pass must not claim LLM-only rules (D1/D2) ──────────────

from vera.scanner import LLM_ONLY_RULES


def test_heuristic_never_emits_llm_only_rules():
    samples = [
        '<img src="a.png">',
        '<div onclick="go()">x</div>',
        '<input type="text">',
        '<h1></h1>',
        '<button></button>',
        '<a href="#" style="color:#aaa;background:#bbb">low contrast text</a>',
    ]
    emitted = set()
    for s in samples:
        emitted |= set(_rules(s))
    # color-contrast / keyboard-trap / focusable-hidden have no static detector.
    assert not (emitted & LLM_ONLY_RULES)
