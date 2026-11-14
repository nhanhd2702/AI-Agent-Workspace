"use client";

import React, { useState } from "react";
import {
  FileText,
  Globe,
  Briefcase,
  CheckCircle2,
  Clock,
  ArrowRight,
  ExternalLink,
  Download,
  Eye,
  X,
  Play,
  Layers,
  Sparkles,
  FileCode,
} from "lucide-react";
import { AgentChibiAvatar } from "../layout/SidebarNav";
import { HtmlSandboxViewer } from "../artifacts/HtmlSandboxViewer";

export type TaskStage = "in_progress" | "delivered" | "waiting_human" | "approved" | "published";

export interface WorkflowStep {
  step: number;
  agentName: string;
  role: string;
  status: "pending" | "in_progress" | "completed";
}

export interface DeliverableItem {
  id: string;
  name: string;
  type: "html" | "markdown" | "video" | "image";
  size: string;
  content: string;
}

export interface TaskFileItem {
  name: string;
  size: string;
  uploadedAt: string;
}

export interface BrowserPageItem {
  id: string;
  title: string;
  url: string;
}

export interface TaskDetailsData {
  id: string;
  title: string;
  description?: string;
  currentStage: TaskStage;
  workflow: WorkflowStep[];
  deliverables: DeliverableItem[];
  files: TaskFileItem[];
  browserPages: BrowserPageItem[];
}

export interface TaskDetailsPanelProps {
  task?: TaskDetailsData;
  className?: string;
}

const STAGES: { key: TaskStage; label: string }[] = [
  { key: "in_progress", label: "Đang làm" },
  { key: "delivered", label: "Đã bàn giao" },
  { key: "waiting_human", label: "Chờ anh" },
  { key: "approved", label: "Đã duyệt" },
  { key: "published", label: "Đã đăng" },
];

export function TaskDetailsPanel({
  task,
  className = "",
}: TaskDetailsPanelProps) {
  const [activeTab, setActiveTab] = useState<"task" | "files" | "browser">("task");
  const [previewDeliverable, setPreviewDeliverable] = useState<DeliverableItem | null>(null);

  if (!task) {
    return (
      <div className={`w-full h-full bg-slate-900 border-l border-slate-800 p-6 flex flex-col items-center justify-center text-slate-500 text-xs text-center ${className}`}>
        <Briefcase className="w-10 h-10 mb-2 text-slate-700" />
        <p>Chọn một task để xem dòng công việc và kết quả bàn giao</p>
      </div>
    );
  }

  const currentStageIndex = STAGES.findIndex((s) => s.key === task.currentStage);

  return (
    <div className={`w-full h-full bg-slate-900 border-l border-slate-800 flex flex-col overflow-hidden text-xs text-slate-200 ${className}`}>
      {/* 3 Top Tabs: Việc, Tệp (N), Trình duyệt (M) */}
      <div className="flex items-center border-b border-slate-800 bg-slate-950/70 px-3 pt-2 gap-2" role="tablist">
        <button
          role="tab"
          aria-selected={activeTab === "task"}
          onClick={() => setActiveTab("task")}
          className={`pb-2.5 px-3 font-semibold transition-all border-b-2 flex items-center gap-1.5 ${
            activeTab === "task"
              ? "border-indigo-500 text-indigo-400"
              : "border-transparent text-slate-400 hover:text-slate-200"
          }`}
        >
          <Briefcase className="w-3.5 h-3.5" />
          <span>Việc</span>
        </button>

        <button
          role="tab"
          aria-selected={activeTab === "files"}
          onClick={() => setActiveTab("files")}
          className={`pb-2.5 px-3 font-semibold transition-all border-b-2 flex items-center gap-1.5 ${
            activeTab === "files"
              ? "border-indigo-500 text-indigo-400"
              : "border-transparent text-slate-400 hover:text-slate-200"
          }`}
        >
          <FileText className="w-3.5 h-3.5" />
          <span>Tệp ({task.files?.length || 0})</span>
        </button>

        <button
          role="tab"
          aria-selected={activeTab === "browser"}
          onClick={() => setActiveTab("browser")}
          className={`pb-2.5 px-3 font-semibold transition-all border-b-2 flex items-center gap-1.5 ${
            activeTab === "browser"
              ? "border-indigo-500 text-indigo-400"
              : "border-transparent text-slate-400 hover:text-slate-200"
          }`}
        >
          <Globe className="w-3.5 h-3.5" />
          <span>Trình duyệt ({task.browserPages?.length || 0})</span>
        </button>
      </div>

      {/* Main Tab Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-5">
        {/* TAB 1: VIỆC */}
        {activeTab === "task" && (
          <>
            {/* 5-Stage Progress Ribbon */}
            <div className="rounded-xl bg-slate-950/80 border border-slate-800 p-3 space-y-2">
              <div className="flex items-center justify-between text-[11px] font-medium text-slate-400 mb-1">
                <span>Tiến trình hoàn thiện</span>
                <span className="text-indigo-400 font-semibold">{STAGES[Math.max(0, currentStageIndex)]?.label}</span>
              </div>
              <div className="flex items-center justify-between gap-1 overflow-x-auto no-scrollbar py-1">
                {STAGES.map((stg, idx) => {
                  const isCurrent = idx === currentStageIndex;
                  const isPassed = idx < currentStageIndex;

                  return (
                    <div key={stg.key} className="flex items-center gap-1.5 shrink-0">
                      <div
                        className={`flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium transition-all ${
                          isCurrent
                            ? "bg-indigo-600 text-white shadow-sm shadow-indigo-600/30 ring-1 ring-indigo-400"
                            : isPassed
                            ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30"
                            : "bg-slate-900 text-slate-500 border border-slate-800"
                        }`}
                      >
                        {isPassed ? (
                          <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                        ) : isCurrent ? (
                          <span className="w-1.5 h-1.5 rounded-full bg-white animate-pulse" />
                        ) : (
                          <span className="w-1.5 h-1.5 rounded-full bg-slate-600" />
                        )}
                        <span>{stg.label}</span>
                      </div>
                      {idx < STAGES.length - 1 && (
                        <ArrowRight className="w-3 h-3 text-slate-700 shrink-0" />
                      )}
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Task Info */}
            <div className="space-y-1">
              <h3 className="font-bold text-sm text-slate-100">{task.title}</h3>
              {task.description && (
                <p className="text-slate-400 text-xs leading-relaxed">{task.description}</p>
              )}
            </div>

            {/* DÒNG CÔNG VIỆC (Workflow Pipeline) */}
            <div className="space-y-2">
              <div className="flex items-center justify-between text-[11px] font-bold uppercase tracking-wider text-slate-400">
                <span className="flex items-center gap-1.5">
                  <Layers className="w-3.5 h-3.5 text-indigo-400" />
                  <span>DÒNG CÔNG VIỆC</span>
                </span>
                <span className="text-[10px] text-slate-500 font-normal">
                  {task.workflow.length} tác tử phụ trách
                </span>
              </div>

              <div className="space-y-1.5">
                {task.workflow.map((item) => (
                  <div
                    key={item.step}
                    className="flex items-center justify-between p-2.5 rounded-xl bg-slate-950/60 border border-slate-800/80 hover:border-slate-700 transition-colors"
                  >
                    <div className="flex items-center gap-2.5">
                      <div className="w-5 h-5 rounded-md bg-indigo-500/10 text-indigo-400 font-mono text-[11px] font-bold flex items-center justify-center border border-indigo-500/20">
                        {item.step}
                      </div>
                      <AgentChibiAvatar agentId={item.agentName} size="sm" />
                      <div>
                        <div className="font-semibold text-slate-200 text-xs">{item.agentName}</div>
                        <div className="text-[10px] text-slate-400">{item.role}</div>
                      </div>
                    </div>

                    <div className="flex items-center gap-1">
                      {item.status === "completed" && (
                        <span className="px-2 py-0.5 rounded text-[10px] bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                          Hoàn thành
                        </span>
                      )}
                      {item.status === "in_progress" && (
                        <span className="px-2 py-0.5 rounded text-[10px] bg-indigo-500/15 text-indigo-400 border border-indigo-500/30 animate-pulse">
                          Đang làm
                        </span>
                      )}
                      {item.status === "pending" && (
                        <span className="px-2 py-0.5 rounded text-[10px] bg-slate-800 text-slate-500 border border-slate-700/50">
                          Chờ lượt
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* BÀN GIAO (Deliverables) */}
            <div className="space-y-2 pt-2 border-t border-slate-800/80">
              <div className="flex items-center justify-between text-[11px] font-bold uppercase tracking-wider text-slate-400">
                <span className="flex items-center gap-1.5">
                  <Sparkles className="w-3.5 h-3.5 text-amber-400" />
                  <span>BÀN GIAO</span>
                </span>
                <span className="text-[10px] text-slate-500 font-normal">
                  {task.deliverables.length} sản phẩm
                </span>
              </div>

              <div className="space-y-2">
                {task.deliverables.map((del) => (
                  <div
                    key={del.id}
                    className="p-3 rounded-xl bg-slate-950/60 border border-slate-800 hover:border-slate-700 transition-all space-y-2"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2 min-w-0">
                        {del.type === "html" ? (
                          <FileCode className="w-4 h-4 text-indigo-400 shrink-0" />
                        ) : (
                          <FileText className="w-4 h-4 text-emerald-400 shrink-0" />
                        )}
                        <span className="font-medium text-slate-200 truncate text-xs">{del.name}</span>
                      </div>
                      <span className="font-mono text-[10px] text-slate-500 bg-slate-900 px-1.5 py-0.5 rounded border border-slate-800">
                        {del.size}
                      </span>
                    </div>

                    <div className="flex items-center justify-between pt-1 border-t border-slate-800/60">
                      <span className="text-[10px] text-slate-400 uppercase tracking-wider font-semibold">
                        {del.type === "html" ? "Interactive HTML" : "Markdown Doc"}
                      </span>
                      <button
                        type="button"
                        aria-label="Mở"
                        onClick={() => setPreviewDeliverable(del)}
                        className="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-medium text-xs transition-all"
                      >
                        <Eye className="w-3.5 h-3.5" />
                        <span>Mở</span>
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </>
        )}

        {/* TAB 2: TỆP (N) */}
        {activeTab === "files" && (
          <div className="space-y-2">
            <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400 mb-2">
              Tệp tài liệu đính kèm & xuất ra ({task.files.length})
            </div>
            {task.files.map((file, idx) => (
              <div
                key={idx}
                className="flex items-center justify-between p-2.5 rounded-xl bg-slate-950/60 border border-slate-800 hover:border-slate-700 transition-colors"
              >
                <div className="flex items-center gap-2 min-w-0">
                  <FileText className="w-4 h-4 text-indigo-400 shrink-0" />
                  <div>
                    <p className="font-medium text-slate-200 truncate text-xs">{file.name}</p>
                    <p className="text-[10px] text-slate-500">{file.size} • {file.uploadedAt}</p>
                  </div>
                </div>

                <button
                  type="button"
                  title="Tải về"
                  className="p-1.5 rounded-lg text-slate-400 hover:text-slate-100 hover:bg-slate-800 transition-colors"
                >
                  <Download className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        )}

        {/* TAB 3: TRÌNH DUYỆT (M) */}
        {activeTab === "browser" && (
          <div className="space-y-2">
            <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400 mb-2">
              Các tab trình duyệt kết nối ({task.browserPages.length})
            </div>
            {task.browserPages.map((page) => (
              <div
                key={page.id}
                className="p-3 rounded-xl bg-slate-950/60 border border-slate-800 hover:border-slate-700 transition-colors space-y-1.5"
              >
                <div className="flex items-center justify-between">
                  <span className="font-semibold text-xs text-indigo-300">{page.title}</span>
                  <ExternalLink className="w-3.5 h-3.5 text-slate-400" />
                </div>
                <p className="font-mono text-[10px] text-slate-400 truncate bg-slate-900 p-1.5 rounded border border-slate-800">
                  {page.url}
                </p>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Preview Modal for Deliverables */}
      {previewDeliverable && (
        <div
          data-testid="html-sandbox-preview"
          className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4"
        >
          <div className="w-full max-w-4xl h-[85vh] bg-slate-900 border border-slate-700 rounded-2xl shadow-2xl flex flex-col overflow-hidden">
            {/* Modal Header */}
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

            {/* Modal Content Preview */}
            <div className="flex-1 overflow-hidden p-2">
              {previewDeliverable.type === "html" ? (
                <HtmlSandboxViewer
                  html={previewDeliverable.content}
                  title={previewDeliverable.name}
                  className="h-full border-0"
                />
              ) : (
                <pre className="h-full overflow-auto p-4 text-xs font-mono text-slate-200 bg-slate-950 rounded-xl">
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
