#!/usr/bin/env node
/**
 * vera — CLI entrypoint
 * Usage: vera <command> [options]
 */

import { Command } from "commander";
import { initCommand } from "../src/commands/init";
import { scanCommand } from "../src/commands/scan";
import { fixCommand } from "../src/commands/fix";
import { uiCommand } from "../src/commands/ui";
import { describeCommand } from "../src/commands/describe";

const program = new Command();

program
  .name("vera")
  .description("⚡ Vera — AI-powered accessibility auto-remediator")
  .version("1.0.0");

// ── init ──────────────────────────────────────────────────────────────────────
program
  .command("init")
  .description("Initialize Vera configuration (.verarc.json)")
  .option("-y, --yes", "Accept all defaults without prompting")
  .action((opts) => initCommand(opts));

// ── scan ──────────────────────────────────────────────────────────────────────
program
  .command("scan <path>")
  .description("Scan a path for accessibility violations")
  .option("-o, --output <file>", "Write report to file")
  .option("-f, --format <fmt>", "Output format: json|html|text", "text")
  .option("-r, --rules <rules>", "Comma-separated rule IDs to check")
  .option("--framework <fw>", "Framework: auto|react|vue|html")
  .option("--no-llm", "Disable LLM analysis (heuristics only)")
  .option("-q, --quiet", "Suppress output (exit code only)")
  .action((targetPath, opts) =>
    scanCommand(targetPath, {
      output:    opts.output,
      format:    opts.format,
      rules:     opts.rules,
      framework: opts.framework,
      quiet:     opts.quiet,
      noLlm:     opts.noLlm,
    })
  );

// ── fix ───────────────────────────────────────────────────────────────────────
program
  .command("fix <path>")
  .description("Apply accessibility fixes to a path")
  .option("--apply", "Write fixes to disk (default: dry run)")
  .option("--dry-run", "Preview fixes without writing")
  .option("--scan-id <id>", "Use results from a previous scan")
  .option("--violations <ids>", "Comma-separated violation IDs to fix")
  .option("-y, --yes", "Skip confirmation prompt")
  .option("-q, --quiet", "Suppress output")
  .action((targetPath, opts) =>
    fixCommand(targetPath, {
      apply:      opts.apply,
      dryRun:     opts.dryRun,
      scanId:     opts.scanId,
      violations: opts.violations,
      yes:        opts.yes,
      quiet:      opts.quiet,
    })
  );

// ── describe (Vera-Describe, opt-in) ──────────────────────────────────────────
program
  .command("describe <path>")
  .alias("check-alt")
  .description("AI alt-text quality review (WCAG 1.1.1) — suggest-only, never writes")
  .option("--api-key <key>", "Anthropic API key (else ANTHROPIC_API_KEY env)")
  .option("--model <model>", "Vision model", "claude-sonnet-4-6")
  .option("-o, --output <file>", "Write JSON report to file")
  .option("-q, --quiet", "Suppress output; exit non-zero if weak/missing found (CI)")
  .action((targetPath, opts) =>
    describeCommand(targetPath, {
      apiKey: opts.apiKey,
      model:  opts.model,
      output: opts.output,
      quiet:  opts.quiet,
    })
  );

// ── ui ────────────────────────────────────────────────────────────────────────
program
  .command("ui")
  .description("Launch the Vera dashboard")
  .option("-p, --port <port>", "Port to serve on", "3000")
  .option("--no-open", "Don't open browser automatically")
  .action((opts) =>
    uiCommand({
      port: parseInt(opts.port, 10),
      open: opts.open !== false,
    })
  );

// ── parse ─────────────────────────────────────────────────────────────────────
program.parse(process.argv);

if (!process.argv.slice(2).length) {
  program.outputHelp();
}
