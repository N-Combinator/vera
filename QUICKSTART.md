# ⚡ Vera — Quickstart Guide

Get Vera running in under 5 minutes.

---

## Prerequisites

- Docker + Docker Compose
- Node.js 18+ (for CLI)
- Python 3.12+ (for running backend locally without Docker)
- Optional: Ollama (local LLM) — https://ollama.com

---

## Option A: Full Docker Setup (Recommended)

```bash
git clone https://github.com/cprite/daily-project-vera-2026-04-06.git
cd daily-project-vera-2026-04-06

# Start backend + dashboard
docker-compose up -d

# Verify
curl http://localhost:8000/health
# → {"status":"ok","version":"1.0.0","llm_available":false}

# Dashboard at:
open http://localhost:3000
```

---

## Option B: Local Development

### 1. Backend (Python)

```bash
cd src/packages/core

# Create venv
python3 -m venv .venv && source .venv/bin/activate

# Install deps
pip install -r requirements.txt

# Start server
uvicorn vera.api:app --reload --port 8000
# → INFO: Vera starting | LLM provider: ollama
```

### 2. Dashboard (React)

```bash
cd src/packages/dashboard
npm install
npm run dev
# → Dashboard at http://localhost:3000
```

### 3. CLI

```bash
cd src/packages/cli
npm install
npm run build

# Link globally
npm link

# Or use directly
node dist/bin/vera.js --help
```

---

## First Scan

```bash
# Scan any directory
vera scan ./src

# Output:
# ⚡ Vera — Scanning /path/to/src
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# 📄 src/components/Hero.jsx
#   [SERIOUS] missing-alt:45
#     Image element is missing an `alt` attribute (line 45)
#     💡 Add alt="descriptive text" or alt="" for decorative images
#     WCAG 1.1.1
#     🔧 Fix available
#
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📊 Summary: 3 violation(s) across 12 files
#    Scan ID: a1b2c3d4
#    Run 'vera fix ./src' to apply fixes.
```

---

## Apply Fixes

```bash
# Preview fixes (no files changed)
vera fix ./src

# Apply all fixes
vera fix ./src --apply

# Apply specific violations (use IDs from scan output)
vera fix ./src --apply --violations a1b2c3d4,e5f6g7h8

# Apply from a previous scan (faster)
vera fix ./src --apply --scan-id <scan_id>

# Skip confirmation prompt
vera fix ./src --apply --yes
```

---

## Enable AI Analysis

### Ollama (Local, Recommended)

```bash
# 1. Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# 2. Pull a model
ollama pull llama3
# or: ollama pull mistral

# 3. Configure Vera
cat > .verarc.json << 'EOF'
{
  "llm": {
    "provider": "ollama",
    "model": "llama3",
    "endpoint": "http://localhost:11434"
  }
}
EOF

# 4. Scan with AI
vera scan ./src
# → 🤖 AI: ollama (in summary)
```

### OpenAI

```bash
export OPENAI_API_KEY=sk-...

cat > .verarc.json << 'EOF'
{
  "llm": {
    "provider": "openai",
    "model": "gpt-4o-mini"
  }
}
EOF

vera scan ./src
```

### Anthropic

```bash
export VERA_API_KEY=sk-ant-...

cat > .verarc.json << 'EOF'
{
  "llm": {
    "provider": "anthropic",
    "model": "claude-3-haiku-20240307"
  }
}
EOF
```

---

## CI/CD Setup

### GitHub Actions

The repo includes a ready-to-use workflow at `.github/workflows/accessibility.yml`.

It:
- Starts the Vera backend
- Scans the repo with heuristic-only mode (no LLM for CI speed)
- Fails the build if critical violations are found
- Uploads a report artifact

### Pre-commit Hook (Husky)

```bash
# Install Husky
npm install -D husky
npx husky init

# The hook is already at .husky/pre-commit
# Just install Husky and it's active
```

---

## Dashboard

```bash
vera ui
# → 🌐 Dashboard running at http://localhost:3000
```

Features:
- 📊 **Scan tab** — enter path, toggle LLM, start scan
- 🔍 **Report tab** — view violations by severity/file, click for detail
- 🔧 **Fix preview** — before/after diff, one-click apply
- 📄 **Export** — JSON or HTML report download

---

## Configuration Reference

Create `.verarc.json` in your project root:

```json
{
  "framework": "react",
  "llm": {
    "provider": "ollama",
    "model": "llama3",
    "endpoint": "http://localhost:11434",
    "timeout": 60,
    "temperature": 0.1,
    "max_tokens": 2048
  },
  "rules": [],
  "ignore_paths": ["node_modules", ".git", "dist", "build"],
  "output_format": "json",
  "max_files": 500,
  "confidence_threshold": 0.6,
  "backend_url": "http://localhost:8000"
}
```

---

## Troubleshooting

**Backend won't start:**
```bash
cd src/packages/core
pip install -r requirements.txt
uvicorn vera.api:app --port 8000
```

**LLM not detected:**
```bash
curl http://localhost:11434/api/tags
# Should return list of models
ollama pull llama3
```

**CLI not found after build:**
```bash
cd src/packages/cli && npm run build
node dist/bin/vera.js --help
```

**Docker: backend can't reach Ollama:**
- Ollama must be running on the host
- `host.docker.internal` routes to your machine (auto-configured in docker-compose)
- Or set `VERA_LLM_ENDPOINT=http://host.docker.internal:11434`

**Port conflicts:**
```bash
# Change backend port
PORT=8001 uvicorn vera.api:app --port 8001

# Change dashboard port
vera ui --port 4000
```
