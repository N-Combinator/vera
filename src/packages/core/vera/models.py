"""
Vera — Shared Pydantic models for API, scanner, and fixer.
"""

from __future__ import annotations
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
import uuid


# ── Enums ─────────────────────────────────────────────────────────────────────

class Severity(str, Enum):
    CRITICAL = "critical"
    SERIOUS  = "serious"
    MODERATE = "moderate"
    MINOR    = "minor"


class RuleId(str, Enum):
    MISSING_ALT       = "missing-alt"
    MISSING_LABEL     = "missing-label"
    COLOR_CONTRAST    = "color-contrast"
    ARIA_HIDDEN_BODY  = "aria-hidden-body"
    DUPLICATE_ID      = "duplicate-id"
    EMPTY_HEADING     = "empty-heading"
    LABEL_ASSOCIATED  = "label-associated"
    MISSING_ROLE      = "missing-role"
    KEYBOARD_TRAP     = "keyboard-trap"
    FOCUSABLE_HIDDEN  = "focusable-hidden"


SEVERITY_MAP: Dict[RuleId, Severity] = {
    RuleId.MISSING_ALT:       Severity.SERIOUS,
    RuleId.MISSING_LABEL:     Severity.SERIOUS,
    RuleId.COLOR_CONTRAST:    Severity.SERIOUS,
    RuleId.ARIA_HIDDEN_BODY:  Severity.CRITICAL,
    RuleId.DUPLICATE_ID:      Severity.MODERATE,
    RuleId.EMPTY_HEADING:     Severity.MODERATE,
    RuleId.LABEL_ASSOCIATED:  Severity.SERIOUS,
    RuleId.MISSING_ROLE:      Severity.MODERATE,
    RuleId.KEYBOARD_TRAP:     Severity.CRITICAL,
    RuleId.FOCUSABLE_HIDDEN:  Severity.SERIOUS,
}


# ── Core Data Models ──────────────────────────────────────────────────────────

class CodeLocation(BaseModel):
    file: str
    line: int
    column: int
    end_line: Optional[int] = None
    end_column: Optional[int] = None


class Violation(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    rule: str
    severity: Severity
    element: str           # CSS selector or element path
    description: str
    suggestion: str        # Human-readable fix suggestion
    code_snippet: Optional[str] = None
    location: Optional[CodeLocation] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    fix_available: bool = True
    ai_generated: bool = False
    wcag_criterion: Optional[str] = None  # e.g. "1.1.1"


class Fix(BaseModel):
    violation_id: str
    file: str
    original_code: str
    fixed_code: str
    description: str
    applied: bool = False
    diff: Optional[str] = None


class ScanResult(BaseModel):
    scan_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    target: str
    framework: str = "auto"
    violations: List[Violation] = []
    total_files_scanned: int = 0
    scan_duration_ms: int = 0
    llm_provider: Optional[str] = None
    created_at: Optional[str] = None

    @property
    def violation_count(self) -> int:
        return len(self.violations)

    @property
    def critical_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == Severity.CRITICAL)


# ── Request / Response Models ──────────────────────────────────────────────────

class ScanRequest(BaseModel):
    path: str
    framework: str = "auto"
    rules: Optional[List[str]] = None   # None = all rules
    use_llm: bool = True
    llm_provider: Optional[str] = None  # override .verarc


class FixRequest(BaseModel):
    scan_id: Optional[str] = None
    violation_ids: Optional[List[str]] = None  # None = fix all
    path: str
    dry_run: bool = False


class FixResponse(BaseModel):
    fixes_applied: int
    fixes_skipped: int
    fixes: List[Fix]
    errors: List[str] = []


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"
    llm_available: bool = False
    llm_provider: Optional[str] = None


# ── Config ────────────────────────────────────────────────────────────────────

class LLMConfig(BaseModel):
    provider: str = "ollama"          # ollama | openai | anthropic | openrouter
    model: str = "llama3"
    endpoint: str = "http://localhost:11434"
    api_key: Optional[str] = None
    timeout: int = 60
    temperature: float = 0.1
    max_tokens: int = 2048


class VeraConfig(BaseModel):
    framework: str = "auto"           # auto | react | vue | html | jsx
    llm: LLMConfig = Field(default_factory=LLMConfig)
    rules: List[str] = []             # empty = all rules
    ignore_paths: List[str] = Field(
        default=["node_modules", ".git", "dist", "build", ".next", ".cache"]
    )
    output_format: str = "json"       # json | html | text
    max_files: int = 500
    confidence_threshold: float = 0.6
