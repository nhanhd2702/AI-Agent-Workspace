"use client";

import React from "react";
import {
  X,
  Play,
  Settings,
  Sparkles,
  Bot,
  Brain,
  Cpu,
  Layers,
  CheckCircle2,
  Clock,
  ArrowRight,
} from "lucide-react";
import { AgentVisual } from "./Office3DCanvas";
import { AgentChibiAvatar } from "../layout/SidebarNav";

export interface AgentDetailModalProps {
  agent: AgentVisual;
  onClose: () => void;
  onUseAgent?: (agent: AgentVisual) => void;
  onConfigure?: (agent: AgentVisual) => void;
}

export function AgentDetailModal({
  agent,
  onClose,
  onUseAgent,
  onConfigure,
}: AgentDetailModalProps) {
  const isWorking = agent.status === "working";

  return (
    <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4 animate-in fade-in duration-150">
      <div className="w-full max-w-lg bg-slate-900 border border-slate-700/80 rounded-2xl shadow-2xl overflow-hidden flex flex-col text-slate-100">
        {/* Header Bar */}
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-slate-800 bg-slate-950/70">
          <div className="flex items-center gap-2.5">
            <AgentChibiAvatar agentId={agent.name} size="md" />
            <div>
              <div className="flex items-center gap-2">
                <h3 className="font-bold text-sm text-slate-100">{agent.name}</h3>
                <span className="px-2 py-0.5 rounded text-[10px] bg-indigo-500/15 text-indigo-300 border border-indigo-500/30 font-medium">
                  {agent.department}
                </span>
              </div>
              <p className="text-xs text-slate-400 font-medium">{agent.displayName}</p>
            </div>
          </div>

          <button
            type="button"
            aria-label="Đóng"
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-5 space-y-4 text-xs">
          {/* Status & Thought Banner */}
          <div className="p-3 rounded-xl bg-slate-950/60 border border-slate-800 space-y-1.5">
            <div className="flex items-center justify-between text-[11px]">
              <span className="text-slate-400 font-medium flex items-center gap-1.5">
                <Clock className="w-3.5 h-3.5 text-indigo-400" />
                <span>Trạng thái hoạt động</span>
              </span>
              {isWorking ? (
                <span className="px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/40 font-semibold flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  Đang làm việc
                </span>
              ) : (
                <span className="px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-slate-700 font-medium">
                  Đang nghỉ ngơi
                </span>
              )}
            </div>

            <p className="text-slate-200 text-xs italic bg-slate-900/80 p-2.5 rounded-lg border border-slate-800/80">
              "{agent.thought}"
            </p>
          </div>

          {/* Role Specification */}
          <div className="space-y-1">
            <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
              <Bot className="w-3.5 h-3.5 text-indigo-400" />
              <span>Chuyên môn đảm nhiệm</span>
            </div>
            <p className="text-slate-200 leading-relaxed bg-slate-950/40 p-2.5 rounded-lg border border-slate-800/60">
              {agent.role}
            </p>
          </div>

          {/* AI Model In Use */}
          <div className="flex items-center justify-between p-2.5 rounded-lg bg-slate-950/40 border border-slate-800/60">
            <span className="text-slate-400 font-medium flex items-center gap-1.5">
              <Cpu className="w-3.5 h-3.5 text-indigo-400" />
              <span>Mô hình mặc định:</span>
            </span>
            <span className="px-2.5 py-1 rounded-md bg-indigo-500/10 text-indigo-300 font-mono text-[11px] font-semibold border border-indigo-500/20">
              {agent.model}
            </span>
          </div>

          {/* Skills List */}
          <div className="space-y-1.5">
            <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
              <Layers className="w-3.5 h-3.5 text-amber-400" />
              <span>Kỹ năng chuyên môn ({agent.skills?.length || 0})</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {agent.skills?.map((sk, idx) => (
                <span
                  key={idx}
                  className="px-2.5 py-1 rounded-lg bg-slate-800 border border-slate-700/80 text-slate-300 text-xs font-medium"
                >
                  {sk}
                </span>
              ))}
            </div>
          </div>
        </div>

        {/* Modal Footer Actions */}
        <div className="flex items-center justify-end gap-2.5 px-5 py-3.5 border-t border-slate-800 bg-slate-950/80">
          <button
            type="button"
            onClick={() => {
              if (onConfigure) onConfigure(agent);
            }}
            className="flex items-center gap-1.5 px-3 py-2 rounded-xl border border-slate-700 bg-slate-800 hover:bg-slate-700 text-slate-300 font-medium text-xs transition-colors"
          >
            <Settings className="w-3.5 h-3.5" />
            <span>Cấu hình agent</span>
          </button>

          <button
            type="button"
            onClick={() => {
              if (onUseAgent) onUseAgent(agent);
            }}
            className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-semibold text-xs shadow-md shadow-indigo-600/30 transition-all hover:scale-[1.02] active:scale-[0.98]"
          >
            <Play className="w-3.5 h-3.5 fill-current" />
            <span>Dùng agent này</span>
          </button>
        </div>
      </div>
    </div>
  );
}
