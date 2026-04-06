# ⚡ Vera — AI-Powered Accessibility Auto-Remediator

> Find accessibility issues in your code. Fix them automatically. Ship inclusive software.

Vera (Verify and Access) scans React, Vue, HTML, and JSX codebases for WCAG 2.2 violations and **generates production-ready code fixes** using a local or cloud LLM. All data stays on your machine.

---

## Why Vera?

- **Auto-fixes, not just reports** — Vera writes the corrected code for you
- **Local-first AI** — Uses Ollama (Llama 3, Mistral) so nothing leaves your machine
- **CI/CD native** — GitHub Actions integration, pre-commit hooks
- **Zero setup friction** — `vera scan ./src` just works

---

## Install

```bash
# Install CLI globally
npm install -g @vera-dev/cli

# Initialize (one-time setup)
vera init

# Start backend
docker-compose up -d
```

---

## Usage

```bash
# Scan a directory
vera scan ./src

# Scan and save JSON report
vera scan ./src --output report.json --format json

# Generate HTML report
vera scan ./src --output report.html --format html

# Preview fixes (dry run)
vera fix ./src

# Apply fixes to disk
vera fix ./src --apply

# Apply specific violations only
vera fix ./src --apply --violations abc123,def456

# Launch dashboard UI
vera ui

# Open on custom port
vera ui --port 4000
```

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   vera CLI (Node.js)                │
│                                                     │
│  vera init  →  vera scan  →  vera fix  →  vera ui  │
│                     │              │                 │
│              HTTP Client     HTTP Client             │
└──────────────────────┬──────────────┬───────────────┘
                       │              │
                       ▼              ▼
┌─────────────────────────────────────────────────────┐
│             Vera Backend (Python FastAPI)            │
│                                                     │
│  POST /scan ──► Scanner ──► Heuristics + LLM        │
│  POST /fix  ──► CodeFixer ──► AST/regex patches     │
│  GET  /health                                       │
│                                                     │
│  ┌─────────────────┐   ┌──────────────────────┐    │
│  │  LLM Bridge     │   │  Code Fixer          │    │
│  │  - Ollama       │   │  - Rule-based fixes  │    │
│  │  - OpenAI       │   │  - LLM fallback      │    │
│  │  - Anthropic    │   │  - Diff generation   │    │
│  │  - OpenRouter   │   └──────────────────────┘    │
│  └─────────────────┘                               │
└──────────────────────┬──────────────────────────────┘
                       │ (optional)
                       ▼
┌─────────────────────────────────────────────────────┐
│              LLM (Local or Cloud)                   │
│                                                     │
│  Ollama (Llama 3)          ← default, private       │
│  OpenAI (GPT-4o-mini)      ← cloud fallback         │
│  Anthropic (Claude Haiku)  ← cloud fallback         │
│  OpenRouter                ← aggregator             │
└─────────────────────────────────────────────────────┘
         ▲
         │ vera ui (port 3000)
┌────────────────────┐
│  React Dashboard   │
│  - Issue cards     │
│  - Fix preview     │
│  - One-click apply │
│  - Report export   │
└────────────────────┘
```

---

## Rules (WCAG 2.2)

| Rule ID | Description | WCAG | Severity |
|---------|-------------|------|----------|
| `missing-alt` | `<img>` missing alt text | 1.1.1 | Serious |
| `missing-label` | Input without label/aria-label | 1.3.1 | Serious |
| `color-contrast` | Text contrast < 4.5:1 | 1.4.3 | Serious |
| `aria-hidden-body` | `body` with `aria-hidden=true` | 4.1.2 | Critical |
| `duplicate-id` | Duplicate `id` attributes | 4.1.1 | Moderate |
| `empty-heading` | `<h1>-<h6>` with no content | 2.4.6 | Moderate |
| `label-associated` | Label not linked to input | 1.3.1 | Serious |
| `missing-role` | Interactive div/span without role | 4.1.2 | Moderate |
| `keyboard-trap` | Focus cannot leave component | 2.1.2 | Critical |
| `focusable-hidden` | Focusable element hidden from AT | 4.1.2 | Serious |

---

## CI/CD Integration

### GitHub Actions

```yaml
- name: Vera Accessibility Scan
  run: vera scan ./src --output report.json --quiet
- name: Fail on critical violations
  run: |
    CRITICAL=$(jq '[.violations[] | select(.severity=="critical")] | length' report.json)
    if [ "$CRITICAL" -gt 0 ]; then exit 1; fi
```

See [`.github/workflows/accessibility.yml`](.github/workflows/accessibility.yml) for the full workflow.

### Pre-commit Hook

Add to `.husky/pre-commit`:
```bash
vera scan ./src --quiet --no-llm || exit 1
```

---

## Configuration (`.verarc.json`)

```json
{
  "framework": "react",
  "llm": {
    "provider": "ollama",
    "model": "llama3",
    "endpoint": "http://localhost:11434"
  },
  "rules": ["missing-alt", "missing-label"],
  "ignore_paths": ["node_modules", "dist"],
  "confidence_threshold": 0.7
}
```

### Environment Variables

| Variable | Description |
|---|---|
| `VERA_LLM_PROVIDER` | `ollama` \| `openai` \| `anthropic` \| `openrouter` |
| `VERA_LLM_MODEL` | Model name (e.g. `llama3`, `gpt-4o-mini`) |
| `VERA_LLM_ENDPOINT` | LLM API endpoint (default: Ollama local) |
| `VERA_API_KEY` | API key for cloud providers |
| `OPENAI_API_KEY` | OpenAI API key (alias) |
| `VERA_BACKEND_URL` | Backend URL for CLI (default: `http://localhost:8000`) |

---

## Project Structure

```
/src/packages
  /cli          # Node.js CLI (@vera-dev/cli)
  /core         # Python FastAPI backend
    /vera
      api.py          ← FastAPI server
      scanner.py      ← File scanner (heuristic + LLM)
      llm_bridge.py   ← LLM routing + prompting
      code_fixer.py   ← Deterministic + LLM-powered fixes
      models.py       ← Pydantic data models
      config_loader.py ← .verarc.json loader
  /dashboard    # React 18 + Redux + Tailwind UI
.github/workflows/accessibility.yml
docker-compose.yml
.verarc.example
```

---

## License

MIT — see [LICENSE](LICENSE)
