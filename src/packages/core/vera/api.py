"""
Vera — FastAPI backend server.
Endpoints: /scan, /fix, /health, /report/{scan_id}
"""

from __future__ import annotations
import logging
import os
from contextlib import asynccontextmanager
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .config_loader import load_config
from .llm_bridge import LLMBridge
from .models import (
    FixRequest,
    FixResponse,
    HealthResponse,
    ScanRequest,
    ScanResult,
)
from .scanner import Scanner
from .code_fixer import CodeFixer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("vera.api")

# ── In-memory scan cache (MVP — swap for SQLite/Redis in production) ──────────
_scan_cache: Dict[str, ScanResult] = {}

# ── App state ─────────────────────────────────────────────────────────────────
_llm: Optional[LLMBridge] = None
_config = None


def _cors_origins() -> List[str]:
    """Allowed CORS origins — the local dashboard/dev hosts. Vera is a local
    developer tool, so only loopback origins are permitted."""
    return [
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:8000", "http://127.0.0.1:8000",
    ]


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _llm, _config
    _config = load_config()
    _llm = LLMBridge(_config.llm)
    logger.info(f"[API] Vera starting | LLM provider: {_config.llm.provider} | model: {_config.llm.model}")
    available = await _llm.is_available()
    logger.info(f"[API] LLM available: {available}")
    yield
    if _llm:
        await _llm.close()
    logger.info("[API] Vera shutting down.")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Vera API",
    description="AI-powered accessibility auto-remediation engine",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
async def health():
    global _llm, _config
    available = False
    provider = None
    if _llm:
        available = await _llm.is_available()
        provider = _config.llm.provider if _config else None
    return HealthResponse(
        status="ok",
        version="1.0.0",
        llm_available=available,
        llm_provider=provider,
    )


@app.post("/scan", response_model=ScanResult)
async def scan(req: ScanRequest):
    global _llm, _config

    # Work on a per-request copy so a `rules` filter never leaks into the shared
    # global config used by later requests (C3).
    base_cfg = load_config() if _config is None else _config
    cfg = base_cfg.model_copy(deep=True)

    # Allow per-request LLM override. A bridge we create here owns its httpx
    # client and must be closed, or the connection pool leaks (C4).
    own_llm = False
    if req.llm_provider:
        from .models import LLMConfig
        custom_llm_cfg = LLMConfig(provider=req.llm_provider, model=cfg.llm.model)
        llm = LLMBridge(custom_llm_cfg) if req.use_llm else None
        own_llm = llm is not None
    else:
        llm = _llm if req.use_llm else None

    if req.rules:
        cfg.rules = req.rules

    scanner = Scanner(config=cfg, llm=llm)
    try:
        result = await scanner.scan(req.path)
    except Exception as e:
        logger.error(f"[API] Scan failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Scan failed: {str(e)}")
    finally:
        if own_llm and llm is not None:
            await llm.close()

    # Cache result
    _scan_cache[result.scan_id] = result
    logger.info(
        f"[API] Scan complete: {result.total_files_scanned} files, "
        f"{result.violation_count} violations in {result.scan_duration_ms}ms"
    )
    return result


@app.post("/fix", response_model=FixResponse)
async def fix(req: FixRequest):
    global _llm

    # Resolve scan result
    scan_result: Optional[ScanResult] = None
    if req.scan_id:
        scan_result = _scan_cache.get(req.scan_id)
        if not scan_result:
            raise HTTPException(status_code=404, detail=f"Scan ID not found: {req.scan_id}. Run /scan first.")
    else:
        # Re-scan the path to get current violations
        cfg = load_config() if _config is None else _config
        scanner = Scanner(config=cfg, llm=_llm)
        try:
            scan_result = await scanner.scan(req.path)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Re-scan failed: {str(e)}")

    fixer = CodeFixer(llm=_llm)
    try:
        response = await fixer.fix_scan(
            scan_result=scan_result,
            violation_ids=req.violation_ids,
            dry_run=req.dry_run,
            root=os.getenv("VERA_FIX_ROOT"),
        )
    except Exception as e:
        logger.error(f"[API] Fix failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Fix failed: {str(e)}")

    logger.info(
        f"[API] Fix complete: {response.fixes_applied} applied, "
        f"{response.fixes_skipped} skipped, dry_run={req.dry_run}"
    )
    return response


@app.get("/report/{scan_id}", response_model=ScanResult)
async def get_report(scan_id: str):
    result = _scan_cache.get(scan_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Scan not found: {scan_id}")
    return result


@app.get("/reports")
async def list_reports():
    """List all cached scan results (summary)."""
    return [
        {
            "scan_id": r.scan_id,
            "target": r.target,
            "violation_count": r.violation_count,
            "critical_count": r.critical_count,
            "created_at": r.created_at,
            "scan_duration_ms": r.scan_duration_ms,
        }
        for r in _scan_cache.values()
    ]


# ── Vera-Describe (opt-in alt-text quality module) ────────────────────────────

@app.post("/describe")
async def describe(req: dict):
    """Opt-in AI alt-text review (WCAG 1.1.1). Suggest-only; never writes files.

    Body: {"path": "<url|file|dir>", "api_key"?: "...", "model"?: "..."}.
    Off by default — the CLI only calls this under --describe/--check-alt.
    """
    from .describe import run_describe

    target = req.get("path")
    if not target:
        raise HTTPException(status_code=400, detail="`path` is required")

    api_key = req.get("api_key") or os.getenv("ANTHROPIC_API_KEY")
    try:
        report = await run_describe(target, api_key=api_key, model=req.get("model"))
    except Exception as e:
        logger.error(f"[API] Describe failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Describe failed: {str(e)}")

    logger.info(
        f"[API] Describe complete: {report.images_found} images | "
        f"pass={report.passed} weak={report.weak} missing={report.missing} "
        f"skipped={report.skipped}"
    )
    return {
        "target": report.target,
        "images_found": report.images_found,
        "summary": {
            "pass": report.passed, "weak": report.weak,
            "missing": report.missing, "skipped": report.skipped,
        },
        "evaluations": [e.model_dump() for e in report.evaluations],
        "human_summary": report.human_summary(),
    }


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    # Vera is a local developer tool — bind loopback by default.
    uvicorn.run(
        "vera.api:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        reload=os.getenv("VERA_DEV", "0") == "1",
        log_level="info",
    )
