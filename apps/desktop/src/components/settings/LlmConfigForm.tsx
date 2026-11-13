"use client";

import React, { useState } from "react";
import {
  Bot,
  Key,
  CheckCircle2,
  AlertCircle,
  Eye,
  EyeOff,
  Edit2,
  RefreshCw,
  Server,
  Zap,
  Globe,
  Sliders,
} from "lucide-react";
import { LlmProviderConfig, LlmProviderUpdatePayload } from "@/lib/types";

export interface LlmConfigFormProps {
  providers: Record<string, LlmProviderConfig>;
  onSaveProvider: (payload: LlmProviderUpdatePayload) => Promise<boolean | void>;
  onTestConnection: (
    provider: string,
    params?: { api_key?: string; default_model?: string; base_url?: string }
  ) => Promise<{ success: boolean; message: string; latency_ms?: number }>;
  isLoading?: boolean;
}

const PROVIDER_ORDER = ["gemini", "openai", "anthropic", "deepseek", "ollama"];

export function LlmConfigForm({
  providers,
  onSaveProvider,
  onTestConnection,
  isLoading = false,
}: LlmConfigFormProps) {
  const [editingProvider, setEditingProvider] = useState<string | null>(null);
  const [formData, setFormData] = useState<Record<string, { api_key: string; default_model: string; base_url: string; is_enabled: boolean }>>({});
  const [showKeyInput, setShowKeyInput] = useState<Record<string, boolean>>({});
  const [testStatus, setTestStatus] = useState<Record<string, { loading: boolean; success?: boolean; message?: string }>>({});
  const [savingStatus, setSavingStatus] = useState<Record<string, boolean>>({});

  const startEditing = (providerKey: string) => {
    const prov = providers[providerKey] || {
      provider: providerKey,
      default_model: "",
      base_url: "",
      is_enabled: true,
    };
    setFormData((prev) => ({
      ...prev,
      [providerKey]: {
        api_key: "",
        default_model: prov.default_model || "",
        base_url: prov.base_url || "",
        is_enabled: prov.is_enabled ?? true,
      },
    }));
    setEditingProvider(providerKey);
  };

  const cancelEditing = () => {
    setEditingProvider(null);
  };

  const handleSave = async (providerKey: string) => {
    const data = formData[providerKey];
    if (!data) return;

    setSavingStatus((prev) => ({ ...prev, [providerKey]: true }));
    try {
      const payload: LlmProviderUpdatePayload = {
        provider: providerKey,
        default_model: data.default_model.trim() || undefined,
        base_url: data.base_url.trim() || undefined,
        is_enabled: data.is_enabled,
      };

      // Only pass api_key if the user entered something
      if (data.api_key.trim()) {
        payload.api_key = data.api_key.trim();
      }

      await onSaveProvider(payload);
      setEditingProvider(null);
    } finally {
      setSavingStatus((prev) => ({ ...prev, [providerKey]: false }));
    }
  };

  const handleTest = async (providerKey: string) => {
    setTestStatus((prev) => ({
      ...prev,
      [providerKey]: { loading: true },
    }));

    try {
      const activeData = formData[providerKey];
      const params = activeData
        ? {
            api_key: activeData.api_key.trim() || undefined,
            default_model: activeData.default_model.trim() || undefined,
            base_url: activeData.base_url.trim() || undefined,
          }
        : {};

      const result = await onTestConnection(providerKey, params);
      setTestStatus((prev) => ({
        ...prev,
        [providerKey]: {
          loading: false,
          success: result.success,
          message: result.message,
        },
      }));
    } catch (err: any) {
      setTestStatus((prev) => ({
        ...prev,
        [providerKey]: {
          loading: false,
          success: false,
          message: err?.message || "Kiểm tra kết nối thất bại.",
        },
      }));
    }
  };

  // Merge known and extra providers
  const allKeys = Array.from(
    new Set([...PROVIDER_ORDER, ...Object.keys(providers)])
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between pb-2 border-b border-gray-800">
        <div>
          <h2 className="text-base font-semibold text-white flex items-center gap-2">
            <Key className="w-4 h-4 text-sky-400" />
            Cấu hình Nhà Cung Cấp Mô Hình AI
          </h2>
          <p className="text-xs text-gray-400 mt-0.5">
            Quản lý API Key các nhà cung cấp mô hình AI. Mọi khóa xác thực được mã hóa đối xứng Fernet bảo mật tuyệt đối tại máy chủ nội bộ.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4">
        {allKeys.map((key) => {
          const config = providers[key] || {
            provider: key,
            name: key.toUpperCase(),
            has_key: false,
            masked_key: "",
            default_model: "default",
            base_url: null,
            is_enabled: false,
            status: "disconnected",
          };

          const isEditing = editingProvider === key;
          const currentForm = formData[key] || {
            api_key: "",
            default_model: config.default_model,
            base_url: config.base_url || "",
            is_enabled: config.is_enabled,
          };
          const test = testStatus[key];
          const isSaving = savingStatus[key] || false;

          return (
            <div
              key={key}
              className="p-5 rounded-xl bg-gray-900 border border-gray-800 hover:border-gray-700 transition-all shadow-sm"
              data-testid={`llm-card-${key}`}
            >
              {/* Card Header */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-9 h-9 rounded-lg bg-sky-950 border border-sky-800/50 flex items-center justify-center text-sky-400">
                    <Bot className="w-5 h-5" />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <h3 className="text-sm font-semibold text-white">{config.name}</h3>
                      {config.is_enabled ? (
                        <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-emerald-950 text-emerald-400 border border-emerald-800/60">
                          Đang hoạt động
                        </span>
                      ) : (
                        <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-gray-800 text-gray-400 border border-gray-700">
                          Chưa kích hoạt
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-gray-400">
                      Mô hình mặc định: <span className="font-mono text-gray-300">{config.default_model}</span>
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => handleTest(key)}
                    disabled={test?.loading || isLoading}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-gray-800 hover:bg-gray-700 text-gray-200 border border-gray-700 hover:border-gray-600 transition-colors disabled:opacity-50 cursor-pointer"
                    aria-label={`Kiểm tra kết nối ${config.name}`}
                  >
                    <RefreshCw className={`w-3.5 h-3.5 ${test?.loading ? "animate-spin text-sky-400" : "text-gray-400"}`} />
                    <span>{test?.loading ? "Đang thử..." : "Kiểm tra kết nối"}</span>
                  </button>

                  {!isEditing && (
                    <button
                      type="button"
                      onClick={() => startEditing(key)}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-sky-900/40 hover:bg-sky-800/60 text-sky-300 border border-sky-700/50 transition-colors cursor-pointer"
                      aria-label={`Chỉnh sửa ${config.name}`}
                    >
                      <Edit2 className="w-3.5 h-3.5" />
                      <span>Chỉnh sửa</span>
                    </button>
                  )}
                </div>
              </div>

              {/* Status / Test message */}
              {test && test.message && (
                <div
                  className={`mt-3 p-2.5 rounded-lg text-xs flex items-center gap-2 border ${
                    test.success
                      ? "bg-emerald-950/40 text-emerald-300 border-emerald-800/60"
                      : "bg-rose-950/40 text-rose-300 border-rose-800/60"
                  }`}
                >
                  {test.success ? (
                    <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                  ) : (
                    <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
                  )}
                  <span>{test.message}</span>
                </div>
              )}

              {/* Key details view (Read-only mode) */}
              {!isEditing ? (
                <div className="mt-4 pt-3 border-t border-gray-800/80 flex flex-wrap items-center justify-between text-xs text-gray-400 gap-2">
                  <div className="flex items-center gap-2">
                    <span className="text-gray-500">Khóa API:</span>
                    {config.has_key ? (
                      <span className="font-mono bg-gray-950 px-2.5 py-1 rounded border border-gray-800 text-gray-200">
                        {config.masked_key}
                      </span>
                    ) : key === "ollama" ? (
                      <span className="italic text-gray-500">Không bắt buộc (Chạy qua local endpoint)</span>
                    ) : (
                      <span className="italic text-amber-500/90">Chưa cấu hình API Key</span>
                    )}
                  </div>
                  {config.base_url && (
                    <div className="flex items-center gap-1.5 font-mono text-gray-400">
                      <Globe className="w-3.5 h-3.5 text-gray-500" />
                      <span>{config.base_url}</span>
                    </div>
                  )}
                </div>
              ) : (
                /* Edit Form view */
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    handleSave(key);
                  }}
                  className="mt-4 pt-4 border-t border-gray-800 space-y-3"
                >
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {/* API Key Field */}
                    <div className="space-y-1">
                      <label className="text-xs font-medium text-gray-300 flex items-center justify-between">
                        <span>API Key mới</span>
                        {config.has_key && (
                          <span className="text-[11px] text-gray-500 font-normal">
                            Đang dùng: {config.masked_key}
                          </span>
                        )}
                      </label>
                      <div className="relative">
                        <input
                          type={showKeyInput[key] ? "text" : "password"}
                          value={currentForm.api_key}
                          onChange={(e) =>
                            setFormData((prev) => ({
                              ...prev,
                              [key]: { ...prev[key], api_key: e.target.value },
                            }))
                          }
                          placeholder={
                            config.has_key
                              ? "Nhập API key mới để ghi đè (hoặc để trống)"
                              : "Nhập API key..."
                          }
                          className="w-full px-3 py-1.5 pr-9 text-xs rounded-lg bg-gray-950 border border-gray-700 text-gray-100 placeholder-gray-500 focus:outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500"
                        />
                        <button
                          type="button"
                          onClick={() =>
                            setShowKeyInput((prev) => ({
                              ...prev,
                              [key]: !prev[key],
                            }))
                          }
                          className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-200"
                        >
                          {showKeyInput[key] ? (
                            <EyeOff className="w-3.5 h-3.5" />
                          ) : (
                            <Eye className="w-3.5 h-3.5" />
                          )}
                        </button>
                      </div>
                    </div>

                    {/* Default Model */}
                    <div className="space-y-1">
                      <label className="text-xs font-medium text-gray-300">
                        Mô hình chỉ định mặc định
                      </label>
                      <input
                        type="text"
                        value={currentForm.default_model}
                        onChange={(e) =>
                          setFormData((prev) => ({
                            ...prev,
                            [key]: { ...prev[key], default_model: e.target.value },
                          }))
                        }
                        placeholder="Ví dụ: gemini-2.5-flash, gpt-4o..."
                        className="w-full px-3 py-1.5 text-xs rounded-lg bg-gray-950 border border-gray-700 text-gray-100 placeholder-gray-500 focus:outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500 font-mono"
                      />
                    </div>
                  </div>

                  {/* Optional Custom Base URL */}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <div className="space-y-1">
                      <label className="text-xs font-medium text-gray-300">
                        Base URL (Tùy chọn Proxy / Ollama Endpoint)
                      </label>
                      <input
                        type="text"
                        value={currentForm.base_url}
                        onChange={(e) =>
                          setFormData((prev) => ({
                            ...prev,
                            [key]: { ...prev[key], base_url: e.target.value },
                          }))
                        }
                        placeholder="http://localhost:11434 hoặc custom endpoint"
                        className="w-full px-3 py-1.5 text-xs rounded-lg bg-gray-950 border border-gray-700 text-gray-100 placeholder-gray-500 focus:outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500 font-mono"
                      />
                    </div>

                    {/* Enable / Disable Toggle */}
                    <div className="flex items-center gap-3 pt-5">
                      <label className="flex items-center gap-2 cursor-pointer text-xs text-gray-300">
                        <input
                          type="checkbox"
                          checked={currentForm.is_enabled}
                          onChange={(e) =>
                            setFormData((prev) => ({
                              ...prev,
                              [key]: { ...prev[key], is_enabled: e.target.checked },
                            }))
                          }
                          className="w-4 h-4 rounded bg-gray-950 border-gray-700 text-sky-500 focus:ring-sky-400 focus:ring-offset-gray-900"
                        />
                        <span>Kích hoạt nhà cung cấp này</span>
                      </label>
                    </div>
                  </div>

                  {/* Action Buttons */}
                  <div className="flex items-center justify-end gap-2 pt-2">
                    <button
                      type="button"
                      onClick={cancelEditing}
                      className="px-3 py-1.5 rounded-lg text-xs text-gray-400 hover:text-gray-200 hover:bg-gray-800 transition-colors"
                    >
                      Hủy
                    </button>
                    <button
                      type="submit"
                      disabled={isSaving}
                      className="px-4 py-1.5 rounded-lg text-xs font-medium bg-sky-500 hover:bg-sky-600 text-white transition-colors disabled:opacity-50 cursor-pointer shadow-sm"
                    >
                      {isSaving ? "Đang lưu..." : "Lưu cấu hình"}
                    </button>
                  </div>
                </form>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
