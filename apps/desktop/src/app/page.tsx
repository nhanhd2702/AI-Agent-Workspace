"use client";

import React, { useState, useEffect } from "react";
import { SidebarNav } from "@/components/layout/SidebarNav";
import { CommanderPromptBox } from "@/components/chat/CommanderPromptBox";
import { ApiClient } from "@/lib/apiClient";
import { Agent, AttachmentItem, ExecutionMode, ParsedTask, SidebarTaskItem } from "@/lib/types";
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
      } catch {
        if (!isMounted) return;
        setBackendOnline(false);
      }
    }

    initializeWorkspace();

    return () => {
      isMounted = false;
    };
  }, [apiClient]);

  const handleNewTask = () => {
    setSelectedTaskId(undefined);
    setLastParsedTask(null);
    setStatusMessage(null);
  };

  const handleSelectTask = (id: string) => {
    setSelectedTaskId(id);
  };

  const handleSubmit = async (data: {
    prompt: string;
    mode: ExecutionMode;
    attachments: AttachmentItem[];
  }) => {
    setIsSubmitting(true);
    setStatusMessage(null);

    try {
      const parsed = await apiClient.parseTask(data.prompt, {
        mode: data.mode,
        attachments: data.attachments.map((a) => a.name),
      });

      setLastParsedTask(parsed);

      const newTaskItem: SidebarTaskItem = {
        id: parsed.taskId || `task-${Date.now()}`,
        title: data.prompt.length > 40 ? `${data.prompt.slice(0, 40)}...` : data.prompt,
        status: "running",
        group: "today",
      };

      setTasks((prev) => [newTaskItem, ...prev]);
      setSelectedTaskId(newTaskItem.id);
      setStatusMessage("Yêu cầu đã được Master Commander tiếp nhận và phân rã thành công!");
    } catch (err) {
      // Offline fallback handling so the UI never crashes when backend is not running
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
        status: "pending",
        group: "today",
      };

      setTasks((prev) => [fallbackTaskItem, ...prev]);
      setSelectedTaskId(fallbackTaskId);
      setStatusMessage(
        "Chế độ ngoại tuyến: Lệnh đã được lưu cục bộ (Backend daemon chưa kết nối)."
      );
    } finally {
      setIsSubmitting(false);
    }
  };

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
            else if (navId === "brain") window.location.assign("/brain");
            else if (navId === "customer_chat" || navId === "inbox") window.location.assign("/inbox");
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
              Tổng Chỉ Huy & Điều Phối Đa Tác Tử
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
                <span className="flex items-center gap-1.5 text-amber-400 font-medium" title="Backend chưa chạy, đang ở chế độ giao diện cục bộ">
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
        <div className="flex-1 overflow-y-auto px-6 py-8 flex flex-col justify-between">
          <div className="max-w-4xl w-full mx-auto space-y-6">
            {/* Welcome Banner */}
            <div className="text-center space-y-2 pt-4">
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-sky-950/60 border border-sky-800/50 text-sky-300 text-xs font-medium mb-1">
                <Sparkles className="w-3.5 h-3.5 text-sky-400" />
                <span>Nền tảng Tác tử AI Điều phối Đa Phòng Ban</span>
              </div>
              <h2 className="text-2xl md:text-3xl font-bold tracking-tight text-white">
                Hôm nay bạn muốn hoàn thành việc gì?
              </h2>
              <p className="text-sm text-gray-400 max-w-xl mx-auto leading-relaxed">
                Nhập mục tiêu bằng ngôn ngữ tự nhiên, tag <span className="text-sky-400 font-mono">@Agent</span> chuyên môn và đính kèm tài liệu. Master Commander sẽ tự động phân rã kế hoạch và chỉ huy đội ngũ thực thi.
              </p>
            </div>

            {/* Status notification banner if submitted */}
            {statusMessage && (
              <div className="p-3.5 rounded-xl bg-sky-950/40 border border-sky-800/60 text-xs text-sky-200 flex items-center justify-between">
                <span className="flex items-center gap-2">
                  <CheckCircle2 className="w-4 h-4 text-sky-400 shrink-0" />
                  <span>{statusMessage}</span>
                </span>
                {lastParsedTask && (
                  <span className="font-mono text-[11px] text-sky-300 bg-sky-900/50 px-2 py-0.5 rounded">
                    Task ID: {lastParsedTask.taskId}
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

            {/* Last Parsed Intent & Decomposition Card */}
            {lastParsedTask && (
              <div className="p-4 rounded-xl bg-gray-900 border border-gray-800 space-y-3">
                <div className="flex items-center justify-between border-b border-gray-800 pb-2">
                  <div className="flex items-center gap-2 text-xs font-semibold text-gray-300">
                    <Activity className="w-4 h-4 text-sky-400" />
                    <span>Chi Tiết Phân Rã Lệnh (Parsed Intent)</span>
                  </div>
                  <span className="text-[11px] text-gray-500 font-mono">
                    {lastParsedTask.taskType || "task"}
                  </span>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
                  <div>
                    <span className="text-gray-500 block">Ý định (Intent):</span>
                    <span className="font-medium text-gray-200">{lastParsedTask.intent}</span>
                  </div>
                  <div>
                    <span className="text-gray-500 block">Agent được tag:</span>
                    <span className="font-medium text-sky-400">
                      {lastParsedTask.mentionedAgents.length > 0
                        ? lastParsedTask.mentionedAgents.map((a) => `@${a}`).join(", ")
                        : "Tự động phân công"}
                    </span>
                  </div>
                  <div>
                    <span className="text-gray-500 block">URLs nhận diện:</span>
                    <span className="font-medium text-gray-300">
                      {lastParsedTask.urls.length > 0 ? `${lastParsedTask.urls.length} link` : "Không có"}
                    </span>
                  </div>
                  <div>
                    <span className="text-gray-500 block">Tệp đính kèm:</span>
                    <span className="font-medium text-gray-300">
                      {lastParsedTask.attachmentIds.length > 0
                        ? `${lastParsedTask.attachmentIds.length} tệp`
                        : "Không có"}
                    </span>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Bottom Tips & Shortcuts */}
          <footer className="pt-6 text-center text-xs text-gray-600">
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
