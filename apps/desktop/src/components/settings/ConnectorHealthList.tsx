"use client";

import React from "react";
import {
  Activity,
  CheckCircle2,
  AlertCircle,
  HelpCircle,
  RefreshCw,
  Video,
  Globe,
  Terminal,
  Database,
  PlaySquare,
  Send,
  MessageCircle,
  ShieldCheck,
} from "lucide-react";
import { ConnectorHealthItem } from "@/lib/types";

export interface ConnectorHealthListProps {
  connectors: ConnectorHealthItem[];
  onRefresh: () => Promise<void>;
  isLoading?: boolean;
}

export function ConnectorHealthList({
  connectors,
  onRefresh,
  isLoading = false,
}: ConnectorHealthListProps) {
  const getIconForConnector = (id: string) => {
    switch (id) {
      case "ffmpeg":
        return <Video className="w-5 h-5 text-indigo-400" />;
      case "playwright":
        return <Globe className="w-5 h-5 text-sky-400" />;
      case "shell":
        return <Terminal className="w-5 h-5 text-emerald-400" />;
      case "chromadb":
        return <Database className="w-5 h-5 text-amber-400" />;
      case "youtube":
        return <PlaySquare className="w-5 h-5 text-rose-400" />;
      case "telegram":
        return <Send className="w-5 h-5 text-cyan-400" />;
      case "zalo":
        return <MessageCircle className="w-5 h-5 text-blue-400" />;
      default:
        return <Activity className="w-5 h-5 text-gray-400" />;
    }
  };

  const getStatusBadge = (healthy: boolean, status: string) => {
    if (healthy) {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-950/80 text-emerald-400 border border-emerald-800/60 shadow-xs">
          <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
          <span>Sẵn sàng</span>
        </span>
      );
    }

    switch (status) {
      case "missing":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-rose-950/80 text-rose-400 border border-rose-800/60 shadow-xs">
            <AlertCircle className="w-3.5 h-3.5 shrink-0" />
            <span>Chưa cài đặt</span>
          </span>
        );
      case "disconnected":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-amber-950/80 text-amber-400 border border-amber-800/60 shadow-xs">
            <HelpCircle className="w-3.5 h-3.5 shrink-0" />
            <span>Chưa kết nối</span>
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-rose-950/80 text-rose-400 border border-rose-800/60 shadow-xs">
            <AlertCircle className="w-3.5 h-3.5 shrink-0" />
            <span>Lỗi</span>
          </span>
        );
    }
  };

  const healthyCount = connectors.filter((c) => c.healthy).length;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between pb-2 border-b border-gray-800">
        <div>
          <h2 className="text-base font-semibold text-white flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-emerald-400" />
            Sức Khỏe Hệ Thống & Kết Nối Ngoại Vi
          </h2>
          <p className="text-xs text-gray-400 mt-0.5">
            Trạng thái kiểm tra kết nối các công cụ & runtime ngoại vi (FFmpeg, Playwright, Shell Sandbox, ChromaDB, YouTube, Telegram, Zalo).
          </p>
        </div>

        <div className="flex items-center gap-3">
          <div className="text-xs text-gray-400">
            Đang hoạt động:{" "}
            <span className="font-semibold text-emerald-400">
              {healthyCount} / {connectors.length}
            </span>
          </div>

          <button
            type="button"
            onClick={onRefresh}
            disabled={isLoading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-gray-800 hover:bg-gray-700 text-gray-200 border border-gray-700 hover:border-gray-600 transition-colors disabled:opacity-50 cursor-pointer shadow-sm"
            aria-label="Làm mới kiểm tra kết nối"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin text-sky-400" : "text-gray-400"}`} />
            <span>{isLoading ? "Đang kiểm tra..." : "Làm mới"}</span>
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {connectors.map((item) => (
          <div
            key={item.id}
            className="p-4 rounded-xl bg-gray-900 border border-gray-800 hover:border-gray-700 transition-all flex flex-col justify-between shadow-xs"
            data-testid={`connector-card-${item.id}`}
          >
            <div>
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-3">
                  <div className="w-9 h-9 rounded-lg bg-gray-950 border border-gray-800 flex items-center justify-center">
                    {getIconForConnector(item.id)}
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold text-white">{item.name}</h3>
                    <span className="text-[11px] uppercase tracking-wider text-gray-500 font-mono">
                      {item.category}
                    </span>
                  </div>
                </div>

                <div>{getStatusBadge(item.healthy, item.status)}</div>
              </div>

              {item.message && (
                <p className="mt-3 text-xs text-gray-400 leading-relaxed bg-gray-950/60 p-2.5 rounded-lg border border-gray-800/60">
                  {item.message}
                </p>
              )}
            </div>

            <div className="mt-3 pt-2 border-t border-gray-800/60 flex items-center justify-between text-[11px] text-gray-500">
              <span>Mã định danh: <span className="font-mono text-gray-400">{item.id}</span></span>
              <span>
                {item.last_checked
                  ? new Date(item.last_checked).toLocaleTimeString("vi-VN", {
                      hour: "2-digit",
                      minute: "2-digit",
                      second: "2-digit",
                    })
                  : "Chưa kiểm tra"}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
