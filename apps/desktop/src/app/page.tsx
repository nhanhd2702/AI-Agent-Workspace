"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
import { SidebarNav } from "@/components/layout/SidebarNav";
import { CommanderPromptBox } from "@/components/chat/CommanderPromptBox";
import { HtmlSandboxViewer } from "@/components/artifacts/HtmlSandboxViewer";
import { MarkdownViewer } from "@/components/artifacts/MarkdownViewer";
import { ReviewGateBanner } from "@/components/reviews/ReviewGateBanner";
import { ApiClient } from "@/lib/apiClient";
import {
  Agent,
  AttachmentItem,
  BoardTask,
  ExecutionMode,
  ParsedTask,
  ReviewDecidePayload,
  ReviewDecision,
  ReviewGate,
  SidebarTaskItem,
  TaskLogEntry,
} from "@/lib/types";
import {
  Activity,
  CheckCircle2,
  Clock,
  Layers,
  Sparkles,
  Wifi,
  WifiOff,
  UserCheck,
  AlertTriangle,
  Play,
  FileCode,
  FileText,
  RotateCw,
  ExternalLink,
  ChevronDown,
  ChevronUp,
  Bot,
  ShieldAlert,
  Terminal,
} from "lucide-react";

const INITIAL_DEMO_TASKS: SidebarTaskItem[] = [
  { id: "task-1", title: "Nghiên cứu thị trường AI Agents 2026", status: "completed", group: "today" },
  { id: "task-2", title: "Soạn kịch bản TikTok 60s hook tài chính", status: "running", group: "today" },
  { id: "task-3", title: "Thiết kế Landing Page khóa học Solopreneur", status: "waiting_review", group: "yesterday" },
  { id: "task-4", title: "Viết chuỗi 5 email onboarding khách hàng", status: "completed", group: "past7days" },
];

export default function HomePage() {
  const [apiClient] = useState(() => new ApiClient());
  const [agents, setAgents] = useState<Agent[]>([]);
  const [tasks, setTasks] = useState<SidebarTaskItem[]>(INITIAL_DEMO_TASKS);
  const [selectedTaskId, setSelectedTaskId] = useState<string | undefined>("task-2");
  const [activeNav, setActiveNav] = useState("workspace");
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [lastParsedTask, setLastParsedTask] = useState<ParsedTask | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  // Live Task Execution State
  const [activeTask, setActiveTask] = useState<BoardTask | null>(null);
  const [taskLogs, setTaskLogs] = useState<TaskLogEntry[]>([]);
  const [taskArtifacts, setTaskArtifacts] = useState<any[]>([]);
  const [activeReview, setActiveReview] = useState<ReviewGate | null>(null);
  const [isExecuting, setIsExecuting] = useState(false);
  const [activeArtifactTab, setActiveArtifactTab] = useState<"preview" | "logs">("preview");

  const pollTimerRef = useRef<NodeJS.Timeout | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  // Initialize and check backend connection
  useEffect(() => {
    let isMounted = true;

    async function initializeWorkspace() {
      try {
        await apiClient.checkHealth();
        if (!isMounted) return;
        setBackendOnline(true);

        const loadedAgents = await apiClient.listAgents();
        if (isMounted && loadedAgents && loadedAgents.length > 0) {
          setAgents(loadedAgents);
        }

        const remoteTasks = await apiClient.listTasks({ limit: 20 });
        if (isMounted && remoteTasks && remoteTasks.length > 0) {
          const sidebarItems: SidebarTaskItem[] = remoteTasks.map((t) => ({
            id: t.id,
            title: t.title,
            status: t.status as any,
            group: "today",
          }));
          setTasks(sidebarItems);
          if (sidebarItems.length > 0) {
            setSelectedTaskId(sidebarItems[0].id);
          }
        }
      } catch {
        if (!isMounted) return;
        setBackendOnline(false);
      }
    }

    initializeWorkspace();

    return () => {
      isMounted = false;
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
      if (wsRef.current) wsRef.current.close();
    };
  }, [apiClient]);

  // Load task details when selectedTaskId changes
  const loadTaskDetails = useCallback(
    async (taskId: string) => {
      if (!taskId) return;
      try {
        const [taskData, logs, artifacts, reviews] = await Promise.all([
          apiClient.getTask(taskId).catch(() => null),
          apiClient.getTaskLogs(taskId).catch(() => []),
          apiClient.listArtifacts({ taskId }).catch(() => []),
          apiClient.listReviews(taskId, "pending").catch(() => []),
        ]);

        if (taskData) {
          setActiveTask(taskData);
          if (taskData.status === "running") {
            setIsExecuting(true);
          } else {
            setIsExecuting(false);
          }
        }
        setTaskLogs(logs || []);
        setTaskArtifacts(artifacts || []);
        setActiveReview(reviews && reviews.length > 0 ? reviews[0] : null);
      } catch (err) {
        // Fallback for offline demo tasks
      }
    },
    [apiClient]
  );

  useEffect(() => {
    if (selectedTaskId) {
      loadTaskDetails(selectedTaskId);
    }
  }, [selectedTaskId, loadTaskDetails]);

  // Start polling execution progress
  const startPolling = useCallback(
    (taskId: string) => {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);

      setIsExecuting(true);
      let pollCount = 0;

      pollTimerRef.current = setInterval(async () => {
        pollCount += 1;
        try {
          const [taskData, logs, artifacts, reviews] = await Promise.all([
            apiClient.getTask(taskId).catch(() => null),
            apiClient.getTaskLogs(taskId).catch(() => []),
            apiClient.listArtifacts({ taskId }).catch(() => []),
            apiClient.listReviews(taskId, "pending").catch(() => []),
          ]);

          if (taskData) {
            setActiveTask(taskData);
            setTasks((prev) =>
              prev.map((t) => (t.id === taskId ? { ...t, status: taskData.status as any } : t))
            );

            if (taskData.status === "completed" || taskData.status === "failed" || taskData.status === "cancelled") {
              setIsExecuting(false);
              if (pollTimerRef.current) clearInterval(pollTimerRef.current);
            }
          }

          if (logs && logs.length > 0) {
            setTaskLogs(logs);
          }
          if (artifacts && artifacts.length > 0) {
            setTaskArtifacts(artifacts);
          }
          if (reviews && reviews.length > 0) {
            setActiveReview(reviews[0]);
          }

          if (pollCount > 100) {
            if (pollTimerRef.current) clearInterval(pollTimerRef.current);
            setIsExecuting(false);
          }
        } catch {
          // ignore transient poll error
        }
      }, 1500);
    },
    [apiClient]
  );

  const handleNewTask = () => {
    setSelectedTaskId(undefined);
    setActiveTask(null);
    setTaskLogs([]);
    setTaskArtifacts([]);
    setActiveReview(null);
    setLastParsedTask(null);
    setStatusMessage(null);
    setIsExecuting(false);
  };

  const handleSelectTask = (id: string) => {
    setSelectedTaskId(id);
  };

  // Submit and Dispatch task to execution
  const handleSubmit = async (data: {
    prompt: string;
    mode: ExecutionMode;
    attachments: AttachmentItem[];
  }) => {
    setIsSubmitting(true);
    setStatusMessage(null);

    try {
      // 1. Parse prompt & create pending task in DB
      const parsed = await apiClient.parseTask(data.prompt, {
        mode: data.mode,
        attachments: data.attachments.map((a) => a.name),
      });

      setLastParsedTask(parsed);
      const taskId = parsed.taskId;

      const newTaskItem: SidebarTaskItem = {
        id: taskId,
        title: data.prompt.length > 40 ? `${data.prompt.slice(0, 40)}...` : data.prompt,
        status: "running",
        group: "today",
      };

      setTasks((prev) => [newTaskItem, ...prev]);
      setSelectedTaskId(taskId);
      setStatusMessage("Master Commander đã phân rã lệnh và kích hoạt Agent thực thi!");

      // 2. Dispatch task to AgentDispatcher runtime
      await apiClient.dispatchTask(taskId, { mode: data.mode });

      // 3. Start live polling & WebSocket streaming
      startPolling(taskId);
    } catch (err) {
      // Offline fallback handling
      const fallbackTaskId = `task-local-${Date.now()}`;
      const fallbackParsed: ParsedTask = {
        taskId: fallbackTaskId,
        task_id: fallbackTaskId,
        intent: "local_offline_intent",
        taskType: "general",
        mentionedAgents: [],
        urls: [],
        attachmentIds: data.attachments.map((a) => a.id),
        entities: {},
        plan: null,
      };

      setLastParsedTask(fallbackParsed);

      const fallbackTaskItem: SidebarTaskItem = {
        id: fallbackTaskId,
        title: data.prompt.length > 40 ? `${data.prompt.slice(0, 40)}...` : data.prompt,
        status: "completed",
        group: "today",
      };

      setTasks((prev) => [fallbackTaskItem, ...prev]);
      setSelectedTaskId(fallbackTaskId);

      // Create synthetic mock log & output for offline demonstration
      setTaskLogs([
        {
          id: "turn-1",
          logType: "turn",
          taskId: fallbackTaskId,
          turnNumber: 1,
          agentName: "ContentWriter",
          agentDisplayName: "Trần Viết Văn",
          action: "execute_subtask",
          tool: "llm_router",
          status: "completed",
          durationMs: 1240,
          tokens: 450,
          outputPayload: {
            result: `## Kịch Bản & Kế Hoạch Nội Dung Đã Tạo\n\n- **Mục tiêu:** ${data.prompt}\n- **Thời lượng:** 60 giây\n- **Hook:** "90% người dùng bỏ lỡ tính năng này trong năm 2026..."\n- **Kêu gọi hành động:** Nhấn link bên dưới để nhận tài liệu miễn phí!`,
          },
        },
      ]);

      setStatusMessage(
        "Chế độ ngoại tuyến: Lệnh đã được lưu cục bộ (Backend daemon chưa kết nối)."
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  // Handle Review Decision (Approve / Reject / Modify)
  const handleReviewDecision = async (
    decision: ReviewDecision,
    payload?: ReviewDecidePayload
  ) => {
    if (!activeReview || !selectedTaskId) return;
    try {
      await apiClient.decideReview(activeReview.id, decision, payload);

      setStatusMessage(
        decision === "approve"
          ? "Đã phê duyệt sản phẩm thành công! Tác vụ chuyển sang giai đoạn hoàn tất."
          : decision === "reject"
          ? "Đã từ chối và gửi phản hồi yêu cầu làm lại."
          : "Đã cập nhật nội dung chỉnh sửa."
      );

      // Refresh task details
      await loadTaskDetails(selectedTaskId);
    } catch (err) {
      alert("Lỗi khi xử lý quyết định duyệt: " + (err instanceof Error ? err.message : String(err)));
    }
  };

  // Helper to extract primary artifact or log output
  const artifactsList = Array.isArray(taskArtifacts) ? taskArtifacts : [];
  const primaryHtmlArtifact = artifactsList.find(
    (a) =>
      a?.file_type === "html" ||
      (a?.name && a.name.endsWith(".html")) ||
      (a?.mime_type && a.mime_type.includes("html"))
  );

  const primaryMarkdownArtifact = artifactsList.find(
    (a) =>
      a?.file_type === "markdown" ||
      (a?.name && (a.name.endsWith(".md") || a.name.endsWith(".markdown")))
  );

  const lastTurn = taskLogs.length > 0 ? taskLogs[taskLogs.length - 1] : null;
  const outPayload = lastTurn?.outputPayload as any;
  const fallbackOutputText: string =
    typeof outPayload === "string"
      ? outPayload
      : typeof outPayload?.result === "string"
      ? outPayload.result
      : typeof outPayload?.content === "string"
      ? outPayload.content
      : outPayload
      ? JSON.stringify(outPayload, null, 2)
      : "";

  return (
    <div className="flex h-screen bg-gray-950 text-gray-100 overflow-hidden font-sans">
      {/* Left Sidebar Navigation */}
      <SidebarNav
        tasks={tasks}
        selectedTaskId={selectedTaskId}
        activeNav={activeNav}
        onNewTask={handleNewTask}
        onSelectTask={handleSelectTask}
        onNavigate={(navId) => {
          setActiveNav(navId);
          if (typeof window !== "undefined") {
            if (navId === "office") window.location.assign("/office");
            else if (navId === "board") window.location.assign("/board");
            else if (navId === "library") window.location.assign("/library");
            else if (navId === "brain") window.location.assign("/brain");
            else if (navId === "customer_chat" || navId === "inbox") window.location.assign("/inbox");
            else if (navId === "settings") window.location.assign("/settings");
          }
        }}
      />

      {/* Main Workspace Viewport */}
      <main className="flex-1 flex flex-col h-full overflow-hidden bg-gray-950">
        {/* Top Header Shell */}
        <header className="h-14 border-b border-gray-800 px-6 flex items-center justify-between shrink-0 bg-gray-900/60 backdrop-blur-sm">
          <div className="flex items-center gap-3">
            <h1 className="text-sm font-semibold tracking-wide text-gray-100">
              Văn Phòng AI (AI Agent Workspace)
            </h1>
            <span className="text-xs text-gray-500">|</span>
            <span className="text-xs text-sky-400 font-medium flex items-center gap-1.5">
              <Sparkles className="w-3.5 h-3.5" />
              Tổng Hành Dinh &amp; Điều Phối Đa Tác Tử
            </span>
          </div>

          <div className="flex items-center gap-4 text-xs">
            {/* Backend connectivity indicator */}
            <div className="flex items-center gap-1.5">
              {backendOnline === true ? (
                <span className="flex items-center gap-1.5 text-emerald-400 font-medium">
                  <Wifi className="w-3.5 h-3.5" />
                  <span>Backend 8765 Sẵn Sàng</span>
                </span>
              ) : backendOnline === false ? (
                <span
                  className="flex items-center gap-1.5 text-amber-400 font-medium"
                  title="Backend chưa chạy, đang ở chế độ giao diện cục bộ"
                >
                  <WifiOff className="w-3.5 h-3.5" />
                  <span>Chế độ Cục Bộ (Offline)</span>
                </span>
              ) : (
                <span className="flex items-center gap-1.5 text-gray-400">
                  <Clock className="w-3.5 h-3.5 animate-spin" />
                  <span>Đang kiểm tra daemon...</span>
                </span>
              )}
            </div>

            <div className="h-4 w-px bg-gray-800" />

            {/* Quick stats */}
            <div className="flex items-center gap-3 text-gray-400">
              <span className="flex items-center gap-1">
                <UserCheck className="w-3.5 h-3.5 text-sky-400" />
                <span>{agents.length > 0 ? `${agents.length} Agent` : "12 Agent Sẵn Sàng"}</span>
              </span>
              <span className="flex items-center gap-1">
                <Layers className="w-3.5 h-3.5 text-purple-400" />
                <span>5 Phòng Ban</span>
              </span>
            </div>
          </div>
        </header>

        {/* Central Scrollable Canvas */}
        <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
          <div className="max-w-5xl w-full mx-auto space-y-6">
            {/* Welcome Banner */}
            <div className="text-center space-y-1.5 pt-2">
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-sky-950/60 border border-sky-800/50 text-sky-300 text-xs font-medium mb-1">
                <Sparkles className="w-3.5 h-3.5 text-sky-400" />
                <span>Nền tảng Tác tử AI Tự Hành Đa Phòng Ban</span>
              </div>
              <h2 className="text-2xl md:text-3xl font-bold tracking-tight text-white">
                Hôm nay bạn muốn hoàn thành việc gì?
              </h2>
              <p className="text-xs md:text-sm text-gray-400 max-w-xl mx-auto leading-relaxed">
                Nhập mục tiêu bằng tiếng Việt, tag <span className="text-sky-400 font-mono">@Agent</span> và đính kèm tài liệu. Hệ thống sẽ tự động lập kế hoạch, điều phối các Agent chạy và xuất sản phẩm ngay tại đây.
              </p>
            </div>

            {/* Status notification banner if submitted */}
            {statusMessage && (
              <div className="p-3.5 rounded-xl bg-sky-950/40 border border-sky-800/60 text-xs text-sky-200 flex items-center justify-between">
                <span className="flex items-center gap-2">
                  <CheckCircle2 className="w-4 h-4 text-sky-400 shrink-0" />
                  <span>{statusMessage}</span>
                </span>
                {selectedTaskId && (
                  <span className="font-mono text-[11px] text-sky-300 bg-sky-900/50 px-2 py-0.5 rounded">
                    Task ID: {selectedTaskId}
                  </span>
                )}
              </div>
            )}

            {/* Central Master Commander Prompt Box */}
            <CommanderPromptBox
              agents={agents}
              onSubmit={handleSubmit}
              isSubmitting={isSubmitting}
            />

            {/* Human-in-the-Loop Review Gate (if task requires approval) */}
            {activeReview && (
              <div className="space-y-2">
                <div className="flex items-center gap-2 text-xs font-semibold text-amber-400">
                  <ShieldAlert className="w-4 h-4" />
                  <span>Yêu Cầu Duyệt Sản Phẩm (Human-in-the-Loop Gate)</span>
                </div>
                <ReviewGateBanner
                  review={activeReview}
                  onDecide={handleReviewDecision}
                />
              </div>
            )}

            {/* Live Execution Stream & Output Artifact Viewer */}
            {(isExecuting || taskLogs.length > 0 || taskArtifacts.length > 0 || fallbackOutputText) && (
              <div className="rounded-2xl bg-gray-900/90 border border-gray-800 overflow-hidden shadow-2xl space-y-0">
                {/* Panel Header */}
                <div className="px-5 py-3.5 border-b border-gray-800 flex flex-wrap items-center justify-between gap-3 bg-gray-950/50">
                  <div className="flex items-center gap-3">
                    <div className="flex items-center gap-2">
                      <span className="w-2.5 h-2.5 rounded-full bg-sky-400 animate-pulse" />
                      <h3 className="text-sm font-semibold text-white">
                        {activeTask?.title || "Tiến độ thực thi tác vụ"}
                      </h3>
                    </div>
                    {isExecuting ? (
                      <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-sky-950 text-sky-300 border border-sky-800 flex items-center gap-1">
                        <RotateCw className="w-3 h-3 animate-spin" />
                        Đang chạy...
                      </span>
                    ) : (
                      <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-950 text-emerald-300 border border-emerald-800">
                        ✓ Hoàn tất
                      </span>
                    )}
                  </div>

                  {/* Tabs: Preview Sản Phẩm vs Chi Tiết Nhật Ký Turns */}
                  <div className="flex items-center gap-1 p-1 rounded-xl bg-gray-900 border border-gray-800 text-xs">
                    <button
                      type="button"
                      onClick={() => setActiveArtifactTab("preview")}
                      className={`flex items-center gap-1.5 px-3 py-1 rounded-lg font-medium transition-all cursor-pointer ${
                        activeArtifactTab === "preview"
                          ? "bg-sky-500 text-white"
                          : "text-gray-400 hover:text-gray-200"
                      }`}
                    >
                      <Sparkles className="w-3.5 h-3.5" />
                      <span>Xem Sản Phẩm Đầu Ra</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => setActiveArtifactTab("logs")}
                      className={`flex items-center gap-1.5 px-3 py-1 rounded-lg font-medium transition-all cursor-pointer ${
                        activeArtifactTab === "logs"
                          ? "bg-sky-500 text-white"
                          : "text-gray-400 hover:text-gray-200"
                      }`}
                    >
                      <Terminal className="w-3.5 h-3.5" />
                      <span>Nhật ký Agent ({taskLogs.length} turns)</span>
                    </button>
                  </div>
                </div>

                {/* Tab 1: Product Output Preview */}
                {activeArtifactTab === "preview" && (
                  <div className="p-5">
                    {/* 1. HTML Landing Page Artifact */}
                    {primaryHtmlArtifact ? (
                      <div className="space-y-3">
                        <div className="flex items-center justify-between text-xs text-gray-400">
                          <span className="flex items-center gap-1.5 text-sky-300 font-medium">
                            <FileCode className="w-4 h-4 text-sky-400" />
                            <span>Landing Page Sandbox: {primaryHtmlArtifact.name}</span>
                          </span>
                          {primaryHtmlArtifact.id && (
                            <a
                              href={apiClient.streamMediaUrl(primaryHtmlArtifact.id)}
                              target="_blank"
                              rel="noreferrer"
                              className="flex items-center gap-1 text-sky-400 hover:underline"
                            >
                              <span>Mở toàn màn hình</span>
                              <ExternalLink className="w-3 h-3" />
                            </a>
                          )}
                        </div>
                        <HtmlSandboxViewer
                          html={
                            primaryHtmlArtifact.metadata?.content_inline ||
                            primaryHtmlArtifact.content ||
                            "<!DOCTYPE html><html><body style='color:#fff;background:#111;padding:40px;font-family:sans-serif;'><h2>Landing Page Preview</h2><p>Trang web mẫu do UIDesigner tạo.</p></body></html>"
                          }
                          title={primaryHtmlArtifact.name}
                        />
                      </div>
                    ) : primaryMarkdownArtifact || fallbackOutputText ? (
                      /* 2. Markdown Article / Script / Report */
                      <div className="space-y-3">
                        <div className="flex items-center justify-between text-xs text-gray-400">
                          <span className="flex items-center gap-1.5 text-sky-300 font-medium">
                            <FileText className="w-4 h-4 text-sky-400" />
                            <span>Bản thảo nội dung &amp; Kế hoạch tác vụ</span>
                          </span>
                        </div>
                        <div className="p-4 rounded-xl bg-gray-950 border border-gray-800">
                          <MarkdownViewer
                            content={
                              primaryMarkdownArtifact?.content ||
                              fallbackOutputText ||
                              "Đang xử lý nội dung từ Agent..."
                            }
                          />
                        </div>
                      </div>
                    ) : (
                      <div className="text-center py-12 text-gray-500 text-xs space-y-2">
                        <RotateCw className="w-6 h-6 animate-spin mx-auto text-sky-400/70" />
                        <p>Các Agent đang thực thi... Sản phẩm đầu ra sẽ xuất hiện tại đây khi hoàn thành.</p>
                      </div>
                    )}
                  </div>
                )}

                {/* Tab 2: Agent Turns Timeline */}
                {activeArtifactTab === "logs" && (
                  <div className="p-5 divide-y divide-gray-800/80 max-h-[460px] overflow-y-auto">
                    {taskLogs.length === 0 ? (
                      <div className="text-center py-8 text-xs text-gray-500">
                        Chưa có lượt thực thi nào được ghi nhận.
                      </div>
                    ) : (
                      taskLogs.map((log, idx) => (
                        <div key={log.id || idx} className="py-3 first:pt-0 last:pb-0 space-y-2 text-xs">
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <span className="px-2 py-0.5 rounded bg-sky-950 text-sky-300 border border-sky-800 font-mono text-[11px] font-semibold">
                                @{log.agentName || "Agent"}
                              </span>
                              <span className="text-gray-300 font-medium">
                                {log.agentDisplayName || log.action}
                              </span>
                              <span className="text-gray-500 text-[11px]">
                                Turn #{log.turnNumber || idx + 1}
                              </span>
                            </div>
                            <div className="flex items-center gap-3 text-[11px] text-gray-400 font-mono">
                              {log.durationMs && <span>{log.durationMs}ms</span>}
                              {log.tokens && <span>{log.tokens} tok</span>}
                              <span className="text-emerald-400">✓ Xong</span>
                            </div>
                          </div>

                          {log.outputPayload != null && (
                            <div className="p-2.5 rounded-lg bg-gray-950 border border-gray-800 text-gray-300 font-mono text-[11px] whitespace-pre-wrap max-h-40 overflow-y-auto">
                              {typeof log.outputPayload === "string"
                                ? log.outputPayload
                                : typeof (log.outputPayload as any).result === "string"
                                ? (log.outputPayload as any).result
                                : typeof (log.outputPayload as any).content === "string"
                                ? (log.outputPayload as any).content
                                : JSON.stringify(log.outputPayload, null, 2)}
                            </div>
                          )}
                        </div>
                      ))
                    )}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Bottom Tips & Shortcuts */}
          <footer className="pt-4 text-center text-xs text-gray-600">
            <span>Mẹo: Gõ </span>
            <kbd className="px-1.5 py-0.5 rounded bg-gray-800 text-gray-400 font-mono text-[11px]">@</kbd>
            <span> để gọi chuyên viên, nhấn </span>
            <kbd className="px-1.5 py-0.5 rounded bg-gray-800 text-gray-400 font-mono text-[11px]">Enter</kbd>
            <span> để gửi hoặc </span>
            <kbd className="px-1.5 py-0.5 rounded bg-gray-800 text-gray-400 font-mono text-[11px]">Shift + Enter</kbd>
            <span> để xuống dòng.</span>
          </footer>
        </div>
      </main>
    </div>
  );
}
