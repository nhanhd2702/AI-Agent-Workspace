"useclient";

import React from "react";
import {
  Plus,
  Bot,
  Zap,
  FolderClosed,
  Brain,
  MessageSquare,
  Clock,
  CheckCircle2,
  CircleDashed,
  AlertCircle,
} from "lucide-react";
import { SidebarTaskItem, TimeGroup } from "@/lib/types";

export interface SidebarNavProps {
  tasks?: SidebarTaskItem[];
  selectedTaskId?: string;
  activeNav?: string;
  onNewTask?: () => void;
  onSelectTask?: (id: string) => void;
  onNavigate?: (navId: string) => void;
  className?: string;
}

interface NavItem {
  id: string;
  label: string;
  icon: React.ElementType;
}

const PRIMARY_NAV_ITEMS: NavItem[] = [
  { id: "workspace", label: "Văn phòng AI", icon: Bot },
  { id: "automation", label: "Tự động", icon: Zap },
  { id: "library", label: "Thư viện", icon: FolderClosed },
  { id: "brain", label: "Brain", icon: Brain },
  { id: "customer_chat", label: "Hội thoại khách", icon: MessageSquare },
];

const TIME_GROUP_CONFIG: { key: TimeGroup; label: string }[] = [
  { key: "today", label: "Hôm nay" },
  { key: "yesterday", label: "Hôm qua" },
  { key: "past7days", label: "7 ngày qua" },
];

export function SidebarNav({
  tasks = [],
  selectedTaskId,
  activeNav = "workspace",
  onNewTask,
  onSelectTask,
  onNavigate,
  className = "",
}: SidebarNavProps) {
  // Group tasks by time bucket
  const groupedTasks: Record<TimeGroup, SidebarTaskItem[]> = {
    today: [],
    yesterday: [],
    past7days: [],
    older: [],
  };

  for (const task of tasks) {
    const groupKey = task.group || "today";
    if (groupedTasks[groupKey]) {
      groupedTasks[groupKey].push(task);
    } else {
      groupedTasks.today.push(task);
    }
  }

  const renderStatusIcon = (status?: string) => {
    switch (status) {
      case "completed":
        return <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 shrink-0" />;
      case "running":
        return <CircleDashed className="w-3.5 h-3.5 text-sky-500 animate-spin shrink-0" />;
      case "failed":
        return <AlertCircle className="w-3.5 h-3.5 text-rose-500 shrink-0" />;
      default:
        return <Clock className="w-3.5 h-3.5 text-gray-400 shrink-0" />;
    }
  };

  return (
    <aside
      className={`w-64 bg-gray-900 border-r border-gray-800 text-gray-200 flex flex-col h-full select-none ${className}`}
      data-testid="sidebar-nav"
    >
      {/* Brand & Workspace Title */}
      <div className="p-4 border-b border-gray-800 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-sky-600 flex items-center justify-center font-bold text-white shadow-sm">
            AI
          </div>
          <div>
            <h2 className="text-sm font-semibold tracking-wide text-white">Văn Phòng AI</h2>
            <p className="text-xs text-gray-400">Master Commander</p>
          </div>
        </div>
      </div>

      {/* Top Primary Action: Tạo task mới */}
      <div className="p-3">
        <button
          type="button"
          onClick={onNewTask}
          className="w-full flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg bg-sky-500 hover:bg-sky-600 text-white font-medium text-sm transition-colors shadow-sm focus:outline-none focus:ring-2 focus:ring-sky-400 focus:ring-offset-2 focus:ring-offset-gray-900 cursor-pointer"
          aria-label="Tạo task mới"
        >
          <Plus className="w-4 h-4" />
          <span>Tạo task mới</span>
        </button>
      </div>

      {/* Primary Navigation Items */}
      <nav className="px-3 py-2 space-y-1">
        {PRIMARY_NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const isActive = activeNav === item.id;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => onNavigate?.(item.id)}
              className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors text-left cursor-pointer ${
                isActive
                  ? "bg-gray-800 text-sky-400 font-semibold"
                  : "text-gray-400 hover:text-gray-200 hover:bg-gray-800/60"
              }`}
            >
              <Icon className="w-4 h-4" />
              <span>{item.label}</span>
            </button>
          );
        })}
      </nav>

      {/* Separator */}
      <div className="px-4 py-2">
        <div className="h-px bg-gray-800" />
      </div>

      {/* Time-grouped Task History List */}
      <div className="flex-1 overflow-y-auto px-3 py-1 space-y-4">
        {TIME_GROUP_CONFIG.map(({ key, label }) => {
          const items = groupedTasks[key];
          return (
            <div key={key} className="space-y-1">
              <div className="px-2 text-xs font-semibold uppercase tracking-wider text-gray-500">
                {label}
              </div>
              {items.length === 0 ? (
                <div className="px-2 py-1 text-xs text-gray-600 italic">Chưa có task</div>
              ) : (
                items.map((task) => {
                  const isSelected = selectedTaskId === task.id;
                  return (
                    <button
                      key={task.id}
                      type="button"
                      onClick={() => onSelectTask?.(task.id)}
                      className={`w-full flex items-center gap-2.5 px-2.5 py-1.5 rounded-md text-xs text-left truncate transition-colors cursor-pointer ${
                        isSelected
                          ? "bg-gray-800 text-sky-300 font-medium border border-sky-800/40"
                          : "text-gray-400 hover:text-gray-200 hover:bg-gray-800/50"
                      }`}
                      title={task.title}
                    >
                      {renderStatusIcon(task.status)}
                      <span className="truncate flex-1">{task.title}</span>
                    </button>
                  );
                })
              )}
            </div>
          );
        })}
      </div>

      {/* Footer Info */}
      <div className="p-3 border-t border-gray-800 text-xs text-gray-500 flex items-center justify-between">
        <span className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-emerald-500 inline-block"></span>
          <span>Hệ thống sẵn sàng</span>
        </span>
        <span className="text-[11px] font-mono text-gray-400">v1.0.0</span>
      </div>
    </aside>
  );
}
