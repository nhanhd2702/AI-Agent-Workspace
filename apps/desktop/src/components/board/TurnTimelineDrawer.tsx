"use client";

import React, { useEffect, useState } from "react";
import {
  Activity,
  AlertCircle,
  Bot,
  ChevronDown,
  ChevronUp,
  Clock,
  Cpu,
  GitCommitHorizontal,
  Loader2,
  X,
} from "lucide-react";
import { ReviewGateBanner } from "@/components/reviews/ReviewGateBanner";
import type {
  BoardTask,
  ReviewDecidePayload,
  ReviewDecision,
  ReviewGate,
  TaskLogEntry,
} from "@/lib/types";

export interface TurnTimelineDrawerProps {
  isOpen: boolean;
  task: BoardTask | null;
  logs: TaskLogEntry[];
  isLoading?: boolean;
  error?: string | null;
  activeReview?: ReviewGate | null;
  onDecideReview?: (
    decision: ReviewDecision,
    payload?: ReviewDecidePayload
  ) => void | Promise<void>;
  collapsedStepLimit?: number;
  onClose: () => void;
}

const DEFAULT_COLLAPSED_STEP_LIMIT = 2;

function formatTimestamp(iso?: string | null): string {
  if (!iso) return "";
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return iso;
  return new Date(ms).toLocaleTimeString("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatJsonPreview(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function TurnTimelineDrawer({
  isOpen,
  task,
  logs,
  isLoading = false,
  error = null,
  activeReview = null,
  onDecideReview,
  collapsedStepLimit = DEFAULT_COLLAPSED_STEP_LIMIT,
  onClose,
}: TurnTimelineDrawerProps) {
  const [expandedStepsByLog, setExpandedStepsByLog] = useState<
    Record<string, boolean>
  >({});
  const [expandedPayloadByLog, setExpandedPayloadByLog] = useState<
    Record<string, boolean>
  >({});

  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  useEffect(() => {
    setExpandedStepsByLog({});
    setExpandedPayloadByLog({});
  }, [task?.id]);

  if (!isOpen || !task) {
    return null;
  }

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-black/60 backdrop-blur-xs"
      role="dialog"
      aria-modal="true"
      aria-label="Các Lượt"
      data-testid="turn-timeline-drawer"
    >
      <div className="w-full max-w-xl bg-gray-950 border-l border-gray-800 h-full flex flex-col shadow-2xl">
        {/* Drawer Header */}
        <header className="px-5 py-4 border-b border-gray-800 bg-gray-900/90 flex items-start justify-between gap-4">
          <div className="space-y-1 min-w-0">
            <div className="flex items-center gap-2">
              <Activity className="w-4 h-4 text-sky-400 shrink-0" />
              <h2 className="text-sm font-bold tracking-wide text-white">
                Các Lượt
              </h2>
              <span className="px-2 py-0.5 rounded-full text-[11px] font-mono bg-gray-800 text-sky-300 border border-gray-700">
                {task.status}
              </span>
            </div>
            <p className="text-xs font-medium text-gray-300 truncate">
              {task.title}
            </p>
          </div>

          <button
            type="button"
            onClick={onClose}
            aria-label="Đóng"
            className="p-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-gray-800 transition-colors cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </header>

        {/* Drawer Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {activeReview && onDecideReview && (
            <ReviewGateBanner review={activeReview} onDecide={onDecideReview} />
          )}

          {error && (
            <div
              role="alert"
              className="p-3 rounded-xl bg-rose-950/60 border border-rose-800/70 text-xs text-rose-200 flex items-center gap-2"
            >
              <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {isLoading ? (
            <div className="py-12 flex flex-col items-center justify-center gap-2 text-xs text-gray-400">
              <Loader2 className="w-5 h-5 animate-spin text-sky-400" />
              <span>Đang tải nhật ký lượt chạy...</span>
            </div>
          ) : logs.length === 0 ? (
            <div className="py-12 text-center rounded-2xl border border-dashed border-gray-800 text-xs text-gray-500">
              Chưa có lượt chạy nào được ghi nhận cho công việc này.
            </div>
          ) : (
            <ol className="relative border-l border-gray-800 ml-2.5 space-y-4">
              {logs.map((entry, idx) => {
                const entryKey = entry.id || String(idx);
                const logType = entry.logType ?? entry.log_type ?? "turn";
                const createdAt = entry.createdAt ?? entry.created_at;
                const durationMs = entry.durationMs ?? entry.duration_ms;
                const agentName = entry.agentName ?? entry.agent_name;
                const turnNum = entry.turnNumber ?? entry.turn_number;
                const steps = entry.steps || [];
                const isStepsExpanded = Boolean(expandedStepsByLog[entryKey]);
                const hiddenCount = Math.max(0, steps.length - collapsedStepLimit);
                const visibleSteps = isStepsExpanded
                  ? steps
                  : steps.slice(0, collapsedStepLimit);

                const inputPayload = entry.inputPayload ?? entry.input_payload;
                const outputPayload =
                  entry.outputPayload ?? entry.output_payload;
                const isPayloadExpanded = Boolean(expandedPayloadByLog[entryKey]);
                const hasPayloads =
                  inputPayload !== undefined && inputPayload !== null
                    ? true
                    : outputPayload !== undefined && outputPayload !== null;

                if (logType === "audit") {
                  const fromSt = entry.fromStatus ?? entry.from_status;
                  const toSt = entry.toStatus ?? entry.to_status;
                  return (
                    <li key={entryKey} className="ml-5 relative">
                      <span className="absolute -left-[27px] top-1.5 w-3 h-3 rounded-full bg-gray-800 border-2 border-purple-400" />
                      <div className="rounded-xl bg-gray-900/70 border border-gray-800 p-3 space-y-1">
                        <div className="flex items-center justify-between gap-2 text-xs">
                          <span className="inline-flex items-center gap-1.5 font-medium text-purple-300">
                            <GitCommitHorizontal className="w-3.5 h-3.5" />
                            <span>
                              {fromSt} → {toSt}
                            </span>
                          </span>
                          <span className="text-[11px] font-mono text-gray-500">
                            {formatTimestamp(createdAt)}
                          </span>
                        </div>
                        {(entry.actor || entry.reason) && (
                          <p className="text-[11px] text-gray-400">
                            {entry.actor ? `Bởi: ${entry.actor}` : ""}
                            {entry.actor && entry.reason ? " • " : ""}
                            {entry.reason || ""}
                          </p>
                        )}
                      </div>
                    </li>
                  );
                }

                return (
                  <li key={entryKey} className="ml-5 relative">
                    <span
                      className={`absolute -left-[27px] top-2 w-3 h-3 rounded-full border-2 ${
                        entry.status === "failed" || entry.status === "rejected"
                          ? "bg-rose-950 border-rose-400"
                          : entry.status === "running"
                          ? "bg-sky-950 border-sky-400"
                          : "bg-emerald-950 border-emerald-400"
                      }`}
                    />
                    <div className="rounded-xl bg-gray-900 border border-gray-800 p-3.5 space-y-2.5">
                      {/* Turn Header */}
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="px-2 py-0.5 rounded-md text-[11px] font-mono font-semibold bg-sky-950/70 text-sky-300 border border-sky-800/50">
                            Lượt #{turnNum ?? idx + 1}
                          </span>
                          {agentName && (
                            <span className="inline-flex items-center gap-1 text-xs font-medium text-gray-200">
                              <Bot className="w-3.5 h-3.5 text-sky-400" />
                              {agentName}
                            </span>
                          )}
                          {entry.action && (
                            <span className="text-[11px] font-mono text-gray-400">
                              {entry.action}
                            </span>
                          )}
                        </div>
                        <span className="text-[11px] font-mono text-gray-500">
                          {formatTimestamp(createdAt)}
                        </span>
                      </div>

                      {/* Badges row */}
                      <div className="flex flex-wrap items-center gap-2 text-[11px]">
                        {entry.tool && (
                          <span className="px-2 py-0.5 rounded-full bg-gray-800 text-gray-300 font-mono">
                            {entry.tool}
                          </span>
                        )}
                        {durationMs != null && (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-gray-800/80 text-gray-300">
                            <Clock className="w-3 h-3 text-sky-400" />
                            {durationMs} ms
                          </span>
                        )}
                        {entry.tokens != null && entry.tokens > 0 && (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-gray-800/80 text-gray-300">
                            <Cpu className="w-3 h-3 text-purple-400" />
                            {entry.tokens.toLocaleString("en-US")} tokens
                          </span>
                        )}
                        {entry.status && (
                          <span
                            className={`px-2 py-0.5 rounded-full font-medium ${
                              entry.status === "failed" ||
                              entry.status === "rejected"
                                ? "bg-rose-950/70 text-rose-300 border border-rose-800/60"
                                : "bg-emerald-950/70 text-emerald-300 border border-emerald-800/60"
                            }`}
                          >
                            {entry.status}
                          </span>
                        )}
                      </div>

                      {/* Steps list with "Xem thêm X bước" */}
                      {steps.length > 0 && (
                        <div className="space-y-1.5 pt-1">
                          <ul className="space-y-1">
                            {visibleSteps.map((step, sIdx) => (
                              <li
                                key={step.id || sIdx}
                                className="flex items-center justify-between gap-2 px-2.5 py-1.5 rounded-lg bg-gray-950/80 border border-gray-800/80 text-xs text-gray-300"
                              >
                                <span className="truncate">
                                  {step.name || step.tool || `Bước ${sIdx + 1}`}
                                </span>
                                {step.status && (
                                  <span className="text-[10px] font-mono text-gray-400 shrink-0">
                                    {step.status}
                                  </span>
                                )}
                              </li>
                            ))}
                          </ul>

                          {hiddenCount > 0 && (
                            <button
                              type="button"
                              onClick={() =>
                                setExpandedStepsByLog((prev) => ({
                                  ...prev,
                                  [entryKey]: !isStepsExpanded,
                                }))
                              }
                              className="inline-flex items-center gap-1 text-[11px] font-medium text-sky-400 hover:text-sky-300 cursor-pointer"
                            >
                              {isStepsExpanded ? (
                                <>
                                  <ChevronUp className="w-3.5 h-3.5" />
                                  <span>Thu gọn</span>
                                </>
                              ) : (
                                <>
                                  <ChevronDown className="w-3.5 h-3.5" />
                                  <span>Xem thêm {hiddenCount} bước</span>
                                </>
                              )}
                            </button>
                          )}
                        </div>
                      )}

                      {(entry.errorMessage ?? entry.error_message) && (
                        <div className="p-2 rounded-lg bg-rose-950/50 border border-rose-800/60 text-[11px] text-rose-200">
                          {entry.errorMessage ?? entry.error_message}
                        </div>
                      )}

                      {hasPayloads && (
                        <div>
                          <button
                            type="button"
                            onClick={() =>
                              setExpandedPayloadByLog((prev) => ({
                                ...prev,
                                [entryKey]: !isPayloadExpanded,
                              }))
                            }
                            className="text-[11px] text-gray-400 hover:text-gray-200 underline cursor-pointer"
                          >
                            {isPayloadExpanded
                              ? "Ẩn chi tiết dữ liệu"
                              : "Xem chi tiết dữ liệu"}
                          </button>
                          {isPayloadExpanded && (
                            <pre className="mt-2 p-2.5 rounded-lg bg-gray-950 border border-gray-800 text-[11px] text-gray-300 overflow-x-auto max-h-48">
                              {formatJsonPreview({
                                input: inputPayload,
                                output: outputPayload,
                              })}
                            </pre>
                          )}
                        </div>
                      )}
                    </div>
                  </li>
                );
              })}
            </ol>
          )}
        </div>
      </div>
    </div>
  );
}
