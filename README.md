# Vera — AI-Powered Accessibility Auto-Remediator

Vera scans web code (HTML, JSX/TSX, Vue) for WCAG 2.2 accessibility issues and helps you
fix them — deterministic code patches, AI alt-text review via Claude Vision, and inline
review comments in your pull requests.

---

## Features

- **Scan** — fast heuristic checks for missing alt text, unlabeled inputs, duplicate IDs,
  empty headings, interactive elements without roles, and more.
- **Fix** — safe, opt-in code patches. Dry-run by default; only writes with `--apply`. A
  fixer that can't produce a correct change skips it rather than guessing.
- **Describe** — Claude Vision grades each image's alt text against the actual pixels and
  suggests a real description (suggest-only, never writes).
- **PR comments** — a GitHub Action posts findings as inline review comments on the diff.
- **Local or cloud LLM** — Ollama (private) or OpenAI / Anthropic / OpenRouter.
- **Dashboard** — optional web UI for browsing issues and before/after diffs.

---

## Install

Requires **Node.js 18+** and **Python 3.12+** (Docker optional).

```bash
# 1. Build the CLI
cd src/packages/cli
npm install && npm run build

# 2. Start the backend (pick one)
docker-compose up -d                                   # from repo root, or:
cd ../core && pip install -r requirements.txt \
  && uvicorn vera.api:app --port 8000                  # manual
```

Then call the CLI via the compiled binary (alias it for convenience):

```bash
alias vera='node /abs/path/to/src/packages/cli/dist/bin/vera.js'
vera --version
```

---

## Configure

Two ways to set up your LLM provider — pick whichever you prefer, both work:

**Option 1 — interactive wizard:**

```bash
vera init   # asks for provider, model, etc. → saves .verarc.json
```

**Option 2 — manual:**

```bash
cp .env.example .env   # then open .env and uncomment your provider
```

> Cloud API keys always live in an env var (e.g. in `.env`) — for safety Vera never
> writes keys to `.verarc.json`. Local Ollama needs no key.

---

## Usage

```bash
vera init                      # create .verarc.json config
vera scan ./src                # report violations (add --no-llm for heuristics only)
vera scan ./src -f json -o report.json

vera fix ./src                 # preview fixes (dry run — writes nothing)
vera fix ./src --apply         # apply fixes to disk
vera fix ./src --apply --yes   # skip the confirmation prompt

vera describe ./page.html      # AI alt-text review (needs ANTHROPIC_API_KEY)
vera ui                        # launch the dashboard at :3000
```

**`fix` is safe by design:** it's a dry run unless you pass `--apply`, and it only makes
changes it can make *correctly* — e.g. it derives an input's label from its `placeholder`
rather than inventing a generic one, and never marks an informative image decorative.

### CI / pull requests

A ready-made workflow lives at `.github/workflows/accessibility.yml`. It scans changed
files and posts inline comments on the PR:

```yaml
- env:
    GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
    VERA_FAIL_ON_CRITICAL: "true"   # fail the check on critical issues
  run: python -m vera.pr_report
```

---

## Rules (WCAG 2.2)

Detected by fast heuristics (no LLM needed):

| Rule | WCAG | Severity |
|------|------|----------|
| `missing-alt` — `<img>` without alt | 1.1.1 | Serious |
| `missing-label` — input without an accessible name | 1.3.1 | Serious |
| `label-associated` — label not linked to a control | 1.3.1 | Serious |
| `aria-hidden-body` — `aria-hidden` on `<body>` | 4.1.2 | Critical |
| `duplicate-id` — repeated `id` attribute | 4.1.1 | Moderate |
| `empty-heading` — `<h1>`–`<h6>` with no text | 2.4.6 | Moderate |
| `missing-role` — interactive `div`/`span` without a role | 4.1.2 | Moderate |

Additionally `color-contrast`, `keyboard-trap`, and `focusable-hidden` are detected only
when an LLM pass is enabled (no standalone heuristic yet).

---

## Safe by default

Vera is a local developer tool, and two guards keep it from doing anything surprising
on your machine:

- **Writes stay in the project.** `/fix` only writes inside the scanned directory; set
  `VERA_FIX_ROOT` to pin the allowed root explicitly. It can't overwrite files elsewhere.
  (`VERA_FIX_ROOT` is an env var, set like the others — e.g. `export VERA_FIX_ROOT=./src`.)
- **No internal network fetches.** When `describe` resolves image URLs, it refuses
  addresses that point at private, loopback, link-local, or cloud-metadata IPs — so a
  crafted page can't make Vera reach internal endpoints.

---

## Architecture

```
vera CLI (Node/TS)  ──HTTP──►  FastAPI backend (Python)  ──►  LLM bridge
  scan / fix / describe          /scan  /fix  /describe        Ollama · OpenAI
  init / ui                                                    Anthropic · OpenRouter
                                       │
                                       └──►  React dashboard (:3000)
```

- **CLI** (`src/packages/cli`) — command surface, talks to the backend over HTTP.
- **Core** (`src/packages/core/vera`) — scanner, code fixer, describe (Vision), PR
  reporter, LLM bridge, FastAPI app.
- **Dashboard** (`src/packages/dashboard`) — optional React UI.

---

## License

MIT — see [LICENSE](LICENSE).
