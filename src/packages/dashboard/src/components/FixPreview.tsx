import React from "react";
import type { Fix } from "../store";

// ── FixPreview Component ──────────────────────────────────────────────────────

interface FixPreviewProps {
  fix: Fix;
  onApply?: () => void;
  onDismiss?: () => void;
}

export const FixPreview: React.FC<FixPreviewProps> = ({ fix, onApply, onDismiss }) => {
  return (
    <div className="bg-slate-900 border border-slate-700 rounded-2xl p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-white font-semibold">Fix Preview</h3>
        {onDismiss && (
          <button
            onClick={onDismiss}
            className="text-slate-500 hover:text-slate-300 text-lg leading-none"
          >
            ✕
          </button>
        )}
      </div>

      <p className="text-slate-400 text-sm mb-4">{fix.description}</p>

      <div className="grid grid-cols-2 gap-4 mb-4">
        {/* Before */}
        <div>
          <p className="text-xs text-red-400 font-semibold mb-2">BEFORE</p>
          <pre className="text-xs bg-red-950/30 border border-red-900 rounded-lg p-3 overflow-auto max-h-40 text-red-200 whitespace-pre-wrap">
            {fix.original_code}
          </pre>
        </div>

        {/* After */}
        <div>
          <p className="text-xs text-green-400 font-semibold mb-2">AFTER</p>
          <pre className="text-xs bg-green-950/30 border border-green-900 rounded-lg p-3 overflow-auto max-h-40 text-green-200 whitespace-pre-wrap">
            {fix.fixed_code}
          </pre>
        </div>
      </div>

      {/* Diff */}
      {fix.diff && (
        <div className="mb-4">
          <p className="text-xs text-slate-500 font-semibold mb-2">DIFF</p>
          <pre className="text-xs font-mono bg-slate-950 border border-slate-800 rounded-lg p-3 overflow-auto max-h-48">
            {fix.diff.split("\n").map((line, i) => (
              <span
                key={i}
                className={
                  line.startsWith("+") && !line.startsWith("+++")
                    ? "text-green-400"
                    : line.startsWith("-") && !line.startsWith("---")
                    ? "text-red-400"
                    : line.startsWith("@@")
                    ? "text-cyan-400"
                    : "text-slate-400"
                }
              >
                {line + "\n"}
              </span>
            ))}
          </pre>
        </div>
      )}

      <div className="flex gap-3">
        {onApply && (
          <button
            onClick={onApply}
            className="flex-1 bg-violet-700 hover:bg-violet-600 text-white text-sm font-semibold py-2 px-4 rounded-lg transition-colors"
          >
            ✅ Apply Fix
          </button>
        )}
        {onDismiss && (
          <button
            onClick={onDismiss}
            className="flex-1 bg-slate-800 hover:bg-slate-700 text-slate-300 text-sm font-semibold py-2 px-4 rounded-lg transition-colors"
          >
            Dismiss
          </button>
        )}
      </div>
    </div>
  );
};
