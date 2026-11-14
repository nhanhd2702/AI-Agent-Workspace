"use client";

import React, { useState } from "react";
import {
  Activity,
  Sparkles,
  FileCode,
  FileText,
  Eye,
  X,
  Clock,
  CheckCircle2,
  Play,
  RotateCw,
} from "lucide-react";
import { AgentChibiAvatar } from "../layout/SidebarNav";
import { HtmlSandboxViewer } from "../artifacts/HtmlSandboxViewer";

export type ActivityActionType = "received" | "running" | "delivered" | "completed";

export interface ActivityDeliverable {
  name: string;
  type: "html" | "markdown" | "video" | "image";
  content: string;
}

export interface ActivityFeedItem {
  id: string;
  agentName: string;
  actionType: ActivityActionType;
  time: string;
  title: string;
  deliverable?: ActivityDeliverable;
}

export interface OfficeActivityFeedProps {
  activities?: ActivityFeedItem[];
  className?: string;
}

const DEFAULT_ACTIVITIES: ActivityFeedItem[] = [
  {
    id: "act-1",
    agentName: "ContentWriter",
    actionType: "delivered",
    time: "10:14",
    title: "Bàn giao kịch bản video TikTok 60s hook tài chính",
    deliverable: {
      name: "kich_ban_hook_tai_chinh.md",
      type: "markdown",
      content: "# Hook Tài Chính: Đừng để tiền đứng im!\n\n**0:00 - 0:03:** Bạn đang để 100 triệu trong ngân hàng và nghĩ mình an toàn?\n**0:03 - 0:15:** Lạm phát thực tế đang âm thầm lấy đi 8% mỗi năm...",
    },
  },
  {
    id: "act-2",
    agentName: "UIDesigner",
    actionType: "running",
    time: "10:12",
    title: "Đang dựng cấu trúc interactive HTML landing page",
  },
  {
    id: "act-3",
    agentName: "HookMaster",
    actionType: "completed",
    time: "10:05",
    title: "Hoàn tất 3 góc độ mở đầu video triệu view",
  },
  {
    id: "act-4",
    agentName: "FunnelsAgent",
    actionType: "received",
    time: "09:48",
    title: "Tiếp nhận mục tiêu: Thiết kế phễu bán hàng Solopreneur",
  },
];

export function OfficeActivityFeed({
  activities = DEFAULT_ACTIVITIES,
  className = "",
}: OfficeActivityFeedProps) {
  const [previewDeliverable, setPreviewDeliverable] = useState<ActivityDeliverable | null>(null);

  const getBadge = (type: ActivityActionType) => {
    switch (type) {
      case "received":
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-sky-500/15 text-sky-400 border border-sky-500/30">
            Nhận việc
          </span>
        );
      case "running":
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-indigo-500/15 text-indigo-400 border border-indigo-500/30 flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-pulse" />
            Đang chạy
          </span>
        );
      case "delivered":
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-500/15 text-amber-300 border border-amber-500/30">
            Bàn giao
          </span>
        );
      case "completed":
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
            Xong
          </span>
        );
    }
  };

  return (
    <div className={`w-full h-full bg-slate-900 border-l border-slate-800 flex flex-col overflow-hidden text-xs text-slate-200 ${className}`}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800 bg-slate-950/70">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-indigo-400" />
          <h3 className="font-bold text-sm text-slate-100">Vừa làm gì</h3>
        </div>
        <span className="text-[10px] text-slate-500 font-mono">Thời gian thực</span>
      </div>

      {/* Activity Item List */}
      <div className="flex-1 overflow-y-auto p-3 space-y-2.5">
        {activities.map((act) => (
          <div
            key={act.id}
            className="p-3 rounded-xl bg-slate-950/60 border border-slate-800 hover:border-slate-700 transition-colors space-y-2"
          >
            {/* Top row: Agent & Badge & Time */}
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 min-w-0">
                <AgentChibiAvatar agentId={act.agentName} size="sm" />
                <span className="font-semibold text-slate-200 truncate">{act.agentName}</span>
                {getBadge(act.actionType)}
              </div>
              <span className="text-[10px] font-mono text-slate-500 shrink-0">{act.time}</span>
            </div>

            {/* Title / Description */}
            <p className="text-slate-300 text-xs leading-relaxed">{act.title}</p>

            {/* Deliverable snippet if available */}
            {act.deliverable && (
              <div className="flex items-center justify-between p-2 rounded-lg bg-slate-900 border border-slate-800 text-[11px]">
                <div className="flex items-center gap-1.5 min-w-0">
                  {act.deliverable.type === "html" ? (
                    <FileCode className="w-3.5 h-3.5 text-indigo-400 shrink-0" />
                  ) : (
                    <FileText className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                  )}
                  <span className="font-mono text-slate-300 truncate">{act.deliverable.name}</span>
                </div>

                <button
                  type="button"
                  aria-label="Mở"
                  onClick={() => setPreviewDeliverable(act.deliverable || null)}
                  className="flex items-center gap-1 px-2 py-0.5 rounded bg-indigo-600 hover:bg-indigo-500 text-white font-medium text-[10px] transition-colors"
                >
                  <Eye className="w-3 h-3" />
                  <span>Mở</span>
                </button>
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Preview Modal for Deliverable */}
      {previewDeliverable && (
        <div
          data-testid="activity-deliverable-modal"
          className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4 animate-in fade-in duration-100"
        >
          <div className="w-full max-w-3xl h-[80vh] bg-slate-900 border border-slate-700 rounded-2xl shadow-2xl flex flex-col overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800 bg-slate-950">
              <div className="flex items-center gap-2">
                <FileCode className="w-4 h-4 text-indigo-400" />
                <span className="font-bold text-sm text-slate-200">{previewDeliverable.name}</span>
              </div>
              <button
                type="button"
                onClick={() => setPreviewDeliverable(null)}
                className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="flex-1 overflow-hidden p-2">
              {previewDeliverable.type === "html" ? (
                <HtmlSandboxViewer
                  html={previewDeliverable.content}
                  title={previewDeliverable.name}
                  className="h-full border-0"
                />
              ) : (
                <pre className="h-full overflow-auto p-4 text-xs font-mono text-slate-200 bg-slate-950 rounded-xl whitespace-pre-wrap">
                  {previewDeliverable.content}
                </pre>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
