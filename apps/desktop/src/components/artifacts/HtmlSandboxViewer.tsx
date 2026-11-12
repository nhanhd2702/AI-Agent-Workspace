"use client";

import React, { useState } from "react";
import {
  Monitor,
  Smartphone,
  ExternalLink,
  AlertTriangle,
  ShieldCheck,
  ChevronDown,
  ChevronUp,
} from "lucide-react";

export interface HtmlSandboxViewerProps {
  html: string;
  title?: string;
  warnings?: string[];
  externalUrl?: string;
  onOpenExternal?: () => void;
  onExternalOpen?: () => void;
  className?: string;
}

export function HtmlSandboxViewer({
  html,
  title = "index.html",
  warnings = [],
  externalUrl,
  onOpenExternal,
  onExternalOpen,
  className = "",
}: HtmlSandboxViewerProps) {
  const [viewport, setViewport] = useState<"desktop" | "mobile">("desktop");
  const [isWarningsOpen, setIsWarningsOpen] = useState(true);

  const handleExternalOpen = () => {
    // 1. If an external opener callback is provided (e.g. Tauri shell plugin), invoke it
    const openCallback = onOpenExternal || onExternalOpen;
    if (openCallback) {
      openCallback();
      return;
    }

    // 2. If an explicit sandboxed URL endpoint is provided, open that
    if (externalUrl && typeof window !== "undefined") {
      window.open(externalUrl, "_blank", "noopener,noreferrer");
      return;
    }

    // 3. Browser fallback: NEVER open unsandboxed text/html blob: URLs via window.open!
    // That would inherit the parent desktop app origin without iframe sandbox restrictions.
    // Instead, safely trigger a download so the user can open it offline in their OS browser.
    if (typeof window !== "undefined") {
      try {
        const blob = new Blob([html], { type: "text/html;charset=utf-8" });
        const blobUrl = URL.createObjectURL(blob);
        const safeFilename = title.endsWith(".html") || title.endsWith(".htm") ? title : `${title}.html`;

        const link = document.createElement("a");
        link.href = blobUrl;
        link.download = safeFilename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);

        // Revoke Object URL to prevent memory leaks
        setTimeout(() => {
          URL.revokeObjectURL(blobUrl);
        }, 1000);
      } catch (err) {
        console.error("Failed to trigger artifact download:", err);
      }
    }
  };

  return (
    <div
      className={`flex flex-col h-full w-full bg-slate-950 border border-slate-800 rounded-xl overflow-hidden ${className}`}
      data-testid="html-sandbox-viewer"
    >
      {/* Top Toolbar */}
      <div className="flex items-center justify-between px-4 py-2 bg-slate-900 border-b border-slate-800 text-slate-200 text-sm">
        <div className="flex items-center gap-2">
          <ShieldCheck className="w-4 h-4 text-emerald-400" />
          <span className="font-medium text-slate-300 truncate max-w-[200px] sm:max-w-xs">
            {title}
          </span>
          <span className="text-[11px] bg-slate-800 text-slate-400 px-2 py-0.5 rounded-full border border-slate-700">
            Offline Sandbox
          </span>
        </div>

        {/* Viewport Toggles and Actions */}
        <div className="flex items-center gap-2">
          <div className="flex items-center bg-slate-800 p-0.5 rounded-lg border border-slate-700">
            <button
              type="button"
              onClick={() => setViewport("desktop")}
              className={`flex items-center gap-1 px-2.5 py-1 text-xs rounded-md font-medium transition-colors ${
                viewport === "desktop"
                  ? "bg-slate-700 text-white shadow-xs"
                  : "text-slate-400 hover:text-slate-200"
              }`}
              aria-label="Desktop (100%)"
              title="Khung nhìn Desktop (100%)"
            >
              <Monitor className="w-3.5 h-3.5" />
              <span>Desktop (100%)</span>
            </button>
            <button
              type="button"
              onClick={() => setViewport("mobile")}
              className={`flex items-center gap-1 px-2.5 py-1 text-xs rounded-md font-medium transition-colors ${
                viewport === "mobile"
                  ? "bg-slate-700 text-white shadow-xs"
                  : "text-slate-400 hover:text-slate-200"
              }`}
              aria-label="Mobile (390px)"
              title="Khung nhìn Mobile (390px)"
            >
              <Smartphone className="w-3.5 h-3.5" />
              <span>Mobile (390px)</span>
            </button>
          </div>

          <button
            type="button"
            onClick={handleExternalOpen}
            className="flex items-center gap-1.5 px-3 py-1 bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium rounded-lg transition-colors shadow-xs"
            aria-label="Mở bằng trình duyệt ngoài"
            title="Mở toàn màn hình bằng trình duyệt ngoài"
          >
            <ExternalLink className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Mở bằng trình duyệt</span>
          </button>
        </div>
      </div>

      {/* Offline Warnings Banner */}
      {warnings && warnings.length > 0 && (
        <div className="bg-amber-950/40 border-b border-amber-800/60 text-amber-200 px-4 py-2 text-xs">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 font-medium">
              <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />
              <span>
                {warnings.length} cảnh báo tài nguyên ngoài đã được làm sạch để xem offline an toàn:
              </span>
            </div>
            <button
              type="button"
              onClick={() => setIsWarningsOpen(!isWarningsOpen)}
              className="p-1 hover:bg-amber-900/40 rounded transition-colors text-amber-300"
              aria-label="Thu gọn cảnh báo"
            >
              {isWarningsOpen ? (
                <ChevronUp className="w-3.5 h-3.5" />
              ) : (
                <ChevronDown className="w-3.5 h-3.5" />
              )}
            </button>
          </div>

          {isWarningsOpen && (
            <ul className="mt-1.5 list-disc list-inside space-y-0.5 text-amber-300/90 pl-1">
              {warnings.map((w, index) => (
                <li key={index} className="truncate">
                  {w}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Main Viewport Container */}
      <div className="flex-1 bg-slate-900/50 p-3 sm:p-4 overflow-auto flex justify-center items-center">
        <div
          data-testid="sandbox-viewport-container"
          className={`h-full transition-all duration-300 ease-in-out ${
            viewport === "mobile"
              ? "w-full max-w-[390px] rounded-2xl shadow-2xl border-4 border-slate-700 overflow-hidden bg-white"
              : "w-full rounded-lg overflow-hidden bg-white shadow-md border border-slate-800"
          }`}
        >
          <iframe
            title={title}
            srcDoc={html}
            sandbox="allow-scripts allow-forms"
            className="w-full h-full border-0 bg-white"
          />
        </div>
      </div>
    </div>
  );
}
