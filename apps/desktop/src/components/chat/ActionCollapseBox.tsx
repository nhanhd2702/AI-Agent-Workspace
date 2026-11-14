"use client";

import React, { useState } from "react";
import {
  ChevronDown,
  ChevronUp,
  CheckCircle2,
  Loader2,
  AlertCircle,
  Clock,
  Terminal,
  Activity,
} from "lucide-react";

export interface ActionItem {
  id: string;
  title: string;
  durationMs: number;
  status: "pending" | "running" | "completed" | "failed";
  detail?: string;
}

export interface ActionCollapseBoxProps {
  actions: ActionItem[];
  isRunning?: boolean;
  className?: string;
}

export function formatDuration(ms: number): string {
  if (ms >= 1000) {
    return `${(ms / 1000).toFixed(1)}s`;
  }
  return `${ms}ms`;
}

export function ActionCollapseBox({
  actions,
  isRunning = false,
  className = "",
}: ActionCollapseBoxProps) {
  const [isOpen, setIsOpen] = useState(false);

  const totalMs = actions.reduce((sum, item) => sum + (item.durationMs || 0), 0);
  const totalDurationStr = formatDuration(totalMs);
  const completedCount = actions.filter((a) => a.status === "completed").length;

  return (
    <div
      className={`rounded-xl border border-slate-700/80 bg-slate-900/90 shadow-lg overflow-hidden transition-all text-xs ${className}`}
    >
      {/* Header bar */}
      <div className="flex items-center justify-between px-3.5 py-2.5 bg-slate-800/60 hover:bg-slate-800/90 transition-colors">
        <div className="flex items-center gap-2.5 min-w-0">
          {isRunning ? (
            <div data-testid="action-spinner" className="flex items-center justify-center text-indigo-400">
              <Loader2 className="w-4 h-4 animate-spin" />
            </div>
          ) : (
            <div className="w-4 h-4 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center shrink-0">
              <CheckCircle2 className="w-3.5 h-3.5" />
            </div>
          )}

          <div className="flex items-center gap-2 min-w-0">
            <span className="font-semibold text-slate-200">
              {actions.length} thao tác
            </span>
            <span className="text-slate-500">•</span>
            <div className="flex items-center gap-1 text-[11px] font-mono text-slate-400 bg-slate-950/60 px-2 py-0.5 rounded border border-slate-700/50">
              <Clock className="w-3 h-3 text-slate-500" />
              <span>{totalDurationStr}</span>
            </div>
            {isRunning && (
              <span className="text-[10px] text-indigo-400 animate-pulse font-medium">
                Đang xử lý...
              </span>
            )}
          </div>
        </div>

        {/* Toggle button */}
        <button
          type="button"
          onClick={() => setIsOpen(!isOpen)}
          aria-expanded={isOpen}
          aria-label={isOpen ? "Ẩn chi tiết" : "Xem chi tiết"}
          className="flex items-center gap-1 px-2 py-1 rounded text-slate-400 hover:text-slate-200 hover:bg-slate-700/50 transition-colors font-medium text-[11px]"
        >
          <span>{isOpen ? "Ẩn chi tiết" : "Xem chi tiết"}</span>
          {isOpen ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
        </button>
      </div>

      {/* Collapsible Action Details */}
      {isOpen && (
        <div className="divide-y divide-slate-800/80 border-t border-slate-800/80 bg-slate-950/40 p-1">
          {actions.map((act) => {
            const isCompleted = act.status === "completed";
            const isActRunning = act.status === "running";
            const isFailed = act.status === "failed";

            return (
              <div
                key={act.id}
                className="p-2.5 rounded-lg hover:bg-slate-800/30 transition-colors space-y-1.5"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    {isActRunning ? (
                      <Loader2 className="w-3.5 h-3.5 text-indigo-400 animate-spin shrink-0" />
                    ) : isFailed ? (
                      <AlertCircle className="w-3.5 h-3.5 text-red-400 shrink-0" />
                    ) : (
                      <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                    )}
                    <span className="font-medium text-slate-200 truncate">{act.title}</span>
                  </div>

                  <span className="px-1.5 py-0.5 rounded font-mono text-[10px] bg-slate-800 border border-slate-700/60 text-slate-400 shrink-0">
                    {formatDuration(act.durationMs)}
                  </span>
                </div>

                {act.detail && (
                  <div className="pl-5 text-[11px] font-mono text-slate-400 bg-slate-950/70 p-2 rounded border border-slate-800/90 overflow-x-auto whitespace-pre-wrap break-all">
                    {act.detail}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
