"use client";

import React, { useState } from "react";
import Link from "next/link";
import {
  Search,
  Plus,
  Building2,
  Clock,
  FolderClosed,
  Brain,
  MessageCircle,
  Settings,
  BookOpen,
  SunMoon,
  Folder,
  Circle,
  CheckCircle2,
  AlertCircle,
  Loader2,
} from "lucide-react";
import { SidebarTaskItem, TimeGroup } from "@/lib/types";

export interface ExtendedSidebarTaskItem extends SidebarTaskItem {
  agentId?: string;
  hasUnread?: boolean;
}

export interface SidebarNavProps {
  tasks?: ExtendedSidebarTaskItem[];
  selectedTaskId?: string;
  activeNav?: string;
  officeBadge?: number;
  brainBadge?: number;
  onNewTask?: () => void;
  onSelectTask?: (id: string) => void;
  onNavigate?: (navId: string) => void;
  className?: string;
}

// 5 Standard Menu Items according to Tako specifications
export const TAKO_PRIMARY_NAV = [
  { id: "office", label: "Văn phòng AI", href: "/office", icon: Building2 },
  { id: "auto", label: "Tự động", href: "/board", icon: Clock },
  { id: "library", label: "Thư viện", href: "/library", icon: FolderClosed },
  { id: "brain", label: "Brain", href: "/brain", icon: Brain },
  { id: "inbox", label: "Hội thoại khách", href: "/inbox", icon: MessageCircle },
];

const TIME_GROUP_CONFIG: { key: TimeGroup; label: string }[] = [
  { key: "today", label: "Hôm nay" },
  { key: "yesterday", label: "Hôm qua" },
  { key: "past7days", label: "7 ngày qua" },
];

// Helper to render distinct Chibi Agent Avatars
export function AgentChibiAvatar({ agentId, size = "md" }: { agentId?: string; size?: "sm" | "md" }) {
  const norm = (agentId || "").toLowerCase();
  const dim = size === "sm" ? "w-5 h-5 text-[10px]" : "w-6 h-6 text-xs";

  if (norm.includes("research") || norm.includes("tím")) {
    // DeepResearcher: Purple with glasses
    return (
      <div
        className={`${dim} rounded-full bg-purple-500/20 border border-purple-400/40 text-purple-600 flex items-center justify-center font-bold shrink-0 shadow-xs`}
        title={agentId || "DeepResearcher"}
      >
        <span className="scale-90 font-mono">👓</span>
      </div>
    );
  }

  if (norm.includes("writer") || norm.includes("content") || norm.includes("xanh lá")) {
    // ContentWriter: Green with bag
    return (
      <div
        className={`${dim} rounded-full bg-emerald-500/20 border border-emerald-400/40 text-emerald-600 flex items-center justify-center font-bold shrink-0 shadow-xs`}
        title={agentId || "ContentWriter"}
      >
        <span className="scale-90 font-mono">🎒</span>
      </div>
    );
  }

  if (norm.includes("ui") || norm.includes("design") || norm.includes("đỏ")) {
    // UIDesigner: Red bean with beanie
    return (
      <div
        className={`${dim} rounded-full bg-rose-500/20 border border-rose-400/40 text-rose-600 flex items-center justify-center font-bold shrink-0 shadow-xs`}
        title={agentId || "UIDesigner"}
      >
        <span className="scale-90 font-mono">🧶</span>
      </div>
    );
  }

  if (norm.includes("video") || norm.includes("mực")) {
    // VideoEditor: Blue octopus
    return (
      <div
        className={`${dim} rounded-full bg-blue-500/20 border border-blue-400/40 text-blue-600 flex items-center justify-center font-bold shrink-0 shadow-xs`}
        title={agentId || "VideoEditor"}
      >
        <span className="scale-90 font-mono">🐙</span>
      </div>
    );
  }

  // Default: Master Commander Blue with Headphones
  return (
    <div
      className={`${dim} rounded-full bg-indigo-500/20 border border-indigo-400/40 text-indigo-600 flex items-center justify-center font-bold shrink-0 shadow-xs`}
      title={agentId || "Người điều phối"}
    >
      <span className="scale-90 font-mono">🎧</span>
    </div>
  );
}

export function SidebarNav({
  tasks = [],
  selectedTaskId,
  activeNav,
  officeBadge = 2,
  brainBadge = 1,
  onNewTask,
  onSelectTask,
  onNavigate,
  className = "",
}: SidebarNavProps) {
  const [searchQuery, setSearchQuery] = useState("");

  // Group tasks by time bucket
  const groupedTasks: Record<TimeGroup, ExtendedSidebarTaskItem[]> = {
    today: [],
    yesterday: [],
    past7days: [],
    older: [],
  };

  const filteredTasks = searchQuery.trim()
    ? tasks.filter((t) => t.title.toLowerCase().includes(searchQuery.toLowerCase()))
    : tasks;

  for (const task of filteredTasks) {
    const groupKey = task.group || "today";
    if (groupedTasks[groupKey]) {
      groupedTasks[groupKey].push(task);
    } else {
      groupedTasks.today.push(task);
    }
  }

  const renderStatusDot = (status?: string) => {
    switch (status) {
      case "running":
        return <span className="w-2 h-2 rounded-full bg-blue-500 shrink-0 animate-pulse" title="Đang chạy" />;
      case "done":
      case "completed":
        return <span className="w-2 h-2 rounded-full bg-emerald-500 shrink-0" title="Hoàn tất" />;
      case "awaiting_review":
      case "waiting_review":
        return <span className="w-2 h-2 rounded-full bg-amber-500 shrink-0" title="Chờ anh duyệt" />;
      case "failed":
      case "error":
        return <span className="w-2 h-2 rounded-full bg-rose-500 shrink-0" title="Có lỗi" />;
      default:
        return <span className="w-1.5 h-1.5 rounded-full bg-slate-300 dark:bg-slate-600 shrink-0" />;
    }
  };

  return (
    <aside
      className={`w-64 bg-white dark:bg-slate-900 border-r border-slate-200 dark:border-slate-800 text-slate-700 dark:text-slate-200 flex flex-col h-full select-none shrink-0 ${className}`}
      data-testid="sidebar-nav"
    >
      {/* Search Input Bar with ⌘K */}
      <div className="p-3 pb-2">
        <div className="relative flex items-center">
          <Search className="w-4 h-4 absolute left-3 text-slate-400 pointer-events-none" />
          <input
            type="text"
            placeholder="Tìm kiếm..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-9 pr-10 py-1.5 bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700 rounded-lg text-xs placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-500 transition-all"
          />
          <kbd className="absolute right-2.5 px-1.5 py-0.5 text-[10px] font-semibold text-slate-400 bg-slate-200/60 dark:bg-slate-700/60 rounded border border-slate-300/60 dark:border-slate-600">
            ⌘K
          </kbd>
        </div>
      </div>

      {/* Prominent [+] Tạo task mới Button */}
      <div className="px-3 pb-3">
        <button
          type="button"
          onClick={onNewTask}
          aria-label="Tạo task mới"
          className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-700 active:scale-[0.98] text-white font-medium text-xs md:text-sm shadow-sm shadow-indigo-500/20 transition-all cursor-pointer focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 dark:focus:ring-offset-slate-900"
        >
          <Plus className="w-4 h-4 stroke-[2.5]" />
          <span>Tạo task mới</span>
        </button>
      </div>

      {/* 5 Standard Primary Menus */}
      <nav className="px-3 space-y-0.5">
        {TAKO_PRIMARY_NAV.map((item) => {
          const Icon = item.icon;
          const isActive = activeNav === item.id;
          const badgeCount = item.id === "office" ? officeBadge : item.id === "brain" ? brainBadge : 0;

          return (
            <Link
              key={item.id}
              href={item.href}
              onClick={() => onNavigate?.(item.id)}
              className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-xs md:text-sm font-medium transition-colors cursor-pointer ${
                isActive
                  ? "bg-indigo-50 dark:bg-indigo-950/40 text-indigo-600 dark:text-indigo-400 font-semibold"
                  : "text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100 hover:bg-slate-100/70 dark:hover:bg-slate-800/60"
              }`}
            >
              <div className="flex items-center gap-2.5 truncate">
                <Icon className={`w-4 h-4 shrink-0 ${isActive ? "text-indigo-600 dark:text-indigo-400" : "text-slate-400"}`} />
                <span className="truncate">{item.label}</span>
              </div>
              {badgeCount > 0 && (
                <span
                  className={`px-1.5 py-0.2 rounded-full text-[11px] font-bold ${
                    item.id === "office"
                      ? "bg-amber-100 text-amber-700 dark:bg-amber-950/60 dark:text-amber-400"
                      : "bg-indigo-100 text-indigo-700 dark:bg-indigo-950/60 dark:text-indigo-400"
                  }`}
                >
                  {badgeCount}
                </span>
              )}
            </Link>
          );
        })}
      </nav>

      {/* Divider */}
      <div className="my-2 border-t border-slate-100 dark:border-slate-800/80 mx-3" />

      {/* Scrollable middle area: PROJECTS & TASKS */}
      <div className="flex-1 overflow-y-auto px-3 space-y-4 text-xs">
        {/* PROJECTS */}
        <div>
          <div className="flex items-center justify-between text-[11px] font-semibold text-slate-400 uppercase tracking-wider px-2 mb-1">
            <span>PROJECTS</span>
            <button
              type="button"
              className="hover:text-indigo-600 dark:hover:text-indigo-400 p-0.5 rounded cursor-pointer"
              title="Thêm Project"
            >
              <Plus className="w-3.5 h-3.5" />
            </button>
          </div>
          <div className="space-y-0.5">
            <div className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800/50 cursor-pointer">
              <Folder className="w-3.5 h-3.5 text-slate-400" />
              <span className="truncate">Solopreneur Marketing</span>
            </div>
          </div>
        </div>

        {/* TASKS LIST WITH CHIBI AVATARS */}
        <div>
          <div className="flex items-center gap-1.5 text-[11px] font-semibold text-slate-400 uppercase tracking-wider px-2 mb-2">
            <span>TASKS</span>
            <span className="w-1.5 h-1.5 rounded-full bg-rose-500" />
          </div>

          <div className="space-y-3">
            {TIME_GROUP_CONFIG.map(({ key, label }) => {
              const groupList = groupedTasks[key];
              if (!groupList || groupList.length === 0) return null;

              return (
                <div key={key} className="space-y-1">
                  <span className="text-[10px] font-medium text-slate-400 px-2 block">
                    {label}
                  </span>
                  <div className="space-y-0.5">
                    {groupList.map((task) => {
                      const isSelected = selectedTaskId === task.id;
                      return (
                        <button
                          key={task.id}
                          type="button"
                          onClick={() => onSelectTask?.(task.id)}
                          className={`w-full flex items-center justify-between gap-2 px-2 py-1.5 rounded-lg text-left transition-colors cursor-pointer group ${
                            isSelected
                              ? "bg-indigo-50/80 dark:bg-indigo-950/40 text-indigo-700 dark:text-indigo-300 font-medium"
                              : "text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100 hover:bg-slate-100/70 dark:hover:bg-slate-800/50"
                          }`}
                        >
                          <div className="flex items-center gap-2 truncate">
                            <AgentChibiAvatar agentId={task.agentId} size="sm" />
                            <span className="truncate text-xs leading-snug">{task.title}</span>
                          </div>
                          {renderStatusDot(task.status)}
                        </button>
                      );
                    })}
                  </div>
                </div>
              );
            })}

            {filteredTasks.length === 0 && (
              <p className="text-[11px] text-slate-400 italic px-2">Chưa có tác vụ nào</p>
            )}
          </div>
        </div>
      </div>

      {/* Footer Utilities: Settings, Docs, Theme */}
      <div className="p-3 border-t border-slate-100 dark:border-slate-800/80 flex items-center justify-between text-xs text-slate-500">
        <Link
          href="/settings"
          onClick={() => onNavigate?.("settings")}
          className="flex items-center gap-2 px-2 py-1 rounded-lg hover:text-slate-900 dark:hover:text-slate-100 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors cursor-pointer"
        >
          <Settings className="w-4 h-4 text-slate-400" />
          <span>Cài đặt</span>
        </Link>
        <div className="flex items-center gap-1">
          <button
            type="button"
            className="p-1.5 rounded-lg hover:text-slate-900 dark:hover:text-slate-100 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-400 cursor-pointer"
            title="Tài liệu hướng dẫn"
          >
            <BookOpen className="w-4 h-4" />
          </button>
          <button
            type="button"
            className="p-1.5 rounded-lg hover:text-slate-900 dark:hover:text-slate-100 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-400 cursor-pointer"
            title="Đổi giao diện Sáng / Tối"
          >
            <SunMoon className="w-4 h-4" />
          </button>
        </div>
      </div>
    </aside>
  );
}
