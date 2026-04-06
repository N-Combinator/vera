import { exec, spawn } from "child_process";
import path from "path";
import { loadConfig } from "../utils/config";
import { createClient } from "../utils/api-client";

// ── UI Command ────────────────────────────────────────────────────────────────

export interface UiOptions {
  port?: number;
  open?: boolean;
}

export async function uiCommand(options: UiOptions): Promise<void> {
  const cfg = loadConfig();
  const port = options.port ?? 3000;
  const client = createClient(cfg.backend_url);

  console.log(`\n⚡ Vera Dashboard`);
  console.log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n");

  // Check backend
  try {
    await client.health();
    console.log(`✅ Backend connected: ${cfg.backend_url}`);
  } catch {
    console.warn(`⚠️  Backend not reachable at ${cfg.backend_url}`);
    console.warn(`   Start with: docker-compose up -d\n`);
  }

  // Try to locate dashboard dist
  const dashboardPaths = [
    path.resolve(__dirname, "../../dashboard/dist/index.html"),
    path.resolve(process.cwd(), "src/packages/dashboard/dist/index.html"),
  ];

  const builtDashboard = dashboardPaths.find((p) => {
    try {
      return require("fs").existsSync(p);
    } catch {
      return false;
    }
  });

  if (builtDashboard) {
    // Serve built dashboard via local static server
    await serveStatic(path.dirname(builtDashboard), port, options.open ?? true);
  } else {
    // Launch dashboard dev server
    const dashboardDir = path.resolve(
      __dirname,
      "../../dashboard"
    );

    console.log(`🚀 Starting dashboard dev server on http://localhost:${port}`);
    console.log(`   (Building first time may take ~30 seconds)\n`);

    const proc = spawn("npm", ["run", "dev", "--", `--port=${port}`], {
      cwd: dashboardDir,
      stdio: "inherit",
      shell: true,
      env: {
        ...process.env,
        VITE_BACKEND_URL: cfg.backend_url ?? "http://localhost:8000",
        PORT: String(port),
      },
    });

    proc.on("error", (err) => {
      if ((err as any).code === "ENOENT") {
        console.error("❌ npm not found. Install Node.js first.");
      } else {
        console.error("❌ Dashboard start failed:", err.message);
        console.log("\nManual start:");
        console.log(`  cd src/packages/dashboard && npm install && npm run dev`);
      }
    });

    if (options.open !== false) {
      setTimeout(() => openBrowser(`http://localhost:${port}`), 3000);
    }

    process.on("SIGINT", () => {
      proc.kill();
      process.exit(0);
    });
  }
}

function serveStatic(dir: string, port: number, openBrowserFlag: boolean): Promise<void> {
  return new Promise((resolve, reject) => {
    const http = require("http");
    const fs = require("fs");
    const pathMod = require("path");

    const mimeTypes: Record<string, string> = {
      ".html": "text/html",
      ".js": "application/javascript",
      ".css": "text/css",
      ".json": "application/json",
      ".png": "image/png",
      ".svg": "image/svg+xml",
    };

    const server = http.createServer((req: any, res: any) => {
      let filePath = pathMod.join(dir, req.url === "/" ? "index.html" : req.url);
      if (!fs.existsSync(filePath)) filePath = pathMod.join(dir, "index.html"); // SPA fallback

      const ext = pathMod.extname(filePath);
      res.setHeader("Content-Type", mimeTypes[ext] ?? "application/octet-stream");
      fs.createReadStream(filePath).pipe(res);
    });

    server.listen(port, () => {
      console.log(`🌐 Dashboard running at http://localhost:${port}`);
      if (openBrowserFlag) openBrowser(`http://localhost:${port}`);
      console.log("   Press Ctrl+C to stop.\n");
    });

    server.on("error", (err: Error) => {
      if ((err as any).code === "EADDRINUSE") {
        console.error(`❌ Port ${port} already in use. Use --port <n>`);
      }
      reject(err);
    });
  });
}

function openBrowser(url: string): void {
  const cmds: Record<string, string> = {
    darwin: `open "${url}"`,
    linux:  `xdg-open "${url}" 2>/dev/null || true`,
    win32:  `start "" "${url}"`,
  };
  const cmd = cmds[process.platform];
  if (cmd) exec(cmd);
}
