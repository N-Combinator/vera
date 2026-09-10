# Test Suite — Vera Accessibility Violations

This folder contains intentionally inaccessible pages for testing Vera's scanning and
auto-fix:

- `index.html` — a vanilla HTML page
- `App.jsx` — a React component with roughly the same issues

Each problem is marked with a `VIOLATION:` comment in the source. Not every planted issue
is detected by Vera today — the sections below list what is and isn't.

## What Vera detects

### Heuristics only (no LLM)

```bash
vera scan test/index.html --no-llm   # 8 violations
vera scan test/App.jsx --no-llm      # 8 violations
vera scan test/ --no-llm             # 16 violations in 2 files
```

Both files produce the same set:

| Rule | Per file |
|------|----------|
| `missing-alt` | 3 |
| `missing-label` | 3 |
| `missing-role` | 1 |
| `empty-heading` | 1 |

For a JSON report: `vera scan test/ --no-llm -f json -o report.json`.

### With an LLM enabled

`color-contrast`, `keyboard-trap`, and `focusable-hidden` are checked only in the LLM pass,
so `vera scan test/` without `--no-llm` can report more. The exact count depends on the
model, so there's no fixed expected number.

### Planted but not detected yet

These are in the test files on purpose, but no heuristic rule covers them:

- `aria-hidden="true"` on visible content (`aria-hidden-body` only checks `<body>`)
- skipped heading level (`<h1>` → `<h4>`)
- icon buttons without an accessible name
- `<div>`s used as navigation links or as a list
- foreign-language text without a `lang` attribute (`index.html`)
- low color contrast (LLM pass only, see above)

## Auto-fix

```bash
vera fix test/            # dry run: shows the patches, writes nothing
vera fix test/ --apply    # writes them (asks for confirmation; add --yes to skip)
```

With no LLM configured, `fix` makes 9 of the 16 changes and skips 7:

| Rule | What `fix` does |
|------|-----------------|
| `missing-label` | adds `aria-label` from the input's `placeholder`, `title`, or `name`; skips an input that has none of them |
| `missing-role` | adds `role="button"` and `tabindex="0"` (`tabIndex={0}` in JSX) |
| `empty-heading` | inserts a `TODO: Add heading text` comment — the heading still needs real text, so the next scan flags it again |
| `missing-alt` | skips: these product images are informative, and Vera never marks them decorative with `alt=""`. Use `vera describe` for alt-text suggestions |

After `--apply`, a second scan still reports **9 violations**. That's expected:

- 6 × `missing-alt` — informative images, left for `vera describe` or a human
- 2 × `empty-heading` — the inserted TODO comment (HTML or JSX) isn't heading text
- 1 × `missing-label` in `index.html` — the hidden input has no `placeholder`, `title`, or
  `name` to derive an honest label from

If an LLM is configured, `fix` also shows AI-suggested patches for what it skipped. They're
for review only and are never written to disk.

## Success criteria

With no LLM configured, Vera is working correctly if:

- `vera scan test/ --no-llm` reports 16 violations (8 per file)
- `vera fix test/` proposes 9 patches and skips 7
- the patched files are still valid HTML / JSX
- a rescan after `--apply` reports the 9 remaining violations listed above

If you change the rules or the test files, update these numbers.
