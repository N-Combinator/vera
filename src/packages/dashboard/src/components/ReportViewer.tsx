import React, { useMemo } from "react";
import type { ScanResult, Violation } from "../store";

// ── Types ─────────────────────────────────────────────────────────────────────

interface ReportViewerProps {
  scan: ScanResult;
  onViolationClick?: (v: Violation) => void;
  onExport?: (format: "json" | "html") => void;
}

// ── Severity Badge ─────────────────────────────────────────────────────────────

const SEV_COLOURS: Record<string, string> = {
  critical: "bg-red-900 text-red-300",
  serious:  "bg-amber-900 text-amber-300",
  moderate: "bg-cyan-900 text-cyan-300",
  minor:    "bg-slate-800 text-slate-400",
};

// ── Component ─────────────────────────────────────────────────────────────────

export const ReportViewer: React.FC<ReportViewerProps> = ({
  scan,
  onViolationClick,
  onExport,
}) => {
  const counts = useMemo(() => {
    const map: Record<string, number> = { critical: 0, serious: 0, moderate: 0, minor: 0 };
    for (const v of scan.violations) map[v.severity] = (map[v.severity] ?? 0) + 1;
    return map;
  }, [scan.violations]);

  const byFile = useMemo(() => {
    const map = new Map<string, Violation[]>();
    for (const v of scan.violations) {
      const key = v.location?.file ?? scan.target;
      const arr = map.get(key) ?? [];
      arr.push(v);
      map.set(key, arr);
    }
    return map;
  }, [scan]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-slate-900 border border-slate-700 rounded-2xl p-6">
        <div className="flex items-start justify-between mb-4">
          <div>
            <h2 className="text-white text-xl font-bold mb-1">
              {scan.violations.length === 0 ? "✅ No violations found" : `${scan.violations.length} Violation(s)`}
            </h2>
            <p className="text-slate-400 text-sm">
              {scan.target} · {scan.total_files_scanned} files · {scan.scan_duration_ms}ms
              {scan.llm_provider && ` · AI: ${scan.llm_provider}`}
            </p>
          </div>

          <div className="flex gap-2">
            <button
              onClick={() => onExport?.("json")}
              className="text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 px-3 py-1.5 rounded-lg"
            >
              Export JSON
            </button>
            <button
              onClick={() => onExport?.("html")}
              className="text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 px-3 py-1.5 rounded-lg"
            >
              Export HTML
            </button>
          </div>
        </div>

        {/* Severity pills */}
        <div className="flex flex-wrap gap-2">
          {Object.entries(counts).map(([sev, count]) =>
            count > 0 ? (
              <span key={sev} className={`text-xs font-semibold px-3 py-1 rounded-full ${SEV_COLOURS[sev]}`}>
                {count} {sev}
              </span>
            ) : null
          )}
        </div>
      </div>

      {/* By-file listing */}
      {[...byFile.entries()].map(([file, violations]) => (
        <div key={file} className="bg-slate-900 border border-slate-700 rounded-2xl overflow-hidden">
          <div className="px-4 py-3 bg-slate-800/60 border-b border-slate-700">
            <p className="text-sm font-mono text-slate-300">{file}</p>
            <p className="text-xs text-slate-500">{violations.length} violation(s)</p>
          </div>

          <div className="divide-y divide-slate-800">
            {violations.map((v) => (
              <div
                key={v.id}
                className="px-4 py-3 hover:bg-slate-800/50 cursor-pointer transition-colors"
                onClick={() => onViolationClick?.(v)}
              >
                <div className="flex items-center gap-2 mb-1">
                  <span className={`text-xs font-bold px-2 py-0.5 rounded ${SEV_COLOURS[v.severity]}`}>
                    {v.severity}
                  </span>
                  <span className="text-xs font-mono text-slate-400">{v.rule}</span>
                  {v.location && (
                    <span className="text-xs text-slate-600">line {v.location.line}</span>
                  )}
                  {v.wcag_criterion && (
                    <span className="text-xs text-slate-600">WCAG {v.wcag_criterion}</span>
                  )}
                </div>
                <p className="text-sm text-slate-200">{v.description}</p>
                <p className="text-xs text-slate-500 mt-1">💡 {v.suggestion}</p>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
};
