import React from "react";
import type { Violation } from "../store";

// ── Severity Config ───────────────────────────────────────────────────────────

const SEV_STYLES: Record<string, { bg: string; text: string; dot: string }> = {
  critical: { bg: "bg-red-950/40 border-red-800",   text: "text-red-400",    dot: "bg-red-500" },
  serious:  { bg: "bg-amber-950/40 border-amber-800", text: "text-amber-400",  dot: "bg-amber-500" },
  moderate: { bg: "bg-cyan-950/40 border-cyan-800",  text: "text-cyan-400",   dot: "bg-cyan-500" },
  minor:    { bg: "bg-slate-900/60 border-slate-700", text: "text-slate-400",  dot: "bg-slate-500" },
};

// ── Props ─────────────────────────────────────────────────────────────────────

interface IssueCardProps {
  violation: Violation;
  selected?: boolean;
  onClick?: () => void;
  onFix?: () => void;
}

// ── Component ─────────────────────────────────────────────────────────────────

export const IssueCard: React.FC<IssueCardProps> = ({
  violation,
  selected,
  onClick,
  onFix,
}) => {
  const sev = SEV_STYLES[violation.severity] ?? SEV_STYLES.minor;

  return (
    <div
      className={`rounded-xl border p-4 cursor-pointer transition-all duration-150 ${sev.bg} ${
        selected ? "ring-2 ring-violet-500" : "hover:brightness-110"
      }`}
      onClick={onClick}
    >
      {/* Header row */}
      <div className="flex items-center justify-between gap-2 mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className={`w-2 h-2 rounded-full flex-shrink-0 ${sev.dot}`} />
          <span className={`text-xs font-semibold uppercase tracking-wider ${sev.text}`}>
            {violation.severity}
          </span>
          {violation.ai_generated && (
            <span className="text-xs text-violet-400 bg-violet-900/40 px-2 py-0.5 rounded-full">
              AI
            </span>
          )}
        </div>
        <span className="text-xs text-slate-500 font-mono truncate ml-2">
          {violation.rule}
        </span>
      </div>

      {/* Description */}
      <p className="text-sm text-slate-200 font-medium mb-1 line-clamp-2">
        {violation.description}
      </p>

      {/* Location */}
      {violation.location && (
        <p className="text-xs text-slate-500 font-mono truncate mb-2">
          {violation.location.file}:{violation.location.line}
        </p>
      )}

      {/* Suggestion */}
      <p className="text-xs text-slate-400 line-clamp-2 mb-3">
        💡 {violation.suggestion}
      </p>

      {/* Footer */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {violation.wcag_criterion && (
            <span className="text-xs text-slate-500">
              WCAG {violation.wcag_criterion}
            </span>
          )}
          <span className="text-xs text-slate-600">
            {Math.round(violation.confidence * 100)}% confidence
          </span>
        </div>

        {violation.fix_available && onFix && (
          <button
            className="text-xs bg-violet-700 hover:bg-violet-600 text-white px-3 py-1 rounded-lg transition-colors"
            onClick={(e) => {
              e.stopPropagation();
              onFix();
            }}
          >
            🔧 Fix
          </button>
        )}
      </div>
    </div>
  );
};
