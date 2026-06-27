import path from "path";
import { createClient, AltEvaluation } from "../utils/api-client";
import { loadConfig } from "../utils/config";

// ── Describe Command (Vera-Describe, opt-in) ───────────────────────────────────
//
// AI alt-text quality review (WCAG 1.1.1). Suggest-only: prints findings and
// suggested alt text, NEVER writes files or applies changes.

export interface DescribeOptions {
  apiKey?: string;
  model?: string;
  output?: string;   // write JSON report to file
  quiet?: boolean;
}

export async function describeCommand(
  target: string,
  options: DescribeOptions
): Promise<void> {
  const cfg = loadConfig();
  const client = createClient(cfg.backend_url);
  // URLs pass through unchanged; local paths are resolved.
  const isUrl = /^https?:\/\//i.test(target);
  const resolved = isUrl ? target : path.resolve(target);

  if (!options.quiet) {
    console.log(`\n🖼️  Vera-Describe — ${resolved}`);
    console.log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
    console.log("ℹ️  Suggest-only — no files are changed.\n");
  }

  let res;
  try {
    res = await client.describe({
      path: resolved,
      api_key: options.apiKey ?? process.env.ANTHROPIC_API_KEY,
      model: options.model,
    });
  } catch (err: any) {
    console.error("❌ Describe failed:", err.message);
    process.exit(1);
  }

  if (options.output) {
    const fs = await import("fs");
    fs.writeFileSync(options.output, JSON.stringify(res, null, 2), "utf-8");
    if (!options.quiet) console.log(`📄 Report saved to ${options.output}`);
  }

  if (options.quiet) {
    // CI mode: exit non-zero if any image needs attention.
    const bad = res.summary.weak + res.summary.missing;
    process.exit(bad > 0 ? 1 : 0);
  }

  for (const e of res.evaluations) {
    printEvaluation(e);
  }

  const s = res.summary;
  console.log(`\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`);
  console.log(
    `📊 ${res.images_found} image(s): ` +
      `✅ ${s.pass} pass · △ ${s.weak} weak · ✗ ${s.missing} missing · ⊘ ${s.skipped} skipped`
  );
  if (s.weak + s.missing > 0) {
    console.log(`\n💡 Review the suggestions above and apply the ones that fit.`);
  }
}

function printEvaluation(e: AltEvaluation): void {
  if (e.verdict === "skipped") return;   // decorative / out-of-scope — stay quiet
  const icon = e.verdict === "missing" ? "✗" : e.verdict === "weak" ? "△" : "✅";
  console.log(`\n${icon} [${e.verdict}] ${e.src}  (${e.role})`);
  if (e.existing_alt != null && e.existing_alt !== "") {
    console.log(`   current: alt="${e.existing_alt}"`);
  }
  for (const r of e.reasons ?? []) console.log(`   · ${r}`);
  if (e.suggested_alt) {
    console.log(`\x1b[32m   suggested: alt="${e.suggested_alt}"\x1b[0m`);
  }
}
