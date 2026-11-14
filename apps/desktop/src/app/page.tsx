"use client";

import React, { useState, useEffect, useRef } from "react";
import { SidebarNav, ExtendedSidebarTaskItem, AgentChibiAvatar } from "@/components/layout/SidebarNav";
import { CommanderOmnibar } from "@/components/chat/CommanderOmnibar";
import { ActionCollapseBox, ActionItem } from "@/components/chat/ActionCollapseBox";
import { HumanDecisionCard } from "@/components/chat/HumanDecisionCard";
import { TaskDetailsPanel, TaskDetailsData, TaskStage } from "@/components/chat/TaskDetailsPanel";
import { ApiClient } from "@/lib/apiClient";
import { Agent, SidebarTaskItem } from "@/lib/types";
import {
  Wifi,
  WifiOff,
  Sparkles,
  Bot,
  User,
  CheckCircle2,
  Clock,
  RotateCw,
  Layers,
  ChevronRight,
  ShieldCheck,
} from "lucide-react";

export interface ChatMessage {
  id: string;
  sender: "user" | "agent" | "system";
  agentName?: string;
  content: string;
  createdAt: string;
  actions?: ActionItem[];
  showDecisionCard?: boolean;
  decisionData?: {
    title: string;
    description: string;
    credits: number;
  };
}

const INITIAL_DEMO_TASKS: ExtendedSidebarTaskItem[] = [
  {
    id: "task-1",
    title: "Nghiên cứu thị trường AI Agents 2026",
    status: "completed",
    group: "today",
    agentId: "DeepResearcher",
  },
  {
    id: "task-2",
    title: "Soạn kịch bản TikTok 60s hook tài chính",
    status: "running",
    group: "today",
    agentId: "ContentWriter",
  },
  {
    id: "task-3",
    title: "Thiết kế Landing Page khóa học Solopreneur",
    status: "waiting_review",
    group: "yesterday",
    agentId: "UIDesigner",
  },
  {
    id: "task-4",
    title: "Viết chuỗi 5 email onboarding khách hàng",
    status: "completed",
    group: "past7days",
    agentId: "ContentWriter",
  },
];

const INITIAL_TASK_DETAILS: Record<string, TaskDetailsData> = {
  "task-2": {
    id: "task-2",
    title: "Soạn kịch bản TikTok 60s hook tài chính",
    description: "Kịch bản giữ chân người xem 3s đầu với visual Sketchnote và nhạc nền 120BPM",
    currentStage: "in_progress",
    workflow: [
      { step: 1, agentName: "HookMaster", role: "Nghiên cứu góc nhìn & 3 Hook mở đầu", status: "completed" },
      { step: 2, agentName: "ContentWriter", role: "Biên soạn kịch bản 60s chuẩn W-structure", status: "in_progress" },
      { step: 3, agentName: "VideoEditor", role: "Khớp âm thanh DSP & hiệu ứng visual", status: "pending" },
    ],
    deliverables: [
      {
        id: "del-tt-1",
        name: "kich_ban_tiktok_hook_tai_chinh.md",
        type: "markdown",
        size: "3.4 KB",
        content: "# Kịch Bản TikTok 60s: Đừng Tiết Kiệm Tiền Nữa!\n\n**0:00 - 0:03 [Hook]:** Bạn đang để 100 triệu trong ngân hàng và nghĩ mình an toàn?\n**0:03 - 0:15 [Vấn đề]:** Lạm phát thực tế đang âm thầm lấy đi 8% mỗi năm...\n**0:15 - 0:45 [Giải pháp]:** Quy tắc 3 chiếc lọ tài chính thế hệ mới.\n**0:45 - 0:60 [CTA]:** Nhận bảng tính tự động ở bio!",
      },
      {
        id: "del-tt-2",
        name: "preview_video_storyboard.html",
        type: "html",
        size: "28 KB",
        content: "<!DOCTYPE html><html><body style='font-family:sans-serif;padding:24px;background:#090d16;color:#e2e8f0;'><h2 style='color:#38bdf8;'>Storyboard: Video Hook Tài Chính 60s</h2><div style='background:#1e293b;padding:16px;border-radius:12px;margin-top:12px;'><p><strong>Cảnh 1:</strong> Bàn tay cầm cọc tiền tan biến thành khói đen (Hiệu ứng After Effects).</p><p><strong>Cảnh 2:</strong> Biểu đồ lạm phát dựng đứng màu đỏ neon.</p></div></body></html>",
      },
    ],
    files: [
      { name: "bao_cao_chi_so_cpi_2026.pdf", size: "2.1 MB", uploadedAt: "09:15" },
      { name: "audio_bgm_120bpm.mp3", size: "4.8 MB", uploadedAt: "09:20" },
    ],
    browserPages: [
      { id: "page-1", title: "Nghiên cứu đối thủ TikTok", url: "https://tiktok.com/@finance_hacks" },
    ],
  },
  "task-3": {
    id: "task-3",
    title: "Thiết kế Landing Page khóa học Solopreneur",
    description: "Xây dựng phễu trang đích chuyển đổi cao tặng cẩm nang kinh doanh solo",
    currentStage: "waiting_human",
    workflow: [
      { step: 1, agentName: "GrowthAdvisor", role: "Định vị & USP", status: "completed" },
      { step: 2, agentName: "ContentWriter", role: "Soạn kịch bản & nội dung", status: "completed" },
      { step: 3, agentName: "UIDesigner", role: "Thiết kế Interactive Web", status: "in_progress" },
    ],
    deliverables: [
      {
        id: "del-lp-1",
        name: "landing_page_solopreneur.html",
        type: "html",
        size: "42 KB",
        content: "<!DOCTYPE html><html><body style='font-family:sans-serif;padding:40px;background:#0f172a;color:#f8fafc;'><h1 style='color:#6366f1;'>Khóa Học Solopreneur AI 2026</h1><p style='color:#94a3b8;'>Hệ thống hóa kinh doanh 1 người với 12 AI Agents tự hành.</p><button style='background:#6366f1;color:#fff;border:none;padding:12px 24px;border-radius:8px;font-weight:bold;cursor:pointer;margin-top:20px;'>Đăng ký nhận cẩm nang</button></body></html>",
      },
    ],
    files: [
      { name: "brand_assets.zip", size: "8.4 MB", uploadedAt: "Hôm qua" },
    ],
    browserPages: [
      { id: "page-2", title: "Live Preview Page", url: "http://localhost:3000/preview/solopreneur" },
    ],
  },
};

const INITIAL_MESSAGES: Record<string, ChatMessage[]> = {
  "task-2": [
    {
      id: "msg-1",
      sender: "user",
      content: "Soạn cho anh kịch bản video TikTok 60s hook tài chính, nhắm tới đối tượng người trẻ 22-30 tuổi.",
      createdAt: "09:14",
    },
    {
      id: "msg-2",
      sender: "agent",
      agentName: "Người điều phối",
      content: "Chào anh! Em đã phân tích yêu cầu: Mục tiêu tạo video 60s giữ chân cao. Em điều phối @HookMaster tạo 3 phương án mở đầu giật gân, sau đó @ContentWriter viết kịch bản chi tiết và @VideoEditor dựng storyboard.",
      createdAt: "09:15",
      actions: [
        {
          id: "act-1",
          title: "Phân tích xu hướng TikTok thịnh hành qua SerpApi",
          durationMs: 44,
          status: "completed",
          detail: "Query: top trending finance tiktok hooks vietnam 2026",
        },
        {
          id: "act-2",
          title: "Kích hoạt mô hình lý luận HookMaster",
          durationMs: 89,
          status: "completed",
          detail: "Prompt tokens: 1,420 | Output tokens: 380",
        },
      ],
    },
    {
      id: "msg-3",
      sender: "agent",
      agentName: "ContentWriter",
      content: "Em đã hoàn thành bản thảo kịch bản 60s với hook 'Đừng tiết kiệm tiền nữa!'. Kịch bản áp dụng công thức W-structure và đã sẵn sàng bên cột BÀN GIAO để anh kiểm tra.",
      createdAt: "09:18",
      actions: [
        {
          id: "act-3",
          title: "Xuất file markdown kich_ban_tiktok_hook_tai_chinh.md",
          durationMs: 1200,
          status: "completed",
          detail: "File size: 3.4KB | Saved in library",
        },
      ],
    },
  ],
};

export default function HomePage() {
  const [apiClient] = useState(() => new ApiClient());
  const [tasks, setTasks] = useState<ExtendedSidebarTaskItem[]>(INITIAL_DEMO_TASKS);
  const [selectedTaskId, setSelectedTaskId] = useState<string>("task-2");
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
  const [messages, setMessages] = useState<Record<string, ChatMessage[]>>(INITIAL_MESSAGES);
  const [taskDetails, setTaskDetails] = useState<Record<string, TaskDetailsData>>(INITIAL_TASK_DETAILS);
  const [isExecuting, setIsExecuting] = useState(false);

  const chatBottomRef = useRef<HTMLDivElement>(null);

  // Initialize and check backend health
  useEffect(() => {
    let isMounted = true;
    async function checkHealth() {
      try {
        await apiClient.checkHealth();
        if (isMounted) setBackendOnline(true);
      } catch {
        if (isMounted) setBackendOnline(false);
      }
    }
    checkHealth();
    return () => {
      isMounted = false;
    };
  }, [apiClient]);

  // Scroll chat to bottom when new messages arrive
  useEffect(() => {
    if (typeof chatBottomRef.current?.scrollIntoView === "function") {
      chatBottomRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, selectedTaskId]);

  const activeTask = tasks.find((t) => t.id === selectedTaskId) || tasks[0];
  const activeTaskDetails = taskDetails[selectedTaskId] || {
    id: activeTask.id,
    title: activeTask.title,
    currentStage: "in_progress" as TaskStage,
    workflow: [
      { step: 1, agentName: "Người điều phối", role: "Điều phối tác vụ", status: "completed" },
    ],
    deliverables: [],
    files: [],
    browserPages: [],
  };

  const currentMessages = messages[selectedTaskId] || [];

  const handleOmnibarSubmit = async (data: {
    prompt: string;
    targetAgent?: string;
    model?: string;
    team?: string;
    format?: string;
    handsfree?: boolean;
    attachments?: File[];
  }) => {
    if (!data.prompt.trim()) return;

    const userMsg: ChatMessage = {
      id: `msg-${Date.now()}`,
      sender: "user",
      content: data.prompt,
      createdAt: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    };

    setMessages((prev) => ({
      ...prev,
      [selectedTaskId]: [...(prev[selectedTaskId] || []), userMsg],
    }));

    setIsExecuting(true);

    // Simulate agent response with streaming action box
    setTimeout(() => {
      const agentMsg: ChatMessage = {
        id: `msg-${Date.now() + 1}`,
        sender: "agent",
        agentName: data.targetAgent || "Người điều phối",
        content: `Đã tiếp nhận yêu cầu: "${data.prompt}". Em đang phối hợp cùng các tác tử thực thi và chuẩn bị sản phẩm đầu ra theo định dạng ${data.format || "mặc định"}.`,
        createdAt: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        actions: [
          {
            id: `act-${Date.now()}`,
            title: `Phân tích yêu cầu qua mô hình ${data.model || "GPT-6 Luna"}`,
            durationMs: 76,
            status: "completed",
            detail: `Target: ${data.targetAgent || "Commander"} | Team: ${data.team || "Tổng bộ"}`,
          },
          {
            id: `act-${Date.now() + 1}`,
            title: "Khởi tạo dòng công việc và gán chuyên viên",
            durationMs: 140,
            status: "completed",
            detail: "Workflow nodes initialized in memory.",
          },
        ],
      };

      setMessages((prev) => ({
        ...prev,
        [selectedTaskId]: [...(prev[selectedTaskId] || []), agentMsg],
      }));
      setIsExecuting(false);
    }, 800);
  };

  const handleNewTask = () => {
    const newId = `task-${Date.now()}`;
    const newTask: ExtendedSidebarTaskItem = {
      id: newId,
      title: "Nhiệm vụ mới vừa tạo",
      status: "queued",
      group: "today",
      agentId: "Người điều phối",
    };

    setTasks((prev) => [newTask, ...prev]);
    setSelectedTaskId(newId);
    setTaskDetails((prev) => ({
      ...prev,
      [newId]: {
        id: newId,
        title: "Nhiệm vụ mới vừa tạo",
        description: "Nhập mục tiêu vào Omnibar để Người điều phối bắt đầu chia việc...",
        currentStage: "in_progress",
        workflow: [
          { step: 1, agentName: "Người điều phối", role: "Tiếp nhận & Lập kế hoạch", status: "in_progress" },
        ],
        deliverables: [],
        files: [],
        browserPages: [],
      },
    }));
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-slate-950 text-slate-100 font-sans">
      {/* ================= COLUMN 1: SIDEBAR (260px) ================= */}
      <SidebarNav
        tasks={tasks}
        selectedTaskId={selectedTaskId}
        onSelectTask={(id) => setSelectedTaskId(id)}
        onNewTask={handleNewTask}
        className="w-64 shrink-0 border-r border-slate-800"
      />

      {/* ================= COLUMN 2: CHAT FEED & OMNIBAR (Flex-1) ================= */}
      <main className="flex-1 min-w-0 flex flex-col h-full bg-slate-900 border-r border-slate-800 relative">
        {/* Column 2 Header Bar */}
        <header className="h-14 px-5 border-b border-slate-800 bg-slate-950/70 backdrop-blur-md flex items-center justify-between shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            <AgentChibiAvatar agentId={activeTask.agentId || "Người điều phối"} size="md" />
            <div className="min-w-0">
              <h2 className="text-sm font-bold text-slate-100 truncate flex items-center gap-2">
                <span>{activeTask.title}</span>
                {activeTask.status === "running" && (
                  <span className="px-2 py-0.5 rounded text-[10px] bg-indigo-500/20 text-indigo-400 border border-indigo-500/40 font-mono flex items-center gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-pulse" />
                    Đang chạy
                  </span>
                )}
                {activeTask.status === "completed" && (
                  <span className="px-2 py-0.5 rounded text-[10px] bg-emerald-500/20 text-emerald-400 border border-emerald-500/40 font-mono">
                    Hoàn tất
                  </span>
                )}
              </h2>
              <p className="text-[11px] text-slate-400 truncate">
                Tác tử chỉ huy: <span className="text-indigo-300 font-semibold">{activeTask.agentId || "Người điều phối"}</span>
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3 shrink-0">
            {/* Backend connection pill */}
            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-slate-900 border border-slate-800 text-[11px] text-slate-300">
              {backendOnline === false ? (
                <>
                  <WifiOff className="w-3.5 h-3.5 text-red-400" />
                  <span className="text-red-400 font-medium">Backend Offline</span>
                </>
              ) : (
                <>
                  <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                  <span className="text-slate-300">Backend 8765 Sẵn sàng</span>
                </>
              )}
            </div>
          </div>
        </header>

        {/* Column 2 Message Scroll Area */}
        <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-4">
          {currentMessages.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-center text-slate-500 space-y-3">
              <div className="w-12 h-12 rounded-2xl bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 flex items-center justify-center shadow-lg">
                <Sparkles className="w-6 h-6" />
              </div>
              <div className="space-y-1">
                <h3 className="font-bold text-slate-200 text-sm">Chưa có hội thoại nào</h3>
                <p className="text-xs max-w-sm text-slate-400">
                  Gõ mục tiêu vào khung lệnh bên dưới. Người điều phối sẽ phân tích và giao việc cho đúng Agent.
                </p>
              </div>
            </div>
          ) : (
            currentMessages.map((msg) => {
              const isUser = msg.sender === "user";

              return (
                <div
                  key={msg.id}
                  className={`flex gap-3 max-w-3xl ${isUser ? "ml-auto justify-end" : "mr-auto justify-start"}`}
                >
                  {!isUser && (
                    <div className="shrink-0 mt-0.5">
                      <AgentChibiAvatar agentId={msg.agentName || "Người điều phối"} size="md" />
                    </div>
                  )}

                  <div className={`space-y-2.5 max-w-[85%] ${isUser ? "items-end" : "items-start"}`}>
                    {/* Message Bubble */}
                    <div
                      className={`p-3.5 rounded-2xl text-xs md:text-sm leading-relaxed shadow-md ${
                        isUser
                          ? "bg-indigo-600 text-white rounded-tr-xs"
                          : "bg-slate-800/90 border border-slate-700/80 text-slate-200 rounded-tl-xs"
                      }`}
                    >
                      {!isUser && (
                        <div className="text-[11px] font-bold text-indigo-300 mb-1 flex items-center gap-1.5">
                          <span>{msg.agentName || "Người điều phối"}</span>
                          <span className="text-slate-400 font-normal text-[10px]">• {msg.createdAt}</span>
                        </div>
                      )}
                      <p className="whitespace-pre-wrap">{msg.content}</p>
                    </div>

                    {/* Action Collapse Box if present */}
                    {msg.actions && msg.actions.length > 0 && (
                      <ActionCollapseBox actions={msg.actions} isRunning={false} />
                    )}

                    {/* Human Decision Card if present */}
                    {msg.showDecisionCard && msg.decisionData && (
                      <HumanDecisionCard
                        title={msg.decisionData.title}
                        description={msg.decisionData.description}
                        estimatedCredits={msg.decisionData.credits}
                        onApprove={() => alert("Đã phê duyệt tiếp tục!")}
                        onModify={() => alert("Chỉnh sửa yêu cầu")}
                      />
                    )}
                  </div>
                </div>
              );
            })
          )}

          {/* Streaming spinner if executing */}
          {isExecuting && (
            <div className="flex items-center gap-2 text-xs text-indigo-400 animate-pulse pl-10">
              <RotateCw className="w-3.5 h-3.5 animate-spin" />
              <span>Người điều phối đang chỉ huy tác tử xử lý...</span>
            </div>
          )}

          <div ref={chatBottomRef} />
        </div>

        {/* Column 2 Bottom Fixed Omnibar */}
        <div className="p-3 md:p-4 bg-slate-950/80 border-t border-slate-800/80 backdrop-blur-md">
          <CommanderOmnibar
            onSubmit={handleOmnibarSubmit}
            isStreaming={isExecuting}
            onStop={() => setIsExecuting(false)}
          />
        </div>
      </main>

      {/* ================= COLUMN 3: TASK DETAILS PANEL (420-460px) ================= */}
      <aside className="w-96 lg:w-[440px] shrink-0 h-full hidden md:block">
        <TaskDetailsPanel task={activeTaskDetails} />
      </aside>
    </div>
  );
}
