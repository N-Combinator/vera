# Vera — AI-Powered Accessibility Auto-Remediator

> Find accessibility issues in your code. Fix them automatically. Ship inclusive software.

---

## 🌐 What is Vera?

Vera (Verify & Access) is an open-source, AI-powered tool that automates accessibility remediation for web code. It scans React, Vue, HTML/JSX projects and **generates production-ready code fixes** for accessibility violations — no manual work required. Vera supports both local LLMs (privacy-first) and cloud APIs (speed/accuracy-first).

### 🌟 Key Features

- ✅ **Auto-fix generation**: Not just scanning — Vera writes the actual code patches
- ✅ **Dual-layer workflow**: CLI for developers + interactive dashboard for teams
- ✅ **CI/CD native**: Pre-commit hooks and GitHub Actions integration
- ✅ **WCAG 2.2 compliant**: 10 core rules (contrast, ARIA, keyboard traps)

### 🔍 Why Vera?

> *"We live in an era where accessibility will be mandated. Vera helps developers build inclusive apps at scale."*

**Empowers development teams to:**
- Fix accessibility issues *automatically* in codebases
- Maintain strict privacy with optional local LLMs
- Ship inclusive software faster through hybrid AI
- Integrate seamlessly into development workflows

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    vera CLI (Node.js)                            │
│                                                                  │
│  vera init  →  vera scan  →  vera fix  →  vera ui               │
│                     │             │                              │
│             HTTP Client    HTTP Client                           │
└──────────────────────┬────────────┬──────────────────────────────┘
                       │            │
                       ▼            ▼
┌──────────────────────────────────────────────────────────────────┐
│         Vera Backend (Python FastAPI + LLM Bridge)               │
│                                                                  │
│  POST /scan  ──► Scanner (Heuristics + LLM)                      │
│  POST /fix   ──► CodeFixer (AST patching + LLM)                  │
│  GET /health                                                     │
│                                                                  │
│  LLM Routing (configured in .verarc.json):                       │
│  • Ollama                 ← local, private                       │
│  • OpenAI                 ← cloud recommended                    │
│  • Anthropic              ← cloud fallback                       │
│  • OpenRouter             ← cloud aggregator                     │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│         React Dashboard UI (port 3000)                            │
│                                                                  │
│  • Visual issue cards   • Before/after diffs                    │
│  • One-click apply      • Scan history & export                 │
└──────────────────────────────────────────────────────────────────┘
```

### 📋 Rules (WCAG 2.2)

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

## 🔧 Installation & Usage Guide

### System Requirements

- Node.js 18+
- Docker Compose (optional for containerized backend)
- Python 3.12+ (if running backend locally)
- Ollama installation (for local LLM support) OR cloud API keys

### 1. Install the CLI

```bash
# Global install for command-line access
npm install -g @vera-dev/cli

# Or local project install
npm install --save-dev @vera-dev/cli
```

Verify installation:
```bash
vera --version
```

### 2. Initialize Vera in Your Project

```bash
# Navigate to your project directory
cd /path/to/your/project

# Run initialization
vera init
```

Interactive prompts:
```
? Do you want to use a local LLM? (Y/N): Y
? Which model? (llama3/mistral/neural-chat): llama3
? Use cloud API fallback? (Y/N): Y
? Which API provider? (openai/anthropic/openrouter): openai
? Enter your OpenAI API key: ••••••••••••••••••••••••••
? Target framework? (react/vue/vanilla): react
```

This creates:
- `.verarc.json` — Main configuration file
- `.vera/` — Setup and model directory
- `.env` — Local API keys (gitignored)

### 3. Run Your First Scan

```bash
# Scan source directory
vera scan ./src

# Output: JSON report with violations
# {
#   "violations": [
#     {
#       "id": 1,
#       "rule": "missing-alt",
#       "element": "img.logo",
#       "severity": "serious",
#       "description": "Image missing alt text"
#     }
#   ],
#   "summary": {
#     "total": 5,
#     "critical": 1,
#     "serious": 2,
#     "moderate": 2
#   }
# }
```

### 4. Preview and Apply Fixes

```bash
# Dry run: show proposed changes
vera fix ./src

# Shows colored diff output:
# ✓ [missing-alt] img.logo
#   + alt="Company Logo"
# 
# ✓ [color-contrast] button.primary
#   + color: #ffffff; (contrast ratio: 7.2:1)

# Apply fixes with confirmation
vera fix ./src --apply

# Auto-approve all fixes (skip prompt)
vera fix ./src --apply --yes

# Apply only specific violations
vera fix ./src --apply --violations abc123,def456
```

### 5. Launch the Interactive Dashboard

```bash
# Start dashboard at http://localhost:3000
vera ui

# Open on custom port
vera ui --port 4000

# Launch without opening browser
vera ui --no-open
```

Dashboard features:
- Visual issue cards with severity levels
- Before/after code comparison
- One-click apply fixes
- Export reports (JSON, HTML, CSV)
- Scan history and trending

### 6. Configuration (`.verarc.json`)

Full configuration reference:

```json
{
  "framework": "react",
  "llm": {
    "provider": "openai",
    "model": "gpt-4o-mini",
    "endpoint": "https://api.openai.com/v1",
    "temperature": 0.7,
    "maxTokens": 2000
  },
  "rules": [
    "missing-alt",
    "missing-label",
    "color-contrast",
    "aria-hidden-body",
    "duplicate-id",
    "empty-heading",
    "label-associated",
    "missing-role",
    "keyboard-trap",
    "focusable-hidden"
  ],
  "fixMode": "auto-apply",
  "confidenceThreshold": 0.75,
  "ignorePaths": [
    "node_modules",
    "dist",
    "build",
    ".next"
  ],
  "autoCommit": true,
  "deepScan": true,
  "maxFailures": 10
}
```

### 7. Environment Variables

```bash
# LLM Configuration
export VERA_LLM_PROVIDER=openai
export VERA_LLM_MODEL=gpt-4o-mini
export VERA_LLM_ENDPOINT=https://api.openai.com/v1
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...

# Backend Configuration
export VERA_BACKEND_URL=http://localhost:8000
export VERA_LOG_LEVEL=info

# CI/CD
export VERA_FAIL_ON_CRITICAL=true
```

### 8. CI/CD Integration

#### GitHub Actions Example

Create `.github/workflows/accessibility.yml`:

```yaml
name: Accessibility Check

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]

jobs:
  accessibility:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v3
        with:
          node-version: '18'
      
      - name: Install Vera CLI
        run: npm install -g @vera-dev/cli
      
      - name: Run accessibility scan
        run: vera scan ./src --output report.json
      
      - name: Fail on critical violations
        run: |
          CRITICAL=$(jq '[.violations[] | select(.severity=="critical")] | length' report.json)
          if [ "$CRITICAL" -gt 0 ]; then
            echo "❌ Critical accessibility issues found!"
            jq '.violations[] | select(.severity=="critical")' report.json
            exit 1
          fi
      
      - name: Upload report
        if: always()
        uses: actions/upload-artifact@v3
        with:
          name: accessibility-report
          path: report.json
```

#### Pre-Commit Hook

Add to `.husky/pre-commit`:

```bash
#!/bin/sh
. "$(dirname "$0")/_/husky.sh"

echo "🔍 Running accessibility check..."
if ! vera scan ./src --quiet --no-llm; then
  echo "❌ Accessibility issues found. Run 'vera fix ./src' to resolve."
  exit 1
fi
echo "✅ Accessibility check passed!"
```

Install Husky:
```bash
npx husky-init && npm install
npx husky add .husky/pre-commit 'vera scan ./src --quiet'
```

### 9. Docker Setup (Backend Only)

Run the backend in Docker:

```bash
# Start backend + dashboard
docker-compose up -d

# Check logs
docker-compose logs -f backend

# Stop services
docker-compose down
```

`docker-compose.yml`:
```yaml
version: '3.9'
services:
  backend:
    build: ./src/packages/core
    ports:
      - "8000:8000"
    environment:
      - VERA_LLM_PROVIDER=openai
      - OPENAI_API_KEY=${OPENAI_API_KEY}
    volumes:
      - ./src:/workspace
  
  dashboard:
    build: ./src/packages/dashboard
    ports:
      - "3000:3000"
    depends_on:
      - backend
```

### 10. Troubleshooting

| Issue | Solution |
|-------|----------|
| `vera: command not found` | Run `npm install -g @vera-dev/cli` or use `npx @vera-dev/cli` |
| `Error: LLM model not found` | Run `ollama run llama3` to download the model |
| `API key invalid` | Check `echo $OPENAI_API_KEY` or update `.verarc.json` |
| `Port 3000 already in use` | Run `vera ui --port 4000` or `lsof -i :3000` to find process |
| `Backend connection refused` | Ensure backend is running: `curl http://localhost:8000/health` |
| `No violations found` | Check that source directory contains `.jsx`, `.tsx`, or `.html` files |

### 11. Advanced Usage

```bash
# Generate HTML report
vera scan ./src --output report.html --format html

# Quiet mode (CI/CD)
vera scan ./src --quiet

# Verbose output with timing
vera scan ./src --verbose

# Dry run: test fixes without applying
vera fix ./src --dry-run

# Clean up local state
vera clean

# Check version
vera --version
```

---

## 📚 Project Structure

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
README.md
LICENSE
```

---

## 🤝 Contributing

We welcome contributions! Here's how:

1. Fork the repo
2. Create a branch (`git checkout -b feature/my-fix`)
3. Commit changes (`git commit -m 'Add feature'`)
4. Push (`git push origin feature/my-fix`)
5. Open a Pull Request

---

## 📄 License

MIT — see [LICENSE](LICENSE) for details.

---

## 💡 Final Tips

- Use `vera clean` to reset project configuration
- Back up `.verarc.json` when switching environments
- The dashboard's "Fix Preview" shows AI-generated code before applying
- Combine with Web Accessibility Inspector tools for best results
- Check out [WCAG 2.2 Guidelines](https://www.w3.org/WAI/WCAG22/quickref/) for standards reference

**Vera is live. Build inclusive apps at scale.** 🚀
