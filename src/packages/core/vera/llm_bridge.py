"""
Vera — LLM Bridge: routes requests to local (Ollama) or cloud LLMs.
Supports: Ollama, OpenAI, Anthropic, OpenRouter.
"""

from __future__ import annotations
import json
import logging
from typing import Any, Dict, List, Optional
import httpx
from .models import LLMConfig, Violation, Severity, RuleId, SEVERITY_MAP

logger = logging.getLogger("vera.llm")

# ── Prompt Templates ──────────────────────────────────────────────────────────

DETECT_PROMPT = """\
You are a WCAG 2.2 accessibility expert. Analyze the following code snippet for accessibility violations.

Focus on:
- Missing or empty alt text on images
- Form inputs without associated labels or aria-label
- Poor color contrast (if inline styles present)
- Semantic HTML issues (interactive divs, spans used as buttons)
- Missing ARIA roles where needed
- Empty headings
- Duplicate IDs
- aria-hidden on focusable elements

Return a JSON array (only JSON, no explanation) of violations:
[
  {{
    "rule": "<rule-id>",
    "element": "<css-selector or xpath>",
    "description": "<human-readable issue>",
    "suggestion": "<code fix suggestion>",
    "confidence": <0.0-1.0>,
    "wcag_criterion": "<criterion e.g. 1.1.1>"
  }}
]

If no violations found, return: []

Rule IDs: missing-alt, missing-label, color-contrast, aria-hidden-body,
duplicate-id, empty-heading, label-associated, missing-role, keyboard-trap, focusable-hidden

Code snippet (file: {filename}):
```
{snippet}
```
"""

FIX_PROMPT = """\
You are a WCAG 2.2 accessibility expert and senior developer.

Violation: {description}
Rule: {rule}
Element: {element}
Suggestion: {suggestion}

Original code:
```
{code}
```

Generate the corrected code. Apply only the minimal change needed to fix the accessibility issue.
Preserve indentation, formatting, and all other code exactly.
Return ONLY the fixed code, no explanation, no markdown fences.
"""


# ── LLM Bridge Class ──────────────────────────────────────────────────────────

class LLMBridge:
    """
    Routes LLM requests with automatic fallback:
    1. Configured provider
    2. Ollama (local)
    3. Heuristic-only mode (no LLM)
    """

    def __init__(self, config: LLMConfig):
        self.config = config
        self._client = httpx.AsyncClient(timeout=config.timeout)

    async def close(self) -> None:
        await self._client.aclose()

    # ── Health Check ──────────────────────────────────────────────────────────

    async def is_available(self) -> bool:
        """Check if configured LLM is reachable."""
        try:
            if self.config.provider == "ollama":
                resp = await self._client.get(f"{self.config.endpoint}/api/tags", timeout=5)
                return resp.status_code == 200
            elif self.config.provider in ("openai", "openrouter"):
                return bool(self.config.api_key)
            elif self.config.provider == "anthropic":
                return bool(self.config.api_key)
        except Exception:
            pass
        return False

    # ── Detect Violations via LLM ─────────────────────────────────────────────

    async def detect_violations(
        self,
        snippet: str,
        filename: str = "unknown",
    ) -> List[Dict[str, Any]]:
        """Send code snippet to LLM for accessibility analysis."""
        prompt = DETECT_PROMPT.format(snippet=snippet[:8000], filename=filename)

        try:
            raw = await self._complete(prompt)
            return self._parse_violations(raw)
        except Exception as e:
            logger.warning(f"[LLM] detect_violations failed: {e}")
            return []

    # ── Generate Fix via LLM ──────────────────────────────────────────────────

    async def generate_fix(
        self,
        violation: Violation,
        code: str,
    ) -> Optional[str]:
        """Ask LLM to produce a corrected code snippet."""
        prompt = FIX_PROMPT.format(
            description=violation.description,
            rule=violation.rule,
            element=violation.element,
            suggestion=violation.suggestion,
            code=code[:6000],
        )

        try:
            result = await self._complete(prompt)
            # Strip accidental markdown fences
            result = result.strip()
            if result.startswith("```"):
                lines = result.split("\n")
                result = "\n".join(
                    line for line in lines
                    if not line.strip().startswith("```")
                )
            return result.strip()
        except Exception as e:
            logger.warning(f"[LLM] generate_fix failed: {e}")
            return None

    # ── Provider Routing ──────────────────────────────────────────────────────

    async def _complete(self, prompt: str) -> str:
        provider = self.config.provider
        try:
            if provider == "ollama":
                return await self._ollama_complete(prompt)
            elif provider == "openai":
                return await self._openai_complete(prompt)
            elif provider == "anthropic":
                return await self._anthropic_complete(prompt)
            elif provider == "openrouter":
                return await self._openrouter_complete(prompt)
            else:
                raise ValueError(f"Unknown provider: {provider}")
        except Exception as e:
            logger.error(f"[LLM] Provider {provider} failed: {e}, trying Ollama fallback")
            if provider != "ollama":
                return await self._ollama_complete(prompt)
            raise

    async def _ollama_complete(self, prompt: str) -> str:
        payload = {
            "model": self.config.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.config.temperature,
                "num_predict": self.config.max_tokens,
            },
        }
        resp = await self._client.post(
            f"{self.config.endpoint}/api/generate",
            json=payload,
            timeout=self.config.timeout,
        )
        resp.raise_for_status()
        return resp.json()["response"]

    async def _openai_complete(self, prompt: str) -> str:
        payload = {
            "model": self.config.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        resp = await self._client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.config.api_key}"},
            json=payload,
            timeout=self.config.timeout,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    async def _anthropic_complete(self, prompt: str) -> str:
        payload = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        resp = await self._client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.config.api_key or "",
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
            timeout=self.config.timeout,
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]

    async def _openrouter_complete(self, prompt: str) -> str:
        payload = {
            "model": self.config.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.config.temperature,
        }
        resp = await self._client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "HTTP-Referer": "https://github.com/cprite/vera",
            },
            json=payload,
            timeout=self.config.timeout,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    # ── Response Parsing ──────────────────────────────────────────────────────

    def _parse_violations(self, raw: str) -> List[Dict[str, Any]]:
        """Extract JSON array from LLM response (handles wrapped/polluted output)."""
        raw = raw.strip()

        # Try direct parse
        try:
            result = json.loads(raw)
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

        # Find JSON array in text
        start = raw.find("[")
        end = raw.rfind("]")
        if start != -1 and end > start:
            try:
                result = json.loads(raw[start:end + 1])
                if isinstance(result, list):
                    return result
            except json.JSONDecodeError:
                pass

        logger.warning(f"[LLM] Could not parse violation JSON from response: {raw[:200]}")
        return []
