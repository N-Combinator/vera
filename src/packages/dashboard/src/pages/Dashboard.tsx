import React, { useEffect, useState, useCallback } from "react";
import { useDispatch, useSelector } from "react-redux";
import type { AppDispatch, RootState } from "../store";
import {
  runScan,
  runFix,
  loadReports,
  selectViolation,
  setFixPreview,
  clearError,
  setScanPath,
  type Violation,
} from "../store";
import { IssueCard } from "../components/IssueCard";
import { FixPreview } from "../components/FixPreview";
import { ReportViewer } from "../components/ReportViewer";

// ── Dashboard ─────────────────────────────────────────────────────────────────

type View = "scan" | "report" | "reports";

export const Dashboard: React.FC = () => {
  const dispatch = useDispatch<AppDispatch>();
  const { scan, loading, fixing, error, selectedViolation, fixes, fixPreview, scanPath, backendUrl } =
    useSelector((s: RootState) => s.vera);

  const [view, setView] = useState<View>("scan");
  const [useLlm, setUseLlm] = useState(true);
  const [filterSev, setFilterSev] = useState<string>("all");
  const [healthStatus, setHealthStatus] = useState<"unknown" | "ok" | "error">("unknown");

  // ── Backend Health Check ───────────────────────────────────────────────────

  useEffect(() => {
    fetch(`${backendUrl}/health`)
      .then((r) => r.json())
      .then(() => setHealthStatus("ok"))
      .catch(() => setHealthStatus("error"));
  }, [backendUrl]);

  // ── Actions ────────────────────────────────────────────────────────────────

  const handleScan = useCallback(() => {
    dispatch(runScan({ path: scanPath, useLlm }));
    setView("report");
  }, [dispatch, scanPath, useLlm]);

  const handleFix = useCallback(
    (violationId?: string) => {
      if (!scan) return;
      dispatch(
        runFix({
          path: scan.target,
          scanId: scan.scan_id,
          violationIds: violationId ? [violationId] : undefined,
          dryRun: true,
        })
      ).then((action: any) => {
        const fix = action.payload?.fixes?.[0];
        if (fix) dispatch(setFixPreview(fix));
      });
    },
    [dispatch, scan]
  );

  const handleApplyFix = useCallback(() => {
    if (!scan || !fixPreview) return;
    dispatch(
      runFix({
        path: scan.target,
        scanId: scan.scan_id,
        violationIds: [fixPreview.violation_id],
        dryRun: false,
      })
    );
    dispatch(setFixPreview(null));
  }, [dispatch, scan, fixPreview]);

  const handleExport = useCallback(
    (format: "json" | "html") => {
      if (!scan) return;
      const content =
        format === "json"
          ? JSON.stringify(scan, null, 2)
          : generateHtmlExport(scan);
      const blob = new Blob([content], {
        type: format === "json" ? "application/json" : "text/html",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `vera-report-${scan.scan_id}.${format}`;
      a.click();
      URL.revokeObjectURL(url);
    },
    [scan]
  );

  // ── Filtered violations ───────────────────────────────────────────────────

  const filteredViolations = scan?.violations.filter(
    (v) => filterSev === "all" || v.severity === filterSev
  ) ?? [];

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      {/* Nav */}
      <header className="border-b border-slate-800 bg-slate-950/90 backdrop-blur sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-2xl">⚡</span>
            <span className="font-bold text-lg text-white">Vera</span>
            <span className="text-slate-500 text-sm">Accessibility Auto-Remediator</span>
          </div>

          <div className="flex items-center gap-4">
            <div className="flex items-center gap-1.5">
              <span
                className={`w-2 h-2 rounded-full ${
                  healthStatus === "ok" ? "bg-green-500" : healthStatus === "error" ? "bg-red-500" : "bg-slate-600"
                }`}
              />
              <span className="text-xs text-slate-500">
                {healthStatus === "ok" ? "Backend OK" : healthStatus === "error" ? "Backend offline" : "Checking..."}
              </span>
            </div>

            <nav className="flex gap-1">
              {(["scan", "report", "reports"] as View[]).map((v) => (
                <button
                  key={v}
                  className={`text-sm px-3 py-1.5 rounded-lg capitalize transition-colors ${
                    view === v
                      ? "bg-violet-700 text-white"
                      : "text-slate-400 hover:text-white hover:bg-slate-800"
                  }`}
                  onClick={() => {
                    setView(v);
                    if (v === "reports") dispatch(loadReports());
                  }}
                >
                  {v}
                </button>
              ))}
            </nav>
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-8">
        {/* Error banner */}
        {error && (
          <div className="mb-6 bg-red-950/40 border border-red-800 rounded-xl px-4 py-3 flex items-center justify-between">
            <span className="text-red-300 text-sm">❌ {error}</span>
            <button onClick={() => dispatch(clearError())} className="text-red-500 hover:text-red-300">✕</button>
          </div>
        )}

        {/* ── SCAN VIEW ─────────────────────────────────────────────────────── */}
        {view === "scan" && (
          <div className="max-w-lg mx-auto space-y-6">
            <div>
              <h1 className="text-3xl font-bold text-white mb-2">Scan Your Code</h1>
              <p className="text-slate-400">Find accessibility violations and generate auto-fixes.</p>
            </div>

            <div className="bg-slate-900 border border-slate-700 rounded-2xl p-6 space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">
                  Target Path
                </label>
                <input
                  type="text"
                  value={scanPath}
                  onChange={(e) => dispatch(setScanPath(e.target.value))}
                  className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-white text-sm font-mono focus:ring-2 focus:ring-violet-500 focus:border-transparent outline-none"
                  placeholder="./src"
                />
              </div>

              <label className="flex items-center gap-3 cursor-pointer">
                <div
                  className={`w-10 h-6 rounded-full transition-colors ${useLlm ? "bg-violet-600" : "bg-slate-700"}`}
                  onClick={() => setUseLlm(!useLlm)}
                >
                  <div
                    className={`w-4 h-4 bg-white rounded-full m-1 transition-transform ${useLlm ? "translate-x-4" : ""}`}
                  />
                </div>
                <span className="text-sm text-slate-300">Use AI analysis (LLM)</span>
              </label>

              <button
                onClick={handleScan}
                disabled={loading || !scanPath}
                className="w-full bg-violet-700 hover:bg-violet-600 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold py-3 rounded-xl transition-colors"
              >
                {loading ? "Scanning..." : "⚡ Scan Now"}
              </button>
            </div>

            {scan && (
              <div
                className="bg-slate-900 border border-slate-700 rounded-2xl p-4 cursor-pointer hover:bg-slate-800 transition-colors"
                onClick={() => setView("report")}
              >
                <p className="text-sm text-slate-300">
                  Last scan: <span className="text-white font-semibold">{scan.violations.length}</span> violations
                  in <span className="text-slate-400">{scan.target}</span>
                </p>
              </div>
            )}
          </div>
        )}

        {/* ── REPORT VIEW ───────────────────────────────────────────────────── */}
        {view === "report" && (
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
            {/* Left: issue list */}
            <div className="xl:col-span-2 space-y-4">
              {loading ? (
                <div className="text-center py-20">
                  <div className="text-5xl mb-4 animate-spin">⚡</div>
                  <p className="text-slate-400">Scanning...</p>
                </div>
              ) : scan ? (
                <>
                  {/* Filter bar */}
                  <div className="flex gap-2 flex-wrap">
                    {["all", "critical", "serious", "moderate", "minor"].map((sev) => (
                      <button
                        key={sev}
                        className={`text-xs px-3 py-1.5 rounded-full capitalize transition-colors ${
                          filterSev === sev
                            ? "bg-violet-700 text-white"
                            : "bg-slate-800 text-slate-400 hover:text-white"
                        }`}
                        onClick={() => setFilterSev(sev)}
                      >
                        {sev}
                        {sev !== "all" && (
                          <span className="ml-1 opacity-70">
                            ({scan.violations.filter((v) => v.severity === sev).length})
                          </span>
                        )}
                      </button>
                    ))}
                  </div>

                  <div className="space-y-3">
                    {filteredViolations.length === 0 && (
                      <p className="text-slate-500 text-center py-8">No violations for this filter.</p>
                    )}
                    {filteredViolations.map((v) => (
                      <IssueCard
                        key={v.id}
                        violation={v}
                        selected={selectedViolation?.id === v.id}
                        onClick={() => dispatch(selectViolation(v))}
                        onFix={() => handleFix(v.id)}
                      />
                    ))}
                  </div>

                  {/* Fix all */}
                  {filteredViolations.some((v) => v.fix_available) && (
                    <button
                      onClick={() => handleFix()}
                      disabled={fixing}
                      className="w-full bg-slate-800 hover:bg-slate-700 disabled:opacity-50 text-slate-200 text-sm font-semibold py-3 rounded-xl border border-slate-600 transition-colors"
                    >
                      {fixing ? "Generating fixes..." : `🔧 Fix All (${filteredViolations.filter((v) => v.fix_available).length})`}
                    </button>
                  )}
                </>
              ) : (
                <div className="text-center py-20">
                  <p className="text-slate-500">No scan results yet. Run a scan first.</p>
                  <button
                    className="mt-4 text-violet-400 hover:underline text-sm"
                    onClick={() => setView("scan")}
                  >
                    Go to Scan →
                  </button>
                </div>
              )}
            </div>

            {/* Right: detail panel */}
            <div className="space-y-4">
              {fixPreview ? (
                <FixPreview
                  fix={fixPreview}
                  onApply={handleApplyFix}
                  onDismiss={() => dispatch(setFixPreview(null))}
                />
              ) : selectedViolation ? (
                <ViolationDetail violation={selectedViolation} onFix={() => handleFix(selectedViolation.id)} />
              ) : scan ? (
                <ReportViewer scan={scan} onViolationClick={(v) => dispatch(selectViolation(v))} onExport={handleExport} />
              ) : null}
            </div>
          </div>
        )}

        {/* ── REPORTS VIEW ──────────────────────────────────────────────────── */}
        {view === "reports" && (
          <div className="space-y-4">
            <h2 className="text-xl font-bold text-white">Scan History</h2>
            {scan ? (
              <div className="bg-slate-900 border border-slate-700 rounded-2xl p-4 flex items-center justify-between">
                <div>
                  <p className="text-white font-medium">{scan.target}</p>
                  <p className="text-slate-400 text-sm">
                    {scan.violations.length} violations · {scan.total_files_scanned} files · {scan.scan_duration_ms}ms
                  </p>
                </div>
                <button
                  className="text-violet-400 text-sm hover:underline"
                  onClick={() => setView("report")}
                >
                  View →
                </button>
              </div>
            ) : (
              <p className="text-slate-500 text-center py-8">No scans yet.</p>
            )}
          </div>
        )}
      </main>
    </div>
  );
};

// ── Violation Detail Panel ────────────────────────────────────────────────────

const ViolationDetail: React.FC<{ violation: Violation; onFix?: () => void }> = ({
  violation,
  onFix,
}) => (
  <div className="bg-slate-900 border border-slate-700 rounded-2xl p-5 space-y-4">
    <div>
      <span className="text-xs text-violet-400 font-mono">{violation.rule}</span>
      <h3 className="text-white font-semibold mt-1">{violation.description}</h3>
    </div>

    {violation.location && (
      <p className="text-xs font-mono text-slate-500">
        {violation.location.file}:{violation.location.line}
      </p>
    )}

    <div className="bg-slate-800 rounded-lg p-3">
      <p className="text-xs text-slate-400 mb-1 font-semibold">SUGGESTION</p>
      <p className="text-sm text-slate-200">{violation.suggestion}</p>
    </div>

    {violation.code_snippet && (
      <div>
        <p className="text-xs text-slate-400 mb-1 font-semibold">CODE</p>
        <pre className="text-xs font-mono bg-slate-800 border border-slate-700 rounded-lg p-3 overflow-auto max-h-32 text-slate-300 whitespace-pre-wrap">
          {violation.code_snippet}
        </pre>
      </div>
    )}

    <div className="flex items-center gap-3 text-xs text-slate-500">
      {violation.wcag_criterion && <span>WCAG {violation.wcag_criterion}</span>}
      <span>{Math.round(violation.confidence * 100)}% confidence</span>
      {violation.ai_generated && <span className="text-violet-400">AI detected</span>}
    </div>

    {violation.fix_available && onFix && (
      <button
        onClick={onFix}
        className="w-full bg-violet-700 hover:bg-violet-600 text-white text-sm font-semibold py-2.5 rounded-xl transition-colors"
      >
        🔧 Generate Fix
      </button>
    )}
  </div>
);

// ── HTML export helper ────────────────────────────────────────────────────────

function generateHtmlExport(scan: any): string {
  return `<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><title>Vera Report</title>
<style>body{font-family:system-ui;background:#0f172a;color:#e2e8f0;padding:2rem}
h1{color:#7c3aed}table{border-collapse:collapse;width:100%;margin-top:1rem}
th,td{text-align:left;padding:.5rem .75rem;border-bottom:1px solid #1e293b;font-size:.85rem}
th{color:#64748b}.critical{color:#f87171}.serious{color:#fbbf24}.moderate{color:#67e8f9}.minor{color:#94a3b8}
</style></head><body>
<h1>⚡ Vera Report</h1>
<p>${scan.target} · ${scan.violations.length} violations · ${scan.total_files_scanned} files</p>
<table><thead><tr><th>Severity</th><th>Rule</th><th>Location</th><th>Description</th><th>Suggestion</th></tr></thead>
<tbody>${scan.violations.map((v: any) =>
  `<tr><td class="${v.severity}">${v.severity}</td><td>${v.rule}</td>
   <td>${v.location?.file ?? ""}:${v.location?.line ?? ""}</td>
   <td>${v.description}</td><td>${v.suggestion}</td></tr>`).join("")}
</tbody></table></body></html>`;
}
