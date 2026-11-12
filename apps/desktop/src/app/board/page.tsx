"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  FolderKanban,
  RefreshCw,
  Search,
  Sparkles,
  Wifi,
  WifiOff,
} from "lucide-react";
import { SidebarNav } from "@/components/layout/SidebarNav";
import { KanbanBoard } from "@/components/board/KanbanBoard";
import { TurnTimelineDrawer } from "@/components/board/TurnTimelineDrawer";
import { ApiClient } from "@/lib/apiClient";
import type {
  BoardTask,
  Project,
  ReviewDecidePayload,
  ReviewDecision,
  ReviewGate,
  TaskLogEntry,
} from "@/lib/types";

const DEMO_PROJECTS: Project[] = [
  { id: "proj-default", name: "Văn phòng Mặc định" },
];

const DEMO_TASKS: BoardTask[] = [
  {
    id: "task-demo-1",
    projectId: "proj-default",
    title: "Soạn kịch bản TikTok 60s chủ đề tài chính cá nhân",
    status: "running",
    agentName: "ContentWriter",
    turnCount: 2,
  },
  {
    id: "task-demo-2",
    projectId: "proj-default",
    title: "Thiết kế Landing Page khóa học Solopreneur",
    status: "waiting_review",
    agentName: "UIDesigner",
    turnCount: 3,
  },
  {
    id: "task-demo-3",
    projectId: "proj-default",
    title: "Nghiên cứu thị trường AI Agents 2026",
    status: "completed",
    agentName: "DeepResearcher",
    turnCount: 4,
  },
];

export default function BoardPage() {
  const [apiClient] = useState(() => new ApiClient());
  const [projects, setProjects] = useState<Project[]>(DEMO_PROJECTS);
  const [selectedProjectId, setSelectedProjectId] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [tasks, setTasks] = useState<BoardTask[]>(DEMO_TASKS);
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Selected task + TurnTimelineDrawer state
  const [selectedTask, setSelectedTask] = useState<BoardTask | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [taskLogs, setTaskLogs] = useState<TaskLogEntry[]>([]);
  const [logsLoading, setLogsLoading] = useState(false);
  const [logsError, setLogsError] = useState<string | null>(null);
  const [activeReview, setActiveReview] = useState<ReviewGate | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadBoardData = useCallback(async () => {
    setIsLoading(true);
    try {
      const [loadedProjects, loadedTasks] = await Promise.all([
        apiClient.listProjects(),
        apiClient.listTasks(
          selectedProjectId !== "all"
            ? { projectId: selectedProjectId }
            : undefined
        ),
      ]);
      setBackendOnline(true);
      if (loadedProjects && loadedProjects.length > 0) {
        setProjects(loadedProjects);
      }
      setTasks(loadedTasks || []);
    } catch {
      setBackendOnline(false);
    } finally {
      setIsLoading(false);
    }
  }, [apiClient, selectedProjectId]);

  useEffect(() => {
    loadBoardData();
  }, [loadBoardData]);

  const loadTaskDetails = useCallback(
    async (task: BoardTask) => {
      setLogsLoading(true);
      setLogsError(null);
      try {
        const [logs, reviews] = await Promise.all([
          apiClient.getTaskLogs(task.id),
          apiClient.listReviews(task.id, "pending").catch(() => []),
        ]);
        setTaskLogs(logs);
        setActiveReview(reviews && reviews.length > 0 ? reviews[0] : null);
      } catch (err) {
        setLogsError(
          err instanceof Error
            ? err.message
            : "Không thể tải nhật ký các lượt của task."
        );
      } finally {
        setLogsLoading(false);
      }
    },
    [apiClient]
  );

  // Determine which task ID to subscribe over WebSocket for live updates
  const streamTaskId = useMemo(() => {
    if (selectedTask) return selectedTask.id;
    const runningTask = tasks.find(
      (t) =>
        t.status === "running" ||
        t.status === "waiting_review" ||
        t.status === "pending"
    );
    return runningTask?.id || null;
  }, [selectedTask, tasks]);

  useEffect(() => {
    if (!backendOnline || !streamTaskId || typeof WebSocket === "undefined") {
      return;
    }

    let cancelled = false;

    const connectWs = () => {
      if (cancelled) return;
      try {
        const ws = new WebSocket(apiClient.getTaskWebSocketUrl(streamTaskId));
        wsRef.current = ws;

        ws.onmessage = (event) => {
          try {
            const msg = JSON.parse(event.data);
            const evType = msg?.event || msg?.type;

            if (evType === "task_status" && msg.task_id) {
              setTasks((prev) =>
                prev.map((item) =>
                  item.id === msg.task_id
                    ? { ...item, status: msg.status || item.status }
                    : item
                )
              );
              setSelectedTask((prev) =>
                prev && prev.id === msg.task_id
                  ? { ...prev, status: msg.status || prev.status }
                  : prev
              );
            } else if (
              evType === "turn_completed" ||
              evType === "turn_started" ||
              evType === "handoff" ||
              evType === "review_requested" ||
              evType === "review_decided"
            ) {
              if (evType === "review_decided" && msg.task_id && msg.task_status) {
                setTasks((prev) =>
                  prev.map((item) =>
                    item.id === msg.task_id
                      ? { ...item, status: msg.task_status }
                      : item
                  )
                );
              }
              if (selectedTask && selectedTask.id === msg.task_id && drawerOpen) {
                void loadTaskDetails(selectedTask);
              }
            }
          } catch {
            // Ignore malformed frame
          }
        };

        ws.onclose = () => {
          if (!cancelled) {
            reconnectTimerRef.current = setTimeout(connectWs, 3000);
          }
        };
      } catch {
        // Ignore WS connection errors in offline/test environments
      }
    };

    connectWs();

    return () => {
      cancelled = true;
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [apiClient, backendOnline, drawerOpen, loadTaskDetails, selectedTask, streamTaskId]);

  const handleMoveTask = async (taskId: string, targetStatus: string) => {
    const updated = await apiClient.transitionTaskState(taskId, targetStatus, {
      actor: "user",
      reason: `Kanban board move to ${targetStatus}`,
    });
    setTasks((prev) =>
      prev.map((t) => (t.id === taskId ? { ...t, ...updated } : t))
    );
    if (selectedTask?.id === taskId) {
      setSelectedTask((prev) => (prev ? { ...prev, ...updated } : prev));
      if (drawerOpen) {
        await loadTaskDetails(updated);
      }
    }
  };

  const handleSelectTask = async (task: BoardTask) => {
    setSelectedTask(task);
    setDrawerOpen(true);
    if (backendOnline) {
      await loadTaskDetails(task);
    } else {
      setTaskLogs([]);
      setActiveReview(null);
    }
  };

  const handleDecideReview = async (
    decision: ReviewDecision,
    payload?: ReviewDecidePayload
  ) => {
    if (!activeReview || !selectedTask) return;
    await apiClient.decideReview(activeReview.id, decision, payload);
    await loadBoardData();
    await loadTaskDetails(selectedTask);
  };

  const filteredTasks = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    return tasks.filter((t) => {
      if (
        selectedProjectId !== "all" &&
        (t.projectId || t.project_id || "proj-default") !== selectedProjectId
      ) {
        return false;
      }
      if (!q) return true;
      const agent = (t.agentName || t.agent_name || "").toLowerCase();
      return t.title.toLowerCase().includes(q) || agent.includes(q);
    });
  }, [tasks, selectedProjectId, searchQuery]);

  return (
    <div className="flex h-screen bg-gray-950 text-gray-100 overflow-hidden font-sans">
      <SidebarNav
        tasks={tasks.slice(0, 12).map((t) => ({
          id: t.id,
          title: t.title,
          status: t.status,
          group: "today",
        }))}
        selectedTaskId={selectedTask?.id}
        activeNav="workspace"
        onNewTask={() => {
          if (typeof window !== "undefined") window.location.assign("/");
        }}
        onSelectTask={(id) => {
          const found = tasks.find((t) => t.id === id);
          if (found) void handleSelectTask(found);
        }}
        onNavigate={(navId) => {
          if (navId === "workspace" && typeof window !== "undefined") {
            window.location.assign("/office");
          }
        }}
      />

      <main className="flex-1 flex flex-col h-full overflow-hidden bg-gray-950">
        {/* Header */}
        <header className="h-14 border-b border-gray-800 px-6 flex items-center justify-between shrink-0 bg-gray-900/60 backdrop-blur-sm">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <FolderKanban className="w-4 h-4 text-sky-400" />
              <h1 className="text-sm font-semibold text-white">
                Bảng Công Việc & Tiến Độ
              </h1>
            </div>

            <nav className="flex items-center gap-1 text-xs">
              <Link
                href="/"
                className="px-2.5 py-1 rounded-lg text-gray-400 hover:text-gray-100 hover:bg-gray-800/70 transition-colors"
              >
                Tổng Chỉ Huy
              </Link>
              <Link
                href="/office"
                className="px-2.5 py-1 rounded-lg text-gray-400 hover:text-gray-100 hover:bg-gray-800/70 transition-colors"
              >
                Văn Phòng
              </Link>
              <Link
                href="/board"
                className="px-2.5 py-1 rounded-lg bg-gray-800 text-sky-300 font-medium"
              >
                Bảng Công Việc
              </Link>
            </nav>
          </div>

          <div className="flex items-center gap-3 text-xs">
            {backendOnline === true ? (
              <span className="flex items-center gap-1.5 text-emerald-400 font-medium">
                <Wifi className="w-3.5 h-3.5" />
                <span>Live Sync</span>
              </span>
            ) : backendOnline === false ? (
              <span className="flex items-center gap-1.5 text-amber-400 font-medium">
                <WifiOff className="w-3.5 h-3.5" />
                <span>Ngoại tuyến</span>
              </span>
            ) : null}

            <button
              type="button"
              onClick={loadBoardData}
              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-gray-900 hover:bg-gray-800 border border-gray-800 text-gray-300 cursor-pointer"
            >
              <RefreshCw
                className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`}
              />
              <span>Làm mới</span>
            </button>
          </div>
        </header>

        {/* Filter Bar */}
        <div className="px-6 py-3 border-b border-gray-800/80 bg-gray-900/30 flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-2 text-xs">
              <Sparkles className="w-3.5 h-3.5 text-sky-400" />
              <label htmlFor="project-filter" className="text-gray-400">
                Dự án:
              </label>
              <select
                id="project-filter"
                value={selectedProjectId}
                onChange={(e) => setSelectedProjectId(e.target.value)}
                className="rounded-lg bg-gray-900 border border-gray-800 px-2.5 py-1.5 text-xs text-gray-200 focus:outline-none focus:border-sky-500 cursor-pointer"
              >
                <option value="all">Tất cả dự án</option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>

            <div className="relative">
              <Search className="w-3.5 h-3.5 text-gray-500 absolute left-2.5 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Tìm kiếm task hoặc @Agent..."
                className="pl-8 pr-3 py-1.5 rounded-lg bg-gray-900 border border-gray-800 text-xs text-gray-200 placeholder-gray-500 focus:outline-none focus:border-sky-500 w-60"
              />
            </div>
          </div>
        </div>

        {/* Board Canvas */}
        <div className="flex-1 overflow-y-auto p-6">
          <KanbanBoard
            tasks={filteredTasks}
            onMoveTask={handleMoveTask}
            onSelectTask={handleSelectTask}
            selectedTaskId={selectedTask?.id}
          />
        </div>
      </main>

      {/* Turn Timeline Drawer */}
      <TurnTimelineDrawer
        isOpen={drawerOpen}
        task={selectedTask}
        logs={taskLogs}
        isLoading={logsLoading}
        error={logsError}
        activeReview={activeReview}
        onDecideReview={handleDecideReview}
        onClose={() => setDrawerOpen(false)}
      />
    </div>
  );
}
