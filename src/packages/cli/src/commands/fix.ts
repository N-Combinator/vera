import fs from "fs";
import path from "path";
import readline from "readline";
import { createClient, Fix } from "../utils/api-client";
import { loadConfig } from "../utils/config";

// ── Fix Command ───────────────────────────────────────────────────────────────

export interface FixOptions {
  apply?: boolean;
  dryRun?: boolean;
  scanId?: string;
  violations?: string;  // comma-separated IDs
  yes?: boolean;        // skip confirmation
  quiet?: boolean;
}

export async function fixCommand(
  targetPath: string,
  options: FixOptions
): Promise<void> {
  const cfg = loadConfig();
  const client = createClient(cfg.backend_url);
  const absPath = path.resolve(targetPath);

  if (!options.quiet) {
    console.log(`\n🔧 Vera Fix — ${absPath}`);
    console.log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n");
  }

  const isDryRun = options.dryRun ?? !options.apply;

  if (isDryRun && !options.quiet) {
    console.log("ℹ️  Dry run mode (no files will be changed). Use --apply to write fixes.\n");
  }

  let response;
  try {
    response = await client.fix({
      path: absPath,
      scan_id: options.scanId,
      violation_ids: options.violations?.split(",").map((v) => v.trim()),
      dry_run: isDryRun,
    });
  } catch (err: any) {
    console.error("❌ Fix failed:", err.message);
    process.exit(1);
  }

  const { fixes, fixes_applied, fixes_skipped, errors } = response;

  if (fixes.length === 0) {
    console.log("✅ No fixable violations found.\n");
    return;
  }

  // Show preview
  if (!options.quiet) {
    for (const fix of fixes) {
      printFixPreview(fix);
    }
  }

  // Confirm if --apply and not --yes
  if (options.apply && !isDryRun && !options.yes && !options.quiet) {
    const confirmed = await confirmApply(fixes.length);
    if (!confirmed) {
      console.log("\n⏸  Fixes cancelled.\n");
      return;
    }
  }

  // Summary
  if (!options.quiet) {
    console.log(`\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`);
    if (isDryRun) {
      console.log(`📋 Dry run: ${fixes.length} fix(es) would be applied`);
    } else {
      console.log(`✅ ${fixes_applied} fix(es) applied`);
      if (fixes_skipped > 0) console.log(`⏭  ${fixes_skipped} skipped`);
    }

    if (errors.length > 0) {
      console.log(`\n⚠️  Errors:`);
      for (const e of errors) console.log(`   ${e}`);
    }

    if (!isDryRun && fixes_applied > 0) {
      console.log(`\n💡 Run 'vera scan ${targetPath}' to verify.\n`);
    }
  }
}

// ── Print Fix Preview ─────────────────────────────────────────────────────────

function printFixPreview(fix: Fix): void {
  const rel = path.relative(process.cwd(), fix.file);
  console.log(`\n📄 ${rel}`);
  console.log(`   ${fix.description}`);

  if (fix.diff) {
    const lines = fix.diff.split("\n").slice(0, 20); // limit output
    for (const line of lines) {
      if (line.startsWith("+") && !line.startsWith("+++")) {
        process.stdout.write(`\x1b[32m${line}\x1b[0m\n`);
      } else if (line.startsWith("-") && !line.startsWith("---")) {
        process.stdout.write(`\x1b[31m${line}\x1b[0m\n`);
      } else if (line.startsWith("@@")) {
        process.stdout.write(`\x1b[36m${line}\x1b[0m\n`);
      } else {
        console.log(line);
      }
    }
  } else {
    console.log(`   Before: ${fix.original_code.split("\n")[0]}`);
    console.log(`   After:  ${fix.fixed_code.split("\n")[0]}`);
  }
}

// ── Confirm Prompt ────────────────────────────────────────────────────────────

async function confirmApply(count: number): Promise<boolean> {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  return new Promise((resolve) => {
    rl.question(`\n❓ Apply ${count} fix(es) to disk? (y/N) `, (ans) => {
      rl.close();
      resolve(ans.trim().toLowerCase() === "y");
    });
  });
}
