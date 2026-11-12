"use client";

import React, { useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  Bot,
  CheckCircle2,
  Clock,
  Eye,
  LayoutGrid,
  List as ListIcon,
  Loader2,
  PauseCircle,
  Send,
  ShieldAlert,
  XCircle,
} from "lucide-react";
import type { BoardTask } from "@/lib/types";

export interface KanbanBoardProps {
  tasks: BoardTask[];
  onMoveTask: (taskId: string, targetStatus: string) => void | Promise<unknown>;
  onSelectTask?: (task: BoardTask) => void;
  selectedTaskId?: string | null;
  defaultViewMode?: "kanban" | "list";
  className?: string;
}

interface ColumnConfig {
  id: string;
  label: string;
  targetStatus: string;
  statuses: string[];
  accentClass: string;
  dotClass: string;
}

const KANBAN_COLUMNS: ColumnConfig[] = [
  {
    id: "pending",
    label: "Chờ",
    targetStatus: "pending",
    statuses: ["pending"],
    accentClass: "border-gray-700/80",
    dotClass: "bg-gray-400",
  },
  {
    id: "running",
    label: "Đang làm",
    targetStatus: "running",
    statuses: ["running", "paused", "rejected", "failed"],
    accentClass: "border-sky-800/60",
    dotClass: "bg-sky-400",
  },
  {
    id: "waiting_review",
    label: "Chờ duyệt",
    targetStatus: "waiting_review",
    statuses: ["waiting_review"],
    accentClass: "border-amber-700/60",
    dotClass: "bg-amber-400",
  },
  {
    id: "delivered",
    label: "Đã bàn giao",
    targetStatus: "delivered",
    statuses: ["delivered", "approved"],
    accentClass: "border-purple-700/60",
    dotClass: "bg-purple-400",
  },
  {
    id: "completed",
    label: "Hoàn tất",
    targetStatus: "completed",
    statuses: ["completed", "cancelled"],
    accentClass: "border-emerald-800/60",
    dotClass: "bg-emerald-400",
  },
];

const ALLOWED_TRANSITIONS: Record<string, Set<string>> = {
  pending: new Set(["running", "cancelled", "paused"]),
  running: new Set([
    "waiting_review",
    "delivered",
    "completed",
    "paused",
    "failed",
    "cancelled",
  ]),
  waiting_review: new Set([
    "approved",
    "rejected",
    "running",
    "paused",
    "failed",
    "cancelled",
  ]),
  approved: new Set([
    "delivered",
    "running",
    "completed",
    "paused",
    "failed",
    "cancelled",
  ]),
  rejected: new Set(["running", "paused", "failed", "cancelled"]),
  delivered: new Set(["completed", "running", "paused", "failed", "cancelled"]),
  paused: new Set(["running", "failed", "cancelled"]),
  failed: new Set(["running", "cancelled"]),
  completed: new Set(),
  cancelled: new Set(),
};

const STATUS_LABELS: Record<string, string> = {
  pending: "Mới",
  running: "Đang chạy",
  paused: "Tạm dừng",
  waiting_review: "Cần duyệt",
  approved: "Đã duyệt",
  rejected: "Bị từ chối",
  delivered: "Bàn giao",
  completed: "Xong",
  failed: "Thất bại",
  cancelled: "Đã hủy",
};

export function isValidTaskTransition(fromStatus: string, targetStatus: string): boolean {
  const from = (fromStatus || "pending").toLowerCase();
  const target = (targetStatus || "").toLowerCase();
  if (from === target) return false;
  const allowed = ALLOWED_TRANSITIONS[from];
  if (!allowed) return false;
  return allowed.has(target);
}

function getColumnForStatus(status: string): ColumnConfig {
  const normalized = (status || "pending").toLowerCase();
  return (
    KANBAN_COLUMNS.find((col) => col.statuses.includes(normalized)) ||
    KANBAN_COLUMNS[0]
  );
}

function renderStatusBadge(status: string) {
  const normalized = (status || "pending").toLowerCase();
  const label = STATUS_LABELS[normalized] || status;

  switch (normalized) {
    case "running":
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-sky-950/80 text-sky-300 border border-sky-800/60">
          <Loader2 className="w-3 h-3 animate-spin" />
          {label}
        </span>
      );
    case "waiting_review":
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-amber-950/80 text-amber-300 border border-amber-700/60">
          <ShieldAlert className="w-3 h-3" />
          {label}
        </span>
      );
    case "approved":
    case "delivered":
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-purple-950/80 text-purple-300 border border-purple-700/60">
          <Send className="w-3 h-3" />
          {label}
        </span>
      );
    case "completed":
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-emerald-950/80 text-emerald-300 border border-emerald-800/60">
          <CheckCircle2 className="w-3 h-3" />
          {label}
        </span>
      );
    case "failed":
    case "rejected":
    case "cancelled":
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-rose-950/80 text-rose-300 border border-rose-800/60">
          <XCircle className="w-3 h-3" />
          {label}
        </span>
      );
    case "paused":
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-amber-950/50 text-amber-200 border border-amber-800/50">
          <PauseCircle className="w-3 h-3" />
          {label}
        </span>
      );
    default:
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-gray-800 text-gray-300 border border-gray-700">
          <Clock className="w-3 h-3" />
          {label}
        </span>
      );
  }
}

export function KanbanBoard({
  tasks,
  onMoveTask,
  onSelectTask,
  selectedTaskId,
  defaultViewMode = "kanban",
  className = "",
}: KanbanBoardProps) {
  const [viewMode, setViewMode] = useState<"kanban" | "list">(defaultViewMode);
  const [localTasks, setLocalTasks] = useState<BoardTask[]>(tasks);
  const [dragOverColumn, setDragOverColumn] = useState<string | null>(null);
  const [movingTaskIds, setMovingTaskIds] = useState<Record<string, boolean>>({});
  const [errorBanner, setErrorBanner] = useState<string | null>(null);
  const draggingTaskIdRef = useRef<string | null>(null);
  const movingTaskIdsRef = useRef<Record<string, boolean>>({});

  useEffect(() => {
    setLocalTasks(tasks);
  }, [tasks]);

  const attemptMoveTask = async (taskId: string, targetStatus: string) => {
    const resolvedTarget = targetStatus.toLowerCase();
    if (!resolvedTarget || movingTaskIdsRef.current[taskId]) return;

    const task = localTasks.find((t) => t.id === taskId);
    if (!task) return;

    const previousStatus = task.status;
    const currentStatus = (task.status || "pending").toLowerCase();

    if (currentStatus === resolvedTarget) {
      return;
    }

    if (!isValidTaskTransition(currentStatus, resolvedTarget)) {
      const fromLabel = STATUS_LABELS[currentStatus] || currentStatus;
      const toLabel = STATUS_LABELS[resolvedTarget] || resolvedTarget;
      setErrorBanner(
        `Không thể chuyển task "${task.title}" từ "${fromLabel}" sang "${toLabel}" theo quy trình FSM.`
      );
      return;
    }

    setErrorBanner(null);
    movingTaskIdsRef.current[taskId] = true;
    setMovingTaskIds((prev) => ({ ...prev, [taskId]: true }));
    setLocalTasks((prev) =>
      prev.map((item) =>
        item.id === taskId ? { ...item, status: resolvedTarget } : item
      )
    );

    try {
      await onMoveTask(taskId, resolvedTarget);
    } catch (err) {
      setLocalTasks((prev) =>
        prev.map((item) =>
          item.id === taskId ? { ...item, status: previousStatus } : item
        )
      );
      const message =
        err instanceof Error
          ? err.message
          : "Không thể cập nhật trạng thái task. Đã hoàn tác vị trí cũ.";
      setErrorBanner(message);
    } finally {
      delete movingTaskIdsRef.current[taskId];
      setMovingTaskIds((prev) => {
        const next = { ...prev };
        delete next[taskId];
        return next;
      });
    }
  };

  const renderMoveSelect = (
    task: BoardTask,
    isMoving: boolean,
    selectClassName: string
  ) => {
    const normalizedStatus = (task.status || "pending").toLowerCase();
    const currentCol = getColumnForStatus(normalizedStatus);
    const selectValue =
      normalizedStatus === currentCol.targetStatus
        ? currentCol.targetStatus
        : "";

    return (
      <select
        aria-label={`Chuyển trạng thái cho ${task.title}`}
        value={selectValue}
        disabled={isMoving}
        onChange={(e) => attemptMoveTask(task.id, e.target.value)}
        className={selectClassName}
      >
        {selectValue === "" && (
          <option value="" disabled>
            {`• ${STATUS_LABELS[normalizedStatus] || normalizedStatus}`}
          </option>
        )}
        {KANBAN_COLUMNS.map((opt) => (
          <option key={opt.id} value={opt.targetStatus}>
            {`→ ${opt.label}`}
          </option>
        ))}
      </select>
    );
  };

  const handleDropOnColumn = async (
    e: React.DragEvent<HTMLDivElement>,
    targetStatus: string
  ) => {
    e.preventDefault();
    setDragOverColumn(null);
    const transferredId = e.dataTransfer?.getData("text/plain");
    const taskId = transferredId || draggingTaskIdRef.current;
    draggingTaskIdRef.current = null;
    if (!taskId) return;
    await attemptMoveTask(taskId, targetStatus);
  };

  return (
    <section className={`flex flex-col gap-4 ${className}`} data-testid="kanban-board">
      {/* Board Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-xs text-gray-400">
          <span className="font-medium text-gray-200">{localTasks.length} công việc</span>
          <span>•</span>
          <span>Kéo thả thẻ hoặc chọn trạng thái để chuyển bước FSM</span>
        </div>

        <div
          className="inline-flex items-center rounded-xl bg-gray-900 border border-gray-800 p-1"
          role="group"
          aria-label="Chế độ hiển thị bảng công việc"
        >
          <button
            type="button"
            onClick={() => setViewMode("kanban")}
            aria-pressed={viewMode === "kanban"}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer ${
              viewMode === "kanban"
                ? "bg-sky-600 text-white shadow-sm"
                : "text-gray-400 hover:text-gray-200"
            }`}
          >
            <LayoutGrid className="w-3.5 h-3.5" />
            <span>Kanban</span>
          </button>
          <button
            type="button"
            onClick={() => setViewMode("list")}
            aria-pressed={viewMode === "list"}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer ${
              viewMode === "list"
                ? "bg-sky-600 text-white shadow-sm"
                : "text-gray-400 hover:text-gray-200"
            }`}
          >
            <ListIcon className="w-3.5 h-3.5" />
            <span>Danh sách</span>
          </button>
        </div>
      </div>

      {/* Transition Error Banner */}
      {errorBanner && (
        <div
          role="alert"
          className="px-4 py-2.5 rounded-xl bg-rose-950/70 border border-rose-800/70 text-xs text-rose-200 flex items-center justify-between gap-3"
        >
          <span className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
            <span>{errorBanner}</span>
          </span>
          <button
            type="button"
            onClick={() => setErrorBanner(null)}
            className="text-rose-300 hover:text-white text-[11px] font-medium cursor-pointer"
          >
            Đóng
          </button>
        </div>
      )}

      {/* Kanban Columns View */}
      {viewMode === "kanban" ? (
        <div className="grid grid-cols-1 md:grid-cols-3 xl:grid-cols-5 gap-4 items-start">
          {KANBAN_COLUMNS.map((col) => {
            const colTasks = localTasks.filter(
              (t) => getColumnForStatus(t.status).id === col.id
            );
            const isDragTarget = dragOverColumn === col.id;

            return (
              <div
                key={col.id}
                data-testid={`kanban-column-${col.id}`}
                data-status={col.targetStatus}
                onDragOver={(e) => {
                  e.preventDefault();
                  if (dragOverColumn !== col.id) setDragOverColumn(col.id);
                }}
                onDragLeave={() => {
                  if (dragOverColumn === col.id) setDragOverColumn(null);
                }}
                onDrop={(e) => handleDropOnColumn(e, col.targetStatus)}
                className={`rounded-2xl bg-gray-900/80 border p-3 min-h-[280px] flex flex-col gap-3 transition-colors ${
                  isDragTarget
                    ? "border-sky-500 bg-sky-950/20"
                    : col.accentClass
                }`}
              >
                {/* Column Header */}
                <div className="flex items-center justify-between px-1 pb-2 border-b border-gray-800/80">
                  <div className="flex items-center gap-2">
                    <span className={`w-2 h-2 rounded-full ${col.dotClass}`} />
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-200">
                      {col.label}
                    </h3>
                  </div>
                  <span className="px-2 py-0.5 rounded-full text-[11px] font-mono bg-gray-800 text-gray-300">
                    {colTasks.length}
                  </span>
                </div>

                {/* Column Cards */}
                <div className="flex flex-col gap-2.5 flex-1">
                  {colTasks.length === 0 ? (
                    <div className="flex-1 flex items-center justify-center rounded-xl border border-dashed border-gray-800 p-4 text-center text-[11px] text-gray-600">
                      Chưa có task
                    </div>
                  ) : (
                    colTasks.map((task) => {
                      const agentLabel =
                        task.agentName || task.agent_name || null;
                      const turnCount =
                        task.turnCount ?? task.turn_count ?? 0;
                      const isSelected = selectedTaskId === task.id;
                      const isMoving = Boolean(movingTaskIds[task.id]);

                      return (
                        <article
                          key={task.id}
                          data-testid={`kanban-card-${task.id}`}
                          draggable={true}
                          onDragStart={(e) => {
                            draggingTaskIdRef.current = task.id;
                            e.dataTransfer?.setData("text/plain", task.id);
                          }}
                          onDragEnd={() => {
                            draggingTaskIdRef.current = null;
                            setDragOverColumn(null);
                          }}
                          className={`rounded-xl bg-gray-950/90 border p-3 space-y-2.5 transition-all cursor-grab active:cursor-grabbing ${
                            isSelected
                              ? "border-sky-500 ring-1 ring-sky-500/40"
                              : "border-gray-800 hover:border-gray-700"
                          } ${isMoving ? "opacity-70" : ""}`}
                        >
                          <div className="flex items-start justify-between gap-2">
                            <button
                              type="button"
                              onClick={() => onSelectTask?.(task)}
                              className="text-left text-xs font-semibold text-gray-100 hover:text-sky-300 transition-colors leading-snug cursor-pointer"
                            >
                              {task.title}
                            </button>
                            {task.priority === "high" && (
                              <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-rose-950/80 text-rose-300 border border-rose-800/60 shrink-0">
                                Gấp
                              </span>
                            )}
                          </div>

                          <div className="flex flex-wrap items-center justify-between gap-1.5">
                            {renderStatusBadge(task.status)}
                            {agentLabel && (
                              <span className="inline-flex items-center gap-1 text-[11px] font-mono text-sky-400">
                                <Bot className="w-3 h-3" />@{agentLabel}
                              </span>
                            )}
                          </div>

                          <div className="pt-2 border-t border-gray-800/80 flex items-center justify-between gap-2">
                            {renderMoveSelect(
                              task,
                              isMoving,
                              "bg-gray-900 border border-gray-800 rounded-lg px-2 py-1 text-[11px] text-gray-300 focus:outline-none focus:border-sky-500 cursor-pointer"
                            )}

                            <button
                              type="button"
                              onClick={() => onSelectTask?.(task)}
                              className="inline-flex items-center gap-1 px-2 py-1 rounded-lg bg-gray-900 hover:bg-gray-800 border border-gray-800 text-[11px] text-gray-300 hover:text-sky-300 transition-colors cursor-pointer"
                            >
                              <Eye className="w-3 h-3" />
                              <span>{turnCount > 0 ? `${turnCount} lượt` : "Các lượt"}</span>
                            </button>
                          </div>
                        </article>
                      );
                    })
                  )}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        /* List View */
        <div
          data-testid="task-list-view"
          className="rounded-2xl bg-gray-900/80 border border-gray-800 overflow-hidden"
        >
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-gray-800 text-[11px] uppercase tracking-wider text-gray-400 bg-gray-950/60">
                <th className="py-3 px-4 font-semibold">Công việc</th>
                <th className="py-3 px-4 font-semibold">Agent</th>
                <th className="py-3 px-4 font-semibold">Trạng thái</th>
                <th className="py-3 px-4 font-semibold">Chuyển cột</th>
                <th className="py-3 px-4 font-semibold text-right">Lượt chạy</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800/70 text-xs">
              {localTasks.length === 0 ? (
                <tr>
                  <td colSpan={5} className="py-8 text-center text-gray-500">
                    Chưa có công việc nào trong dự án.
                  </td>
                </tr>
              ) : (
                localTasks.map((task) => {
                  const agentLabel = task.agentName || task.agent_name || "Chưa gán";
                  const turnCount = task.turnCount ?? task.turn_count ?? 0;
                  const isMoving = Boolean(movingTaskIds[task.id]);
                  return (
                    <tr
                      key={task.id}
                      className={`hover:bg-gray-800/40 transition-colors ${
                        selectedTaskId === task.id ? "bg-sky-950/20" : ""
                      }`}
                    >
                      <td className="py-3 px-4">
                        <button
                          type="button"
                          onClick={() => onSelectTask?.(task)}
                          className="font-medium text-gray-100 hover:text-sky-300 text-left cursor-pointer"
                        >
                          {task.title}
                        </button>
                      </td>
                      <td className="py-3 px-4 font-mono text-sky-400">
                        {agentLabel !== "Chưa gán" ? `@${agentLabel}` : agentLabel}
                      </td>
                      <td className="py-3 px-4">{renderStatusBadge(task.status)}</td>
                      <td className="py-3 px-4">
                        {renderMoveSelect(
                          task,
                          isMoving,
                          "bg-gray-950 border border-gray-800 rounded-lg px-2 py-1 text-[11px] text-gray-300 focus:outline-none focus:border-sky-500 cursor-pointer"
                        )}
                      </td>
                      <td className="py-3 px-4 text-right">
                        <button
                          type="button"
                          onClick={() => onSelectTask?.(task)}
                          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-gray-950 hover:bg-gray-800 border border-gray-800 text-[11px] text-gray-300 cursor-pointer"
                        >
                          <Eye className="w-3 h-3" />
                          <span>{turnCount} lượt</span>
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
