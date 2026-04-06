import fs from "fs";
import path from "path";
import { createClient, ScanResult, Violation } from "../utils/api-client";
import { loadConfig } from "../utils/config";

// ── Severity colours (ANSI) ───────────────────────────────────────────────────

const SEVERITY_COLOUR: Record<string, string> = {
  critical: "\x1b[31m", // red
  serious:  "\x1b[33m", // yellow
  moderate: "\x1b[36m", // cyan
  minor:    "\x1b[90m", // grey
};
const RESET = "\x1b[0m";

function coloured(sev: string, text: string): string {
  return (SEVERITY_COLOUR[sev] ?? "") + text + RESET;
}

// ── Scan Command ──────────────────────────────────────────────────────────────

export interface ScanOptions {
  output?: string;   // output file
  format?: string;   // json | html | text
  rules?: string;    // comma-separated rule IDs
  quiet?: boolean;
  noLlm?: boolean;
  framework?: string;
}

export async function scanCommand(
  targetPath: string,
  options: ScanOptions
): Promise<void> {
  const cfg = loadConfig();
  const client = createClient(cfg.backend_url);
  const absPath = path.resolve(targetPath);

  if (!fs.existsSync(absPath)) {
    console.error(`❌ Path not found: ${absPath}`);
    process.exit(1);
  }

  if (!options.quiet) {
    console.log(`\n⚡ Vera — Scanning ${absPath}`);
    console.log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n");
  }

  let result: ScanResult;
  try {
    result = await client.scan({
      path: absPath,
      framework: options.framework ?? cfg.framework,
      rules: options.rules?.split(",").map((r) => r.trim()),
      use_llm: !options.noLlm,
    });
  } catch (err: any) {
    console.error("❌ Scan failed:", err.message);
    process.exit(1);
  }

  // Output results
  const format = options.format ?? cfg.output_format ?? "text";

  if (format === "json" || options.output?.endsWith(".json")) {
    const json = JSON.stringify(result, null, 2);
    if (options.output) {
      fs.writeFileSync(options.output, json, "utf-8");
      if (!options.quiet) console.log(`📄 Report saved to ${options.output}`);
    } else {
      console.log(json);
    }
    return;
  }

  if (format === "html") {
    const html = generateHtmlReport(result);
    const outFile = options.output ?? "vera-report.html";
    fs.writeFileSync(outFile, html, "utf-8");
    if (!options.quiet) console.log(`📄 HTML report saved to ${outFile}`);
    return;
  }

  // Default: text/pretty output
  if (!options.quiet) {
    printTextReport(result);
  }

  // Exit 1 if violations found (for CI)
  if (result.violations.length > 0) {
    process.exit(1);
  }
}

// ── Text Report ───────────────────────────────────────────────────────────────

function printTextReport(result: ScanResult): void {
  const { violations, total_files_scanned, scan_duration_ms, scan_id } = result;

  if (violations.length === 0) {
    console.log("✅ No accessibility violations found!\n");
    console.log(`   Scanned ${total_files_scanned} files in ${scan_duration_ms}ms`);
    return;
  }

  // Group by file
  const byFile = new Map<string, Violation[]>();
  for (const v of violations) {
    const fp = v.location?.file ?? result.target;
    const existing = byFile.get(fp) ?? [];
    existing.push(v);
    byFile.set(fp, existing);
  }

  for (const [file, viols] of byFile) {
    const rel = path.relative(process.cwd(), file);
    console.log(`\n📄 ${rel}`);
    for (const v of viols) {
      const loc = v.location ? `:${v.location.line}` : "";
      const badge = coloured(v.severity, `[${v.severity.toUpperCase()}]`);
      console.log(`  ${badge} ${v.rule}${loc}`);
      console.log(`    ${v.description}`);
      console.log(`    💡 ${v.suggestion}`);
      if (v.wcag_criterion) console.log(`    WCAG ${v.wcag_criterion}`);
      if (v.fix_available) console.log(`    🔧 Fix available`);
    }
  }

  const critical = violations.filter((v) => v.severity === "critical").length;
  const serious  = violations.filter((v) => v.severity === "serious").length;

  console.log(`\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`);
  console.log(`📊 Summary: ${violations.length} violation(s) across ${total_files_scanned} files`);
  if (critical > 0) console.log(`   🔴 ${critical} critical`);
  if (serious > 0)  console.log(`   🟡 ${serious} serious`);
  console.log(`   ⏱  Scanned in ${scan_duration_ms}ms`);
  if (result.llm_provider) console.log(`   🤖 AI: ${result.llm_provider}`);
  console.log(`\n   Scan ID: ${scan_id}`);
  console.log(`   Run 'vera fix ${result.target}' to apply fixes.\n`);
}

// ── HTML Report ───────────────────────────────────────────────────────────────

function generateHtmlReport(result: ScanResult): string {
  const rows = result.violations
    .map(
      (v) => `
    <tr class="sev-${v.severity}">
      <td><span class="badge ${v.severity}">${v.severity}</span></td>
      <td><code>${escHtml(v.rule)}</code></td>
      <td>${escHtml(v.location?.file ?? "")}:${v.location?.line ?? ""}</td>
      <td>${escHtml(v.description)}</td>
      <td>${escHtml(v.suggestion)}</td>
      <td>${v.wcag_criterion ?? ""}</td>
    </tr>`
    )
    .join("\n");

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Vera Accessibility Report</title>
<style>
  body { font-family: system-ui, sans-serif; background: #0f172a; color: #e2e8f0; padding: 2rem; }
  h1 { color: #7c3aed; } h2 { color: #94a3b8; font-size: 1rem; }
  table { border-collapse: collapse; width: 100%; margin-top: 1.5rem; }
  th, td { text-align: left; padding: 0.6rem 1rem; border-bottom: 1px solid #1e293b; font-size: 0.9rem; }
  th { color: #64748b; }
  code { background: #1e293b; padding: 2px 6px; border-radius: 4px; font-size: 0.85em; }
  .badge { border-radius: 4px; padding: 2px 8px; font-size: 0.8em; font-weight: bold; }
  .critical { background: #7f1d1d; color: #fca5a5; }
  .serious  { background: #78350f; color: #fde68a; }
  .moderate { background: #164e63; color: #67e8f9; }
  .minor    { background: #1e293b; color: #94a3b8; }
</style>
</head>
<body>
<h1>⚡ Vera Accessibility Report</h1>
<h2>Target: ${escHtml(result.target)} | ${result.violations.length} violations | ${result.total_files_scanned} files | ${result.scan_duration_ms}ms</h2>
<table>
  <thead><tr><th>Severity</th><th>Rule</th><th>Location</th><th>Description</th><th>Suggestion</th><th>WCAG</th></tr></thead>
  <tbody>${rows}</tbody>
</table>
</body>
</html>`;
}

function escHtml(s: string): string {
  return (s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}
