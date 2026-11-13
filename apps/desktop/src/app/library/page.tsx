"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  Archive,
  CheckCircle2,
  Clock,
  Code,
  Download,
  FileCode,
  FileText,
  Film,
  FolderClosed,
  HardDrive,
  Image as ImageIcon,
  Loader2,
  Music,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { SidebarNav } from "@/components/layout/SidebarNav";
import { ApiClient } from "@/lib/apiClient";
import type { FileItem, FileStorageSummary, SidebarTaskItem } from "@/lib/types";

type CategoryTab = "all" | "image" | "video" | "document" | "code";

const CATEGORY_TABS: { key: CategoryTab; label: string; icon: React.ElementType }[] = [
  { key: "all", label: "Tất cả", icon: FolderClosed },
  { key: "image", label: "Hình ảnh", icon: ImageIcon },
  { key: "video", label: "Video & Media", icon: Film },
  { key: "document", label: "Tài liệu", icon: FileText },
  { key: "code", label: "Code & HTML", icon: Code },
];

function formatBytes(bytes: number): string {
  if (bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  const val = bytes / Math.pow(1024, i);
  return `${val.toFixed(val < 10 && i > 0 ? 1 : 0)} ${units[i]}`;
}

function formatDate(dateStr?: string | null): string {
  if (!dateStr) return "N/A";
  try {
    const d = new Date(dateStr);
    return d.toLocaleString("vi-VN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return dateStr;
  }
}

function getFileIcon(type: string) {
  switch (type) {
    case "image":
      return <ImageIcon className="w-5 h-5 text-sky-400 shrink-0" />;
    case "video":
      return <Film className="w-5 h-5 text-purple-400 shrink-0" />;
    case "audio":
      return <Music className="w-5 h-5 text-indigo-400 shrink-0" />;
    case "document":
      return <FileText className="w-5 h-5 text-amber-400 shrink-0" />;
    case "code":
    case "html":
      return <FileCode className="w-5 h-5 text-emerald-400 shrink-0" />;
    default:
      return <FolderClosed className="w-5 h-5 text-gray-400 shrink-0" />;
  }
}

export default function LibraryPage() {
  const [apiClient] = useState(() => new ApiClient());
  const [activeTab, setActiveTab] = useState<CategoryTab>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [files, setFiles] = useState<FileItem[]>([]);
  const [selectedFileIds, setSelectedFileIds] = useState<Set<string>>(new Set());
  const [storage, setStorage] = useState<FileStorageSummary>({
    used_bytes: 0,
    max_bytes: 5 * 1024 * 1024 * 1024,
    percentage: 0,
    used_mb: 0,
    max_gb: 5.0,
  });
  const [isLoading, setIsLoading] = useState(true);
  const [errorBanner, setErrorBanner] = useState<string | null>(null);
  const [successBanner, setSuccessBanner] = useState<string | null>(null);

  // Modals & Actions
  const [showCleanupModal, setShowCleanupModal] = useState(false);
  const [isCleaning, setIsCleaning] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [isUploading, setIsUploading] = useState(false);

  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const loadData = useCallback(async () => {
    setIsLoading(true);
    setErrorBanner(null);
    try {
      const [storageData, filesData] = await Promise.all([
        apiClient.getStorageSummary(),
        apiClient.listFiles(),
      ]);
      setStorage(storageData);
      setFiles(filesData || []);
    } catch (err) {
      setErrorBanner(
        err instanceof Error ? err.message : "Không thể tải dữ liệu Thư viện."
      );
    } finally {
      setIsLoading(false);
    }
  }, [apiClient]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Filtered files
  const filteredFiles = useMemo(() => {
    return files.filter((file) => {
      // Tab filter
      if (activeTab === "image" && file.file_type !== "image") return false;
      if (
        activeTab === "video" &&
        file.file_type !== "video" &&
        file.file_type !== "audio" &&
        file.file_type !== "media"
      )
        return false;
      if (
        activeTab === "document" &&
        file.file_type !== "document" &&
        file.file_type !== "text"
      )
        return false;
      if (
        activeTab === "code" &&
        file.file_type !== "code" &&
        file.file_type !== "html"
      )
        return false;

      // Search filter
      if (searchQuery.trim()) {
        const query = searchQuery.toLowerCase();
        const matchesName = file.name.toLowerCase().includes(query);
        const matchesProject = file.project_id?.toLowerCase().includes(query);
        if (!matchesName && !matchesProject) return false;
      }

      return true;
    });
  }, [files, activeTab, searchQuery]);

  // Selection handlers
  const toggleSelectAll = () => {
    if (selectedFileIds.size === filteredFiles.length && filteredFiles.length > 0) {
      setSelectedFileIds(new Set());
    } else {
      setSelectedFileIds(new Set(filteredFiles.map((f) => f.id)));
    }
  };

  const toggleSelectFile = (id: string) => {
    const next = new Set(selectedFileIds);
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
    }
    setSelectedFileIds(next);
  };

  // Upload handler
  const handleUploadClick = () => {
    if (fileInputRef.current) {
      fileInputRef.current.click();
    }
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files;
    if (!selected || selected.length === 0) return;

    setIsUploading(true);
    setErrorBanner(null);
    setSuccessBanner(null);

    try {
      for (let i = 0; i < selected.length; i++) {
        await apiClient.uploadFile(selected[i]);
      }
      setSuccessBanner(`Đã tải lên ${selected.length} tệp thành công!`);
      await loadData();
    } catch (err) {
      setErrorBanner(
        err instanceof Error ? err.message : "Tải lên tệp không thành công."
      );
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  // Batch ZIP Export
  const handleExportZip = async () => {
    if (selectedFileIds.size === 0) return;

    setIsExporting(true);
    setErrorBanner(null);
    try {
      const ids = Array.from(selectedFileIds);
      const blob = await apiClient.exportFilesZip(ids);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `bundle_${new Date().toISOString().slice(0, 10)}.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
      setSuccessBanner(`Đã xuất ZIP ${ids.length} tệp thành công!`);
    } catch (err) {
      setErrorBanner(
        err instanceof Error ? err.message : "Xuất file ZIP thất bại."
      );
    } finally {
      setIsExporting(false);
    }
  };

  // Delete single file
  const handleDeleteFile = async (id: string, name: string) => {
    if (!window.confirm(`Bạn có chắc chắn muốn xóa tệp "${name}"?`)) return;

    try {
      await apiClient.deleteFile(id);
      setSelectedFileIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
      setFiles((prev) => prev.filter((f) => f.id !== id));
      setSuccessBanner(`Đã xóa "${name}" thành công.`);
      // Reload storage stats
      const st = await apiClient.getStorageSummary();
      setStorage(st);
    } catch (err) {
      setErrorBanner(
        err instanceof Error ? err.message : "Xóa tệp không thành công."
      );
    }
  };

  // Temp files cleanup
  const handleConfirmCleanup = async () => {
    setIsCleaning(true);
    setErrorBanner(null);
    try {
      const res = await apiClient.cleanupTempFiles(7);
      setShowCleanupModal(false);
      setSuccessBanner(
        `Đã dọn dẹp ${res.cleaned_files} tệp tạm (giải phóng ${formatBytes(res.freed_bytes)}).`
      );
      await loadData();
    } catch (err) {
      setErrorBanner(
        err instanceof Error ? err.message : "Dọn dẹp tệp tạm thất bại."
      );
    } finally {
      setIsCleaning(false);
    }
  };

  return (
    <div className="flex h-screen bg-gray-950 text-gray-100 overflow-hidden font-sans">
      {/* Hidden File Input */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        className="hidden"
        onChange={handleFileChange}
      />

      {/* Sidebar Navigation */}
      <SidebarNav
        activeNav="library"
        onNavigate={(navId) => {
          if (typeof window !== "undefined") {
            if (navId === "workspace" || navId === "office") window.location.assign("/office");
            else if (navId === "board") window.location.assign("/board");
            else if (navId === "brain") window.location.assign("/brain");
            else if (navId === "customer_chat" || navId === "inbox") window.location.assign("/inbox");
            else if (navId === "settings") window.location.assign("/settings");
          }
        }}
      />

      {/* Main Viewport */}
      <main className="flex-1 flex flex-col h-full overflow-hidden bg-gray-950">
        {/* Header Bar */}
        <header className="h-16 border-b border-gray-800 px-6 flex items-center justify-between shrink-0 bg-gray-900/60 backdrop-blur-sm">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-sky-950/80 border border-sky-800/60 text-sky-400">
              <FolderClosed className="w-5 h-5" />
            </div>
            <div>
              <h1 className="text-base font-semibold tracking-wide text-white">
                Thư viện tệp (File Library)
              </h1>
              <p className="text-xs text-gray-400">
                Lưu trữ thành phẩm, phân loại thông minh và quản lý dung lượng
              </p>
            </div>
          </div>

          {/* Action Buttons */}
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setShowCleanupModal(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-gray-800 hover:bg-gray-750 text-gray-200 border border-gray-700 text-xs font-medium transition cursor-pointer"
            >
              <RefreshCw className="w-3.5 h-3.5 text-amber-400" />
              <span>Dọn dẹp tệp tạm</span>
            </button>

            <button
              type="button"
              disabled={selectedFileIds.size === 0 || isExporting}
              onClick={handleExportZip}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition cursor-pointer ${
                selectedFileIds.size > 0 && !isExporting
                  ? "bg-purple-950/80 hover:bg-purple-900 border-purple-700 text-purple-200 shadow-sm"
                  : "bg-gray-900 border-gray-800 text-gray-500 cursor-not-allowed"
              }`}
            >
              {isExporting ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Archive className="w-3.5 h-3.5 text-purple-400" />
              )}
              <span>Xuất ZIP ({selectedFileIds.size})</span>
            </button>

            <button
              type="button"
              disabled={isUploading}
              onClick={handleUploadClick}
              className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-sky-500 hover:bg-sky-600 text-white text-xs font-medium shadow-sm transition cursor-pointer"
            >
              {isUploading ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Upload className="w-3.5 h-3.5" />
              )}
              <span>Tải lên</span>
            </button>
          </div>
        </header>

        {/* Storage Meter Bar & Alerts */}
        <div className="px-6 py-3.5 border-b border-gray-800/80 bg-gray-900/40">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="flex items-center gap-2.5">
              <HardDrive className="w-4 h-4 text-sky-400 shrink-0" />
              <div className="text-xs">
                <span className="text-gray-300 font-medium">Dung lượng Workspace: </span>
                <span className="font-semibold text-white">
                  {formatBytes(storage?.used_bytes ?? 0)}
                </span>{" "}
                <span className="text-gray-400">/ 5.0 GB ({storage?.percentage ?? 0}%)</span>
              </div>
            </div>

            {/* Storage Progress Bar */}
            <div className="w-full sm:w-64 bg-gray-800 rounded-full h-2.5 overflow-hidden">
              <div
                className={`h-full transition-all duration-300 rounded-full ${
                  (storage?.percentage ?? 0) > 90
                    ? "bg-rose-500"
                    : (storage?.percentage ?? 0) > 70
                    ? "bg-amber-500"
                    : "bg-sky-500"
                }`}
                style={{ width: `${Math.min(100, Math.max(1, storage?.percentage ?? 0))}%` }}
              />
            </div>
          </div>
        </div>

        {/* Notifications */}
        {errorBanner && (
          <div className="mx-6 mt-4 p-3 rounded-xl bg-rose-950/60 border border-rose-800 text-rose-300 text-xs flex items-center justify-between">
            <div className="flex items-center gap-2">
              <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
              <span>{errorBanner}</span>
            </div>
            <button
              onClick={() => setErrorBanner(null)}
              className="text-rose-400 hover:text-rose-200"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        )}

        {successBanner && (
          <div className="mx-6 mt-4 p-3 rounded-xl bg-emerald-950/60 border border-emerald-800 text-emerald-300 text-xs flex items-center justify-between">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
              <span>{successBanner}</span>
            </div>
            <button
              onClick={() => setSuccessBanner(null)}
              className="text-emerald-400 hover:text-emerald-200"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        )}

        {/* Controls: Filter Tabs & Search */}
        <div className="px-6 pt-4 pb-2 flex flex-col md:flex-row md:items-center justify-between gap-4 shrink-0">
          {/* Category Tabs */}
          <div className="flex items-center gap-1.5 p-1 bg-gray-900 rounded-xl border border-gray-800" role="tablist">
            {CATEGORY_TABS.map((tab) => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.key;
              return (
                <button
                  key={tab.key}
                  role="tab"
                  aria-selected={isActive}
                  onClick={() => setActiveTab(tab.key)}
                  className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-medium transition cursor-pointer ${
                    isActive
                      ? "bg-gray-800 text-sky-400 shadow-sm font-semibold"
                      : "text-gray-400 hover:text-gray-200 hover:bg-gray-800/50"
                  }`}
                >
                  <Icon className="w-3.5 h-3.5" />
                  <span>{tab.label}</span>
                </button>
              );
            })}
          </div>

          {/* Search Box */}
          <div className="relative w-full md:w-72">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
            <input
              type="text"
              placeholder="Tìm kiếm tệp theo tên..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-gray-900 border border-gray-800 rounded-xl pl-9 pr-3 py-1.5 text-xs text-gray-200 placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-sky-500"
            />
          </div>
        </div>

        {/* Content View: Files Table / Grid */}
        <div className="flex-1 overflow-y-auto px-6 py-3">
          {isLoading ? (
            <div className="flex flex-col items-center justify-center h-64 text-gray-400 gap-3">
              <Loader2 className="w-6 h-6 animate-spin text-sky-400" />
              <span className="text-xs">Đang tải danh sách tệp...</span>
            </div>
          ) : filteredFiles.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-64 border border-dashed border-gray-800 rounded-2xl p-6 text-center text-gray-500">
              <FolderClosed className="w-10 h-10 text-gray-600 mb-3" />
              <p className="text-sm font-medium text-gray-300">Không tìm thấy tệp nào</p>
              <p className="text-xs text-gray-500 mt-1">
                Tải lên tệp đầu tiên hoặc chạy tác vụ để tạo thành phẩm.
              </p>
            </div>
          ) : (
            <div className="bg-gray-900/70 border border-gray-800 rounded-2xl overflow-hidden shadow-sm">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-gray-800 bg-gray-900 text-gray-400 font-medium">
                    <th className="py-3 px-4 w-10">
                      <input
                        type="checkbox"
                        aria-label="select-all"
                        checked={
                          selectedFileIds.size === filteredFiles.length &&
                          filteredFiles.length > 0
                        }
                        onChange={toggleSelectAll}
                        className="rounded bg-gray-800 border-gray-700 text-sky-500 focus:ring-0 cursor-pointer"
                      />
                    </th>
                    <th className="py-3 px-3">Tên tệp</th>
                    <th className="py-3 px-3">Loại</th>
                    <th className="py-3 px-3">Kích thước</th>
                    <th className="py-3 px-3">Dự án</th>
                    <th className="py-3 px-3">Ngày tạo</th>
                    <th className="py-3 px-4 text-right">Thao tác</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-800/60 text-gray-300">
                  {filteredFiles.map((file) => {
                    const isSelected = selectedFileIds.has(file.id);
                    return (
                      <tr
                        key={file.id}
                        className={`hover:bg-gray-800/40 transition-colors ${
                          isSelected ? "bg-sky-950/20" : ""
                        }`}
                      >
                        <td className="py-3 px-4">
                          <input
                            type="checkbox"
                            aria-label="select-file"
                            checked={isSelected}
                            onChange={() => toggleSelectFile(file.id)}
                            className="rounded bg-gray-800 border-gray-700 text-sky-500 focus:ring-0 cursor-pointer"
                          />
                        </td>
                        <td className="py-3 px-3 font-medium text-white flex items-center gap-2.5 truncate max-w-xs">
                          {getFileIcon(file.file_type)}
                          <span className="truncate" title={file.name}>
                            {file.name}
                          </span>
                        </td>
                        <td className="py-3 px-3 capitalize text-gray-400">
                          {file.file_type}
                        </td>
                        <td className="py-3 px-3 font-mono text-gray-400">
                          {formatBytes(file.size_bytes)}
                        </td>
                        <td className="py-3 px-3">
                          {file.project_id ? (
                            <span className="inline-block px-2 py-0.5 rounded-full text-[10px] bg-gray-800 border border-gray-700 text-gray-300">
                              {file.project_id}
                            </span>
                          ) : (
                            <span className="text-gray-600 text-[11px]">—</span>
                          )}
                        </td>
                        <td className="py-3 px-3 text-gray-400">
                          {formatDate(file.created_at)}
                        </td>
                        <td className="py-3 px-4 text-right">
                          <div className="flex items-center justify-end gap-2">
                            <button
                              type="button"
                              onClick={() => handleDeleteFile(file.id, file.name)}
                              className="p-1.5 rounded-lg text-gray-400 hover:text-rose-400 hover:bg-gray-800 transition cursor-pointer"
                              title="Xóa tệp"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </main>

      {/* Temp Files Cleanup Modal */}
      {showCleanupModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="w-full max-w-md rounded-2xl bg-gray-900 border border-gray-800 p-6 shadow-xl">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2.5 text-amber-400">
                <RefreshCw className="w-5 h-5" />
                <h3 className="text-sm font-semibold text-white">
                  Dọn dẹp tệp tạm thời
                </h3>
              </div>
              <button
                type="button"
                onClick={() => setShowCleanupModal(false)}
                className="text-gray-400 hover:text-white"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <p className="text-xs text-gray-300 leading-relaxed mb-6">
              Hệ thống sẽ quét các thư mục <code className="text-sky-400 font-mono">temp/</code>,{" "}
              <code className="text-sky-400 font-mono">frames/</code>, và{" "}
              <code className="text-sky-400 font-mono">cache/</code> trong Workspace và xóa toàn bộ tệp cũ hơn 7 ngày. Các thành phẩm chính không bị ảnh hưởng.
            </p>

            <div className="flex items-center justify-end gap-3">
              <button
                type="button"
                onClick={() => setShowCleanupModal(false)}
                className="px-3.5 py-2 rounded-lg text-xs font-medium text-gray-400 hover:text-white hover:bg-gray-800 transition cursor-pointer"
              >
                Hủy bỏ
              </button>
              <button
                type="button"
                disabled={isCleaning}
                onClick={handleConfirmCleanup}
                className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-500 text-white text-xs font-medium shadow-sm transition cursor-pointer"
              >
                {isCleaning && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                <span>Xác nhận dọn dẹp</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
