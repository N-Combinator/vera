import fs from "fs";
import path from "path";
import os from "os";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface LLMConfig {
  provider: "ollama" | "openai" | "anthropic" | "openrouter";
  model: string;
  endpoint: string;
  apiKey?: string;
  timeout?: number;
}

export interface VeraConfig {
  framework: string;
  llm: LLMConfig;
  rules: string[];
  ignore_paths: string[];
  output_format: "json" | "html" | "text";
  max_files: number;
  confidence_threshold: number;
  backend_url?: string;
}

const DEFAULT_CONFIG: VeraConfig = {
  framework: "auto",
  llm: {
    provider: "ollama",
    model: "llama3",
    endpoint: "http://localhost:11434",
    timeout: 60,
  },
  rules: [],
  ignore_paths: ["node_modules", ".git", "dist", "build", ".next", ".cache"],
  output_format: "json",
  max_files: 500,
  confidence_threshold: 0.6,
  backend_url: "http://localhost:8000",
};

const CONFIG_NAMES = [".verarc.json", ".verarc", "vera.config.json"];

// ── Find Config ───────────────────────────────────────────────────────────────

export function findConfigFile(startDir: string = process.cwd()): string | null {
  let current = path.resolve(startDir);
  for (let i = 0; i < 10; i++) {
    for (const name of CONFIG_NAMES) {
      const candidate = path.join(current, name);
      if (fs.existsSync(candidate)) return candidate;
    }
    const parent = path.dirname(current);
    if (parent === current) break;
    current = parent;
  }
  return null;
}

// ── Load Config ───────────────────────────────────────────────────────────────

export function loadConfig(configPath?: string): VeraConfig {
  const filePath = configPath ?? findConfigFile();
  let fileConfig: Partial<VeraConfig> = {};

  if (filePath && fs.existsSync(filePath)) {
    try {
      const raw = fs.readFileSync(filePath, "utf-8");
      fileConfig = JSON.parse(raw);
    } catch {
      // ignore parse errors
    }
  }

  return {
    ...DEFAULT_CONFIG,
    ...fileConfig,
    llm: {
      ...DEFAULT_CONFIG.llm,
      ...(fileConfig.llm ?? {}),
      apiKey:
        process.env.VERA_API_KEY ??
        process.env.OPENAI_API_KEY ??
        fileConfig.llm?.apiKey,
      provider: (process.env.VERA_LLM_PROVIDER as LLMConfig["provider"]) ?? fileConfig.llm?.provider ?? DEFAULT_CONFIG.llm.provider,
      model: process.env.VERA_LLM_MODEL ?? fileConfig.llm?.model ?? DEFAULT_CONFIG.llm.model,
      endpoint: process.env.VERA_LLM_ENDPOINT ?? fileConfig.llm?.endpoint ?? DEFAULT_CONFIG.llm.endpoint,
    },
    backend_url: process.env.VERA_BACKEND_URL ?? fileConfig.backend_url ?? DEFAULT_CONFIG.backend_url,
  };
}

// ── Save Config ───────────────────────────────────────────────────────────────

export function saveConfig(config: VeraConfig, outputPath: string = ".verarc.json"): void {
  const toSave = { ...config };
  // Don't persist API keys to disk
  if (toSave.llm) {
    toSave.llm = { ...toSave.llm };
    delete toSave.llm.apiKey;
  }
  fs.writeFileSync(outputPath, JSON.stringify(toSave, null, 2), "utf-8");
}
