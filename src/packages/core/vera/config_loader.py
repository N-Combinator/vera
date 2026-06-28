"""
Vera — Configuration loader (.verarc.json / env vars).
"""

from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Optional
from .models import VeraConfig, LLMConfig


DEFAULT_CONFIG_NAMES = [".verarc.json", ".verarc", "vera.config.json"]


def find_config_file(start_path: str = ".") -> Optional[Path]:
    """Walk up directory tree looking for a vera config file."""
    current = Path(start_path).resolve()
    for _ in range(10):  # max 10 levels up
        for name in DEFAULT_CONFIG_NAMES:
            candidate = current / name
            if candidate.exists():
                return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def load_config(config_path: Optional[str] = None) -> VeraConfig:
    """
    Load VeraConfig from file + environment variables.
    Priority: env vars > config file > defaults.
    """
    raw: dict = {}

    # 1. Find and load config file
    path = Path(config_path) if config_path else find_config_file()
    if path and path.exists():
        try:
            with open(path) as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[vera] Warning: Could not load config from {path}: {e}")

    # 2. Build LLM config with env overrides
    llm_raw = raw.get("llm", {})

    llm = LLMConfig(
        provider=os.getenv("VERA_LLM_PROVIDER", llm_raw.get("provider", "ollama")),
        model=os.getenv("VERA_LLM_MODEL", llm_raw.get("model", "llama3")),
        endpoint=os.getenv("VERA_LLM_ENDPOINT", llm_raw.get("endpoint", "http://localhost:11434")),
        api_key=(
            os.getenv("VERA_API_KEY")
            or os.getenv("ANTHROPIC_API_KEY")
            or os.getenv("OPENROUTER_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or llm_raw.get("api_key")
        ),
        timeout=int(os.getenv("VERA_LLM_TIMEOUT", str(llm_raw.get("timeout", 60)))),
        temperature=float(llm_raw.get("temperature", 0.1)),
        max_tokens=int(llm_raw.get("max_tokens", 2048)),
    )

    config = VeraConfig(
        framework=os.getenv("VERA_FRAMEWORK", raw.get("framework", "auto")),
        llm=llm,
        rules=raw.get("rules", []),
        ignore_paths=raw.get("ignore_paths", VeraConfig.model_fields["ignore_paths"].default),
        output_format=os.getenv("VERA_OUTPUT_FORMAT", raw.get("output_format", "json")),
        max_files=int(raw.get("max_files", 500)),
        confidence_threshold=float(raw.get("confidence_threshold", 0.6)),
    )

    return config


def save_config(config: VeraConfig, path: str = ".verarc.json") -> None:
    """Serialize and save config to disk."""
    data = {
        "framework": config.framework,
        "llm": {
            "provider": config.llm.provider,
            "model": config.llm.model,
            "endpoint": config.llm.endpoint,
            "timeout": config.llm.timeout,
            "temperature": config.llm.temperature,
            "max_tokens": config.llm.max_tokens,
        },
        "rules": config.rules,
        "ignore_paths": config.ignore_paths,
        "output_format": config.output_format,
        "max_files": config.max_files,
        "confidence_threshold": config.confidence_threshold,
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
