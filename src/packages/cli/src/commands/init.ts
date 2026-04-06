import fs from "fs";
import path from "path";
import readline from "readline";
import { saveConfig, VeraConfig } from "../utils/config";

// ── Prompt helper ─────────────────────────────────────────────────────────────

function prompt(rl: readline.Interface, question: string): Promise<string> {
  return new Promise((resolve) => rl.question(question, resolve));
}

// ── Init Command ──────────────────────────────────────────────────────────────

export async function initCommand(options: { yes?: boolean }): Promise<void> {
  console.log("\n⚡ Vera — Accessibility Auto-Remediator");
  console.log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n");

  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
  });

  const yes = options.yes ?? false;

  const ask = async (q: string, def: string): Promise<string> => {
    if (yes) {
      console.log(`${q} ${def}`);
      return def;
    }
    const ans = await prompt(rl, `${q} [${def}]: `);
    return ans.trim() || def;
  };

  try {
    console.log("Let's configure Vera for your project.\n");

    // LLM Provider
    const providerInput = await ask(
      "LLM provider? (ollama/openai/anthropic/openrouter)",
      "ollama"
    );
    const provider = (["ollama", "openai", "anthropic", "openrouter"].includes(providerInput)
      ? providerInput
      : "ollama") as VeraConfig["llm"]["provider"];

    let model = "llama3";
    let endpoint = "http://localhost:11434";
    let apiKey: string | undefined;

    if (provider === "ollama") {
      model = await ask("Ollama model?", "llama3");
      endpoint = await ask("Ollama endpoint?", "http://localhost:11434");

      // Detect Ollama
      console.log("\n🔍 Checking for Ollama...");
      const ollamaRunning = await checkOllama(endpoint);
      if (!ollamaRunning) {
        console.log("⚠️  Ollama not detected at", endpoint);
        console.log("   Install Ollama: https://ollama.com");
        console.log(`   Then run: ollama pull ${model}\n`);
      } else {
        console.log(`✅ Ollama detected. Checking for model ${model}...`);
        console.log(`   If not installed: ollama pull ${model}\n`);
      }
    } else if (provider === "openai") {
      model = await ask("OpenAI model?", "gpt-4o-mini");
      apiKey = process.env.OPENAI_API_KEY;
      if (!apiKey) {
        apiKey = await ask("OpenAI API key?", "");
      }
    } else if (provider === "anthropic") {
      model = await ask("Anthropic model?", "claude-3-haiku-20240307");
      apiKey = process.env.ANTHROPIC_API_KEY ?? await ask("Anthropic API key?", "");
    } else if (provider === "openrouter") {
      model = await ask("OpenRouter model?", "meta-llama/llama-3-8b-instruct");
      apiKey = process.env.OPENROUTER_API_KEY ?? await ask("OpenRouter API key?", "");
    }

    const framework = await ask("Target framework? (auto/react/vue/html)", "auto");
    const outputFormat = await ask("Output format? (json/html/text)", "json");
    const backendUrl = await ask("Vera backend URL?", "http://localhost:8000");

    const config: VeraConfig = {
      framework,
      llm: { provider, model, endpoint, timeout: 60, apiKey },
      rules: [],
      ignore_paths: ["node_modules", ".git", "dist", "build", ".next", ".cache"],
      output_format: outputFormat as VeraConfig["output_format"],
      max_files: 500,
      confidence_threshold: 0.6,
      backend_url: backendUrl,
    };

    saveConfig(config, ".verarc.json");
    console.log("\n✅ Configuration saved to .verarc.json");

    // Write .gitignore line if not present
    const gitignorePath = path.join(process.cwd(), ".gitignore");
    if (fs.existsSync(gitignorePath)) {
      const gi = fs.readFileSync(gitignorePath, "utf-8");
      if (!gi.includes(".verarc.json")) {
        fs.appendFileSync(gitignorePath, "\n# Vera config (may contain API keys)\n# .verarc.json\n");
      }
    }

    console.log("\n🚀 Next steps:");
    console.log("  1. Start the backend:  docker-compose up -d");
    console.log("  2. Scan your code:     vera scan ./src");
    console.log("  3. Apply fixes:        vera fix ./src --apply");
    console.log("  4. Open dashboard:     vera ui\n");
  } finally {
    rl.close();
  }
}

async function checkOllama(endpoint: string): Promise<boolean> {
  try {
    const res = await fetch(`${endpoint}/api/tags`, { signal: AbortSignal.timeout(3000) });
    return res.ok;
  } catch {
    return false;
  }
}
