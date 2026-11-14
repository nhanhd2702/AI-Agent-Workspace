"use client";

import React from "react";
import { Coins, Clock, AlertTriangle, CheckCircle2, Bot } from "lucide-react";
import { AgentChibiAvatar } from "../layout/SidebarNav";

export interface OfficeKpiRibbonProps {
  tokenCount?: string;
  runningCount?: number;
  waitingReviewCount?: number;
  completedCount?: number;
  commanderBrief?: string;
  className?: string;
}

export function OfficeKpiRibbon({
  tokenCount = "561K",
  runningCount = 2,
  waitingReviewCount = 1,
  completedCount = 8,
  commanderBrief = "Chào anh! Đội Content đang viết 2 kịch bản, 1 việc đang chờ anh duyệt.",
  className = "",
}: OfficeKpiRibbonProps) {
  return (
    <div className={`space-y-2.5 ${className}`}>
      {/* 4 KPI Metric Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 text-xs">
        {/* Metric 1: Token hôm nay */}
        <div className="p-3 rounded-xl bg-slate-900/90 border border-slate-800 flex items-center justify-between">
          <div>
            <p className="text-[11px] font-medium text-slate-400">Token hôm nay</p>
            <p className="text-base font-bold text-slate-100 font-mono mt-0.5">{tokenCount}</p>
          </div>
          <div className="w-8 h-8 rounded-lg bg-indigo-500/15 border border-indigo-500/30 text-indigo-400 flex items-center justify-center shrink-0">
            <Coins className="w-4 h-4" />
          </div>
        </div>

        {/* Metric 2: Đang làm */}
        <div className="p-3 rounded-xl bg-slate-900/90 border border-slate-800 flex items-center justify-between">
          <div>
            <p className="text-[11px] font-medium text-slate-400">Đang làm</p>
            <p className="text-base font-bold text-indigo-400 font-mono mt-0.5">{runningCount}</p>
          </div>
          <div className="w-8 h-8 rounded-lg bg-indigo-500/15 border border-indigo-500/30 text-indigo-400 flex items-center justify-center shrink-0">
            <Clock className="w-4 h-4 animate-pulse" />
          </div>
        </div>

        {/* Metric 3: Chờ anh (Highlighted Alert Badge) */}
        <div className="p-3 rounded-xl bg-slate-900/90 border border-amber-500/40 flex items-center justify-between shadow-sm shadow-amber-500/5">
          <div>
            <p className="text-[11px] font-semibold text-amber-300">Chờ anh</p>
            <div
              data-testid="kpi-waiting-badge"
              className="inline-flex items-center px-2 py-0.5 mt-0.5 rounded-full text-xs font-bold font-mono bg-amber-500/20 text-amber-300 border border-amber-400/40"
            >
              {waitingReviewCount}
            </div>
          </div>
          <div className="w-8 h-8 rounded-lg bg-amber-500/15 border border-amber-500/30 text-amber-400 flex items-center justify-center shrink-0">
            <AlertTriangle className="w-4 h-4" />
          </div>
        </div>

        {/* Metric 4: Việc xong hôm nay */}
        <div className="p-3 rounded-xl bg-slate-900/90 border border-slate-800 flex items-center justify-between">
          <div>
            <p className="text-[11px] font-medium text-slate-400">Việc xong hôm nay</p>
            <p className="text-base font-bold text-emerald-400 font-mono mt-0.5">{completedCount}</p>
          </div>
          <div className="w-8 h-8 rounded-lg bg-emerald-500/15 border border-emerald-500/30 text-emerald-400 flex items-center justify-center shrink-0">
            <CheckCircle2 className="w-4 h-4" />
          </div>
        </div>
      </div>

      {/* Commander Speech Bubble Bar */}
      {commanderBrief && (
        <div className="flex items-center gap-3 p-2.5 rounded-xl bg-slate-900/80 border border-slate-800/90 backdrop-blur-sm text-xs text-slate-200">
          <AgentChibiAvatar agentId="Người điều phối" size="sm" />
          <div className="flex-1 min-w-0">
            <span className="font-semibold text-indigo-300 mr-1.5">Người điều phối:</span>
            <span className="text-slate-300">{commanderBrief}</span>
          </div>
        </div>
      )}
    </div>
  );
}
