"use client";

import React from "react";
import { AlertTriangle, Check, Edit3, Coins, ShieldCheck } from "lucide-react";

export interface HumanDecisionCardProps {
  title: string;
  description: string;
  estimatedCredits?: number;
  onApprove?: () => void;
  onModify?: () => void;
  className?: string;
}

export function HumanDecisionCard({
  title,
  description,
  estimatedCredits = 0.8,
  onApprove,
  onModify,
  className = "",
}: HumanDecisionCardProps) {
  return (
    <div
      className={`rounded-2xl border-2 border-amber-500/50 bg-gradient-to-b from-amber-500/10 via-slate-900/90 to-slate-900 p-4 shadow-xl shadow-amber-500/5 text-xs text-slate-200 space-y-3.5 backdrop-blur-md ${className}`}
    >
      {/* Title & Badge */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-xl bg-amber-500/20 border border-amber-500/40 text-amber-400 flex items-center justify-center shrink-0">
            <AlertTriangle className="w-4 h-4" />
          </div>
          <div>
            <h4 className="font-bold text-sm text-amber-200 leading-snug">{title}</h4>
            <div className="flex items-center gap-1.5 text-[11px] text-amber-400/80 mt-0.5">
              <ShieldCheck className="w-3.5 h-3.5" />
              <span>Yêu cầu phê duyệt từ Người chỉ huy (Human-in-the-Loop)</span>
            </div>
          </div>
        </div>

        {estimatedCredits > 0 && (
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-amber-500/20 border border-amber-400/30 text-amber-300 font-mono text-[11px] font-semibold shrink-0">
            <Coins className="w-3.5 h-3.5 text-amber-400" />
            <span>Ước tính: {estimatedCredits} credit</span>
          </div>
        )}
      </div>

      {/* Description */}
      <p className="text-slate-300 leading-relaxed text-xs pl-0.5 bg-slate-950/40 p-3 rounded-xl border border-slate-800">
        {description}
      </p>

      {/* Action Buttons */}
      <div className="flex flex-wrap items-center justify-end gap-2.5 pt-1">
        <button
          type="button"
          onClick={onModify}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-slate-700 bg-slate-800 hover:bg-slate-700/80 text-slate-300 hover:text-white font-medium transition-all"
        >
          <Edit3 className="w-3.5 h-3.5" />
          <span>Chỉnh sửa yêu cầu</span>
        </button>

        <button
          type="button"
          onClick={onApprove}
          className="flex items-center gap-1.5 px-4 py-1.5 rounded-xl bg-amber-500 hover:bg-amber-400 text-slate-950 font-bold shadow-md shadow-amber-500/20 transition-all hover:scale-[1.02] active:scale-[0.98]"
        >
          <Check className="w-3.5 h-3.5 stroke-[2.5]" />
          <span>Đồng ý cho chạy tiếp</span>
        </button>
      </div>
    </div>
  );
}
