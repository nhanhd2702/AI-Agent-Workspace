"use client";

import React, { useState, useEffect, useCallback, useRef } from "react";
import {
  Activity,
  Coins,
  DollarSign,
  TrendingUp,
  Download,
  RefreshCw,
  Cpu,
  Bot,
  CheckCircle2,
  XCircle,
  Clock,
  AlertTriangle,
} from "lucide-react";
import { MonitoringDashboardData } from "@/lib/types";
import { defaultApiClient } from "@/lib/apiClient";

export type MonitoringPeriod = "today" | "7d" | "30d" | "all";

export interface UsageDashboardProps {
  initialData?: MonitoringDashboardData;
  onPeriodChange?: (period: MonitoringPeriod) => void;
  onExportCsv?: () => void;
}

export function UsageDashboard({
  initialData,
  onPeriodChange,
  onExportCsv,
}: UsageDashboardProps) {
  const [period, setPeriod] = useState<MonitoringPeriod>(
    (initialData?.period as MonitoringPeriod) || "7d"
  );
  const [data, setData] = useState<MonitoringDashboardData | null>(initialData || null);
  const [isLoading, setIsLoading] = useState<boolean>(!initialData);
  const [error, setError] = useState<string | null>(null);
  const [isExporting, setIsExporting] = useState<boolean>(false);
  const [autoRefresh, setAutoRefresh] = useState<boolean>(false);

  const fetchDashboard = useCallback(
    async (selectedPeriod: MonitoringPeriod) => {
      setIsLoading(true);
      setError(null);
      try {
        const res = await defaultApiClient.getMonitoringDashboard(selectedPeriod);
        setData(res);
      } catch (err: any) {
        setError(err?.message || "Không thể tải số liệu giám sát hệ thống.");
      } finally {
        setIsLoading(false);
      }
    },
    []
  );

  useEffect(() => {
    if (!initialData) {
      fetchDashboard(period);
    } else {
      setData(initialData);
    }
  }, [initialData, period, fetchDashboard]);

  // Handle Auto-Refresh interval (30 seconds)
  useEffect(() => {
    if (!autoRefresh) return;

    const timer = setInterval(() => {
      fetchDashboard(period);
    }, 30000);

    return () => clearInterval(timer);
  }, [autoRefresh, period, fetchDashboard]);

  const handleSelectPeriod = (newPeriod: MonitoringPeriod) => {
    setPeriod(newPeriod);
    if (onPeriodChange) {
      onPeriodChange(newPeriod);
    }
    fetchDashboard(newPeriod);
  };

  const handleExport = async () => {
    if (onExportCsv) {
      onExportCsv();
      return;
    }
    setIsExporting(true);
    try {
      const blob = await defaultApiClient.exportMonitoringCsv(period);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `usage_export_${period}.csv`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (err: any) {
      setError(err?.message || "Xuất tệp CSV thất bại.");
    } finally {
      setIsExporting(false);
    }
  };

  // Safe metrics fallbacks
  const totalTokens = data?.total_tokens ?? 0;
  const totalCostUsd = data?.total_cost_usd ?? 0;
  const totalRequests = data?.total_requests ?? 0;
  const taskStats = data?.task_stats ?? {
    total: 0,
    completed: 0,
    failed: 0,
    in_progress: 0,
    success_rate_pct: 0,
  };
  const byAgent = data?.by_agent ?? [];
  const byModel = data?.by_model ?? [];
  const quota = data?.quota;

  return (
    <div className="space-y-6">
      {/* Header with Period Filters and Actions */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-gray-800">
        <div>
          <h2 className="text-base font-semibold text-white flex items-center gap-2">
            <Activity className="w-4 h-4 text-sky-400" />
            Giám Sát & Chi Phí Token (Monitoring)
          </h2>
          <p className="text-xs text-gray-400 mt-0.5">
            Theo dõi chi phí LLM thực tế, số lượng token tiêu thụ và hiệu suất tác vụ của toàn bộ văn phòng AI.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {/* Period selector buttons */}
          <div className="flex items-center bg-gray-950 p-1 rounded-lg border border-gray-800 text-xs">
            <button
              type="button"
              onClick={() => handleSelectPeriod("today")}
              className={`px-3 py-1 rounded-md transition-colors font-medium cursor-pointer ${
                period === "today"
                  ? "bg-sky-600 text-white font-semibold"
                  : "text-gray-400 hover:text-gray-200"
              }`}
            >
              Hôm nay
            </button>
            <button
              type="button"
              onClick={() => handleSelectPeriod("7d")}
              className={`px-3 py-1 rounded-md transition-colors font-medium cursor-pointer ${
                period === "7d"
                  ? "bg-sky-600 text-white font-semibold"
                  : "text-gray-400 hover:text-gray-200"
              }`}
            >
              7 ngày qua
            </button>
            <button
              type="button"
              onClick={() => handleSelectPeriod("30d")}
              className={`px-3 py-1 rounded-md transition-colors font-medium cursor-pointer ${
                period === "30d"
                  ? "bg-sky-600 text-white font-semibold"
                  : "text-gray-400 hover:text-gray-200"
              }`}
            >
              30 ngày qua
            </button>
            <button
              type="button"
              onClick={() => handleSelectPeriod("all")}
              className={`px-3 py-1 rounded-md transition-colors font-medium cursor-pointer ${
                period === "all"
                  ? "bg-sky-600 text-white font-semibold"
                  : "text-gray-400 hover:text-gray-200"
              }`}
            >
              Tất cả
            </button>
          </div>

          {/* Export CSV Button */}
          <button
            type="button"
            onClick={handleExport}
            disabled={isExporting}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-800 hover:bg-gray-700 text-gray-200 text-xs font-medium rounded-lg border border-gray-700 transition-colors cursor-pointer disabled:opacity-50"
          >
            <Download className="w-3.5 h-3.5 text-sky-400" />
            <span>{isExporting ? "Đang xuất..." : "Xuất CSV"}</span>
          </button>

          {/* 30s Auto Refresh Toggle */}
          <label className="flex items-center gap-1.5 text-xs text-gray-400 cursor-pointer select-none">
            <input
              type="checkbox"
              aria-label="Tự động làm mới"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              className="rounded border-gray-700 bg-gray-900 text-sky-500 focus:ring-0 focus:ring-offset-0 cursor-pointer"
            />
            <span className="flex items-center gap-1">
              <RefreshCw className={`w-3 h-3 ${autoRefresh ? "animate-spin text-sky-400" : ""}`} />
              Tự động làm mới (30s)
            </span>
          </label>
        </div>
      </div>

      {/* Quota Guard Alert Banner */}
      {quota && (quota.warning_triggered || quota.exceeded) && (
        <div
          className={`p-3.5 rounded-xl border flex items-center gap-3 text-xs ${
            quota.exceeded
              ? "bg-rose-950/70 border-rose-800 text-rose-200"
              : "bg-amber-950/70 border-amber-800 text-amber-200"
          }`}
        >
          <AlertTriangle className="w-4 h-4 shrink-0 text-amber-400" />
          <div className="flex-1">
            <span className="font-semibold">
              {quota.exceeded ? "Cảnh báo vượt hạn mức: " : "Cảnh báo hạn mức hàng ngày: "}
            </span>
            Đã chi tiêu ${(quota.spent_today_usd ?? 0).toFixed(3)} / ${(quota.daily_limit_usd ?? 0).toFixed(2)} USD (
            {(quota.utilization_pct ?? quota.percentage_used ?? 0).toFixed(1)}%).
          </div>
        </div>
      )}

      {/* Error Banner */}
      {error && (
        <div className="p-3 rounded-xl bg-rose-950/60 border border-rose-800/80 text-rose-300 text-xs flex items-center gap-2">
          <XCircle className="w-4 h-4 text-rose-400 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* KPI Summary Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Card 1: Total Tokens */}
        <div className="p-4 rounded-xl bg-gray-900 border border-gray-800 flex flex-col justify-between">
          <div className="flex items-center justify-between text-gray-400 mb-2">
            <span className="text-xs font-medium">Tổng Token</span>
            <div className="p-1.5 rounded-lg bg-sky-950/80 text-sky-400 border border-sky-800/50">
              <Coins className="w-4 h-4" />
            </div>
          </div>
          <div>
            <div className="text-xl font-bold text-white tracking-tight">
              {totalTokens.toLocaleString()}
            </div>
            <div className="text-[11px] text-gray-400 mt-1 flex items-center gap-1.5">
              <span>Prompt: {(data?.prompt_tokens ?? 0).toLocaleString()}</span>
              <span>•</span>
              <span>Output: {(data?.completion_tokens ?? 0).toLocaleString()}</span>
            </div>
          </div>
        </div>

        {/* Card 2: Total Cost USD */}
        <div className="p-4 rounded-xl bg-gray-900 border border-gray-800 flex flex-col justify-between">
          <div className="flex items-center justify-between text-gray-400 mb-2">
            <span className="text-xs font-medium">Chi Phí Ước Tính</span>
            <div className="p-1.5 rounded-lg bg-emerald-950/80 text-emerald-400 border border-emerald-800/50">
              <DollarSign className="w-4 h-4" />
            </div>
          </div>
          <div>
            <div className="text-xl font-bold text-white tracking-tight">
              ${totalCostUsd < 0.01 && totalCostUsd > 0 ? totalCostUsd.toFixed(4) : totalCostUsd.toFixed(3)}
            </div>
            <div className="text-[11px] text-gray-400 mt-1">
              Trung bình: ${(totalRequests > 0 ? totalCostUsd / totalRequests : 0).toFixed(4)} / request
            </div>
          </div>
        </div>

        {/* Card 3: Total Requests */}
        <div className="p-4 rounded-xl bg-gray-900 border border-gray-800 flex flex-col justify-between">
          <div className="flex items-center justify-between text-gray-400 mb-2">
            <span className="text-xs font-medium">Lượt Gọi LLM (Requests)</span>
            <div className="p-1.5 rounded-lg bg-indigo-950/80 text-indigo-400 border border-indigo-800/50">
              <TrendingUp className="w-4 h-4" />
            </div>
          </div>
          <div>
            <div className="text-xl font-bold text-white tracking-tight">
              {totalRequests}
            </div>
            <div className="text-[11px] text-gray-400 mt-1">
              {data?.daily_trends && data.daily_trends.length > 0
                ? `${(totalRequests / Math.max(1, data.daily_trends.length)).toFixed(1)} calls / ngày`
                : "Hoạt động ghi nhận"}
            </div>
          </div>
        </div>

        {/* Card 4: Task Success Rate */}
        <div className="p-4 rounded-xl bg-gray-900 border border-gray-800 flex flex-col justify-between">
          <div className="flex items-center justify-between text-gray-400 mb-2">
            <span className="text-xs font-medium">Tỉ Lệ Thành Công Tác Vụ</span>
            <div className="p-1.5 rounded-lg bg-teal-950/80 text-teal-400 border border-teal-800/50">
              <CheckCircle2 className="w-4 h-4" />
            </div>
          </div>
          <div>
            <div className="text-xl font-bold text-white tracking-tight">
              {taskStats.success_rate_pct.toFixed(1)}%
            </div>
            <div className="text-[11px] text-gray-400 mt-1">
              {taskStats.completed} / {taskStats.total} hoàn thành
            </div>
          </div>
        </div>
      </div>

      {/* Task Execution Breakdown Card */}
      <div className="p-5 rounded-xl bg-gray-900 border border-gray-800">
        <h3 className="text-xs font-semibold text-gray-300 uppercase tracking-wider mb-4 flex items-center gap-2">
          <Clock className="w-3.5 h-3.5 text-sky-400" />
          <span>Thống Kê Tiến Độ Tác Vụ (Task Execution Stats)</span>
        </h3>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <div className="p-3 rounded-lg bg-gray-950 border border-gray-800">
            <div className="text-xs text-gray-400">Tổng tác vụ</div>
            <div className="text-lg font-bold text-white mt-1">{taskStats.total}</div>
          </div>
          <div className="p-3 rounded-lg bg-emerald-950/30 border border-emerald-900/40">
            <div className="text-xs text-emerald-400">Hoàn thành</div>
            <div className="text-lg font-bold text-emerald-300 mt-1">{taskStats.completed}</div>
          </div>
          <div className="p-3 rounded-lg bg-rose-950/30 border border-rose-900/40">
            <div className="text-xs text-rose-400">Thất bại</div>
            <div className="text-lg font-bold text-rose-300 mt-1">{taskStats.failed}</div>
          </div>
          <div className="p-3 rounded-lg bg-sky-950/30 border border-sky-900/40">
            <div className="text-xs text-sky-400">Đang xử lý</div>
            <div className="text-lg font-bold text-sky-300 mt-1">{taskStats.in_progress}</div>
          </div>
        </div>
      </div>

      {/* Two Column Layout: Agent Breakdown vs Model Breakdown */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Column 1: Agent Usage Breakdown */}
        <div className="p-5 rounded-xl bg-gray-900 border border-gray-800 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-semibold text-gray-300 uppercase tracking-wider flex items-center gap-2">
              <Bot className="w-3.5 h-3.5 text-sky-400" />
              <span>Phân Bổ Chi Phí Theo Agent</span>
            </h3>
            <span className="text-[11px] text-gray-500">{byAgent.length} nhân sự</span>
          </div>

          {byAgent.length === 0 ? (
            <div className="py-8 text-center text-xs text-gray-500">
              Chưa có dữ liệu tiêu thụ token của Agent trong giai đoạn này.
            </div>
          ) : (
            <div className="space-y-3">
              {byAgent.map((agent) => {
                const pct = agent.percentage ?? 0;
                return (
                  <div key={agent.agent_id} className="p-3 rounded-lg bg-gray-950 border border-gray-800/80 space-y-2">
                    <div className="flex items-center justify-between text-xs">
                      <span className="font-medium text-white truncate max-w-[200px]">
                        {agent.agent_name}
                      </span>
                      <div className="flex items-center gap-3">
                        <span className="text-gray-400">{(agent.tokens ?? agent.total_tokens ?? 0).toLocaleString()} tks</span>
                        <span className="font-semibold text-emerald-400">${agent.cost_usd.toFixed(4)}</span>
                      </div>
                    </div>
                    {/* Visual Progress Bar */}
                    <div className="w-full bg-gray-800 rounded-full h-1.5 overflow-hidden">
                      <div
                        className="bg-sky-500 h-1.5 rounded-full transition-all"
                        style={{ width: `${Math.min(100, Math.max(2, pct))}%` }}
                      />
                    </div>
                    <div className="flex justify-between items-center text-[10px] text-gray-500">
                      <span>{agent.requests} lượt gọi</span>
                      <span>{pct.toFixed(1)}% chi phí</span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Column 2: Model Usage Breakdown */}
        <div className="p-5 rounded-xl bg-gray-900 border border-gray-800 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-semibold text-gray-300 uppercase tracking-wider flex items-center gap-2">
              <Cpu className="w-3.5 h-3.5 text-indigo-400" />
              <span>Phân Bổ Theo Mô Hình LLM</span>
            </h3>
            <span className="text-[11px] text-gray-500">{byModel.length} mô hình</span>
          </div>

          {byModel.length === 0 ? (
            <div className="py-8 text-center text-xs text-gray-500">
              Chưa có dữ liệu tiêu thụ theo mô hình trong giai đoạn này.
            </div>
          ) : (
            <div className="space-y-3">
              {byModel.map((model) => (
                <div
                  key={model.model_name}
                  className="p-3 rounded-lg bg-gray-950 border border-gray-800/80 flex items-center justify-between text-xs"
                >
                  <div className="flex flex-col">
                    <span className="font-medium text-white font-mono">{model.model_name}</span>
                    <span className="text-[11px] text-gray-500 mt-0.5">
                      {model.requests} requests • {(model.tokens ?? model.total_tokens ?? 0).toLocaleString()} tokens
                    </span>
                  </div>
                  <div className="text-right">
                    <div className="font-semibold text-emerald-400">${model.cost_usd.toFixed(4)}</div>
                    <div className="text-[10px] text-gray-500">
                      ${(model.requests > 0 ? model.cost_usd / model.requests : 0).toFixed(4)} / req
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
