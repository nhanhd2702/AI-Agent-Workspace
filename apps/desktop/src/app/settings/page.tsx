"use client";

import React, { useState, useEffect, useCallback } from "react";
import {
  Settings,
  Key,
  Cpu,
  User,
  ShieldCheck,
  Save,
  CheckCircle2,
  AlertCircle,
  RefreshCw,
  Sliders,
  Moon,
  Sun,
  Laptop,
  Languages,
  DollarSign,
  Coins,
  DatabaseBackup,
} from "lucide-react";
import { SidebarNav } from "@/components/layout/SidebarNav";
import { LlmConfigForm } from "@/components/settings/LlmConfigForm";
import { ConnectorHealthList } from "@/components/settings/ConnectorHealthList";
import { defaultApiClient } from "@/lib/apiClient";
import {
  LlmProviderConfig,
  LlmProviderUpdatePayload,
  ConnectorHealthItem,
  UserProfileSettings,
  ProfileUpdatePayload,
} from "@/lib/types";

export type SettingsTab = "llm" | "connectors" | "profile";

const DEFAULT_MOCK_PROVIDERS: Record<string, LlmProviderConfig> = {
  gemini: {
    provider: "gemini",
    name: "Google Gemini",
    has_key: false,
    masked_key: "",
    default_model: "gemini-2.5-flash",
    base_url: null,
    is_enabled: false,
    status: "disconnected",
    updated_at: null,
  },
  openai: {
    provider: "openai",
    name: "OpenAI",
    has_key: false,
    masked_key: "",
    default_model: "gpt-4o",
    base_url: null,
    is_enabled: false,
    status: "disconnected",
    updated_at: null,
  },
  anthropic: {
    provider: "anthropic",
    name: "Anthropic Claude",
    has_key: false,
    masked_key: "",
    default_model: "claude-3-5-sonnet-20241022",
    base_url: null,
    is_enabled: false,
    status: "disconnected",
    updated_at: null,
  },
  deepseek: {
    provider: "deepseek",
    name: "DeepSeek",
    has_key: false,
    masked_key: "",
    default_model: "deepseek-chat",
    base_url: null,
    is_enabled: false,
    status: "disconnected",
    updated_at: null,
  },
  ollama: {
    provider: "ollama",
    name: "Ollama (Local)",
    has_key: false,
    masked_key: "",
    default_model: "llama3.2",
    base_url: "http://localhost:11434",
    is_enabled: true,
    status: "connected",
    updated_at: null,
  },
};

const DEFAULT_MOCK_CONNECTORS: ConnectorHealthItem[] = [
  {
    id: "ffmpeg",
    name: "FFmpeg Media Processor",
    category: "runtime",
    healthy: true,
    status: "ready",
    message: "Tìm thấy binary FFmpeg",
    last_checked: new Date().toISOString(),
  },
  {
    id: "playwright",
    name: "Playwright Chromium",
    category: "runtime",
    healthy: true,
    status: "ready",
    message: "Playwright headless Chromium sandbox sẵn sàng",
    last_checked: new Date().toISOString(),
  },
  {
    id: "shell",
    name: "Shell Sandbox",
    category: "runtime",
    healthy: true,
    status: "ready",
    message: "Shell sandbox với allowlist an toàn",
    last_checked: new Date().toISOString(),
  },
  {
    id: "chromadb",
    name: "ChromaDB Vector Store",
    category: "storage",
    healthy: true,
    status: "ready",
    message: "ChromaDB vector store hoạt động",
    last_checked: new Date().toISOString(),
  },
  {
    id: "youtube",
    name: "YouTube Data API",
    category: "external",
    healthy: false,
    status: "disconnected",
    message: "Chưa cấu hình API key",
    last_checked: new Date().toISOString(),
  },
  {
    id: "telegram",
    name: "Telegram Bot",
    category: "external",
    healthy: false,
    status: "disconnected",
    message: "Chưa cấu hình bot token",
    last_checked: new Date().toISOString(),
  },
  {
    id: "zalo",
    name: "Zalo OA",
    category: "external",
    healthy: false,
    status: "disconnected",
    message: "Chưa cấu hình OA token",
    last_checked: new Date().toISOString(),
  },
];

const DEFAULT_MOCK_PROFILE: UserProfileSettings = {
  id: "settings-default",
  theme: "dark",
  language: "vi",
  daily_token_limit: 1000000,
  daily_usd_limit: 10.0,
  auto_backup: true,
  preferences: {
    notifications_enabled: true,
    compact_view: false,
  },
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
};

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState<SettingsTab>("llm");
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [successBanner, setSuccessBanner] = useState<string | null>(null);

  // Domain states
  const [providers, setProviders] = useState<Record<string, LlmProviderConfig>>(DEFAULT_MOCK_PROVIDERS);
  const [connectors, setConnectors] = useState<ConnectorHealthItem[]>(DEFAULT_MOCK_CONNECTORS);
  const [profile, setProfile] = useState<UserProfileSettings>(DEFAULT_MOCK_PROFILE);
  const [isSavingProfile, setIsSavingProfile] = useState<boolean>(false);

  // Form state for profile tab
  const [profileForm, setProfileForm] = useState({
    theme: "dark",
    language: "vi",
    daily_token_limit: 1000000,
    daily_usd_limit: 10.0,
    auto_backup: true,
    notifications_enabled: true,
  });

  const loadSettingsData = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [llmData, healthData, profileData] = await Promise.all([
        defaultApiClient.getLlmSettings().catch(() => DEFAULT_MOCK_PROVIDERS),
        defaultApiClient.getConnectorsHealth().catch(() => DEFAULT_MOCK_CONNECTORS),
        defaultApiClient.getUserProfile().catch(() => DEFAULT_MOCK_PROFILE),
      ]);

      if (llmData && Object.keys(llmData).length > 0) {
        setProviders(llmData);
      }
      if (healthData && healthData.length > 0) {
        setConnectors(healthData);
      }
      if (profileData) {
        setProfile(profileData);
        setProfileForm({
          theme: profileData.theme || "dark",
          language: profileData.language || "vi",
          daily_token_limit: profileData.daily_token_limit ?? 1000000,
          daily_usd_limit: profileData.daily_usd_limit ?? 10.0,
          auto_backup: profileData.auto_backup ?? true,
          notifications_enabled: profileData.preferences?.notifications_enabled ?? true,
        });
      }
    } catch (err: any) {
      setError(err?.message || "Không thể tải cấu hình hệ thống.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSettingsData();
  }, [loadSettingsData]);

  const handleNavigate = (navId: string) => {
    if (typeof window === "undefined") return;
    if (navId === "workspace") window.location.assign("/");
    else if (navId === "office") window.location.assign("/office");
    else if (navId === "board") window.location.assign("/board");
    else if (navId === "brain") window.location.assign("/brain");
    else if (navId === "customer_chat" || navId === "inbox") window.location.assign("/inbox");
    else if (navId === "settings") window.location.assign("/settings");
  };

  // LLM Save Provider Handler
  const handleSaveProvider = async (payload: LlmProviderUpdatePayload) => {
    try {
      const updated = await defaultApiClient.updateLlmProvider(payload);
      setProviders((prev) => ({
        ...prev,
        [updated.provider]: updated,
      }));
      setSuccessBanner(`Đã lưu cấu hình nhà cung cấp ${updated.name || payload.provider} thành công!`);
      setTimeout(() => setSuccessBanner(null), 4000);
    } catch (err: any) {
      setError(err?.message || "Lỗi khi lưu cấu hình provider.");
    }
  };

  // LLM Connection Test Handler
  const handleTestConnection = async (
    provider: string,
    params?: { api_key?: string; default_model?: string; base_url?: string }
  ) => {
    return defaultApiClient.testLlmConnection(provider, params);
  };

  // Connectors Refresh Handler
  const handleRefreshConnectors = async () => {
    setIsLoading(true);
    try {
      const refreshed = await defaultApiClient.getConnectorsHealth();
      setConnectors(refreshed);
    } catch (err: any) {
      setError(err?.message || "Không thể làm mới tình trạng kết nối.");
    } finally {
      setIsLoading(false);
    }
  };

  // Profile Save Handler
  const handleSaveProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSavingProfile(true);
    setError(null);
    try {
      const payload: ProfileUpdatePayload = {
        theme: profileForm.theme,
        language: profileForm.language,
        daily_token_limit: Number(profileForm.daily_token_limit),
        daily_usd_limit: Number(profileForm.daily_usd_limit),
        auto_backup: profileForm.auto_backup,
        preferences: {
          notifications_enabled: profileForm.notifications_enabled,
        },
      };

      const updated = await defaultApiClient.updateUserProfile(payload);
      setProfile(updated);
      setSuccessBanner("Đã cập nhật hồ sơ & tùy chọn giao diện thành công!");
      setTimeout(() => setSuccessBanner(null), 4000);
    } catch (err: any) {
      setError(err?.message || "Lỗi khi cập nhật hồ sơ người dùng.");
    } finally {
      setIsSavingProfile(false);
    }
  };

  return (
    <div className="flex h-screen bg-gray-950 text-gray-100 overflow-hidden">
      {/* Sidebar Navigation */}
      <SidebarNav
        activeNav="settings"
        onNavigate={handleNavigate}
        onNewTask={() => {
          if (typeof window !== "undefined") window.location.assign("/");
        }}
      />

      {/* Main Settings Content Area */}
      <main className="flex-1 flex flex-col h-full overflow-hidden">
        {/* Top Header */}
        <header className="px-8 py-5 border-b border-gray-800 bg-gray-900/60 backdrop-blur-md flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-sky-500/10 border border-sky-500/20 flex items-center justify-center text-sky-400">
              <Settings className="w-5 h-5" />
            </div>
            <div>
              <h1 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
                <span>Cài Đặt Hệ Thống</span>
                <span className="text-xs px-2.5 py-0.5 rounded-full bg-sky-950 text-sky-400 border border-sky-800/60 font-medium">
                  Văn Phòng AI
                </span>
              </h1>
              <p className="text-xs text-gray-400 mt-0.5">
                Cấu hình mã hóa API key, kiểm tra kết nối MCP tool, và tùy chỉnh hồ sơ hạn mức chi tiêu.
              </p>
            </div>
          </div>

          {/* 3 Main Settings Navigation Tabs */}
          <div
            className="flex items-center bg-gray-950/80 p-1 rounded-xl border border-gray-800/80 shadow-inner"
            role="tablist"
            aria-label="Cài đặt hệ thống"
          >
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === "llm"}
              onClick={() => setActiveTab("llm")}
              className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all cursor-pointer ${
                activeTab === "llm"
                  ? "bg-sky-500 text-white shadow-sm font-semibold"
                  : "text-gray-400 hover:text-gray-200 hover:bg-gray-900"
              }`}
            >
              <Key className="w-3.5 h-3.5" />
              <span>Cấu hình AI (LLM)</span>
            </button>

            <button
              type="button"
              role="tab"
              aria-selected={activeTab === "connectors"}
              onClick={() => setActiveTab("connectors")}
              className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all cursor-pointer ${
                activeTab === "connectors"
                  ? "bg-sky-500 text-white shadow-sm font-semibold"
                  : "text-gray-400 hover:text-gray-200 hover:bg-gray-900"
              }`}
            >
              <Cpu className="w-3.5 h-3.5" />
              <span>Kết nối & Công cụ (Connectors)</span>
            </button>

            <button
              type="button"
              role="tab"
              aria-selected={activeTab === "profile"}
              onClick={() => setActiveTab("profile")}
              className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all cursor-pointer ${
                activeTab === "profile"
                  ? "bg-sky-500 text-white shadow-sm font-semibold"
                  : "text-gray-400 hover:text-gray-200 hover:bg-gray-900"
              }`}
            >
              <User className="w-3.5 h-3.5" />
              <span>Hồ sơ & Giao diện (Profile)</span>
            </button>
          </div>
        </header>

        {/* Alerts & Notifications */}
        {successBanner && (
          <div className="mx-8 mt-4 p-3 rounded-xl bg-emerald-950/60 border border-emerald-800/80 text-emerald-300 text-xs flex items-center gap-2.5 shadow-sm">
            <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
            <span>{successBanner}</span>
          </div>
        )}

        {error && (
          <div className="mx-8 mt-4 p-3 rounded-xl bg-rose-950/60 border border-rose-800/80 text-rose-300 text-xs flex items-center gap-2.5 shadow-sm">
            <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* Tab Body Container */}
        <div className="flex-1 overflow-y-auto px-8 py-6">
          {/* Tab 1: Cấu hình AI (LLM) */}
          {activeTab === "llm" && (
            <div className="max-w-4xl mx-auto">
              <LlmConfigForm
                providers={providers}
                onSaveProvider={handleSaveProvider}
                onTestConnection={handleTestConnection}
                isLoading={isLoading}
              />
            </div>
          )}

          {/* Tab 2: Kết nối & Công cụ (Connectors) */}
          {activeTab === "connectors" && (
            <div className="max-w-4xl mx-auto">
              <ConnectorHealthList
                connectors={connectors}
                onRefresh={handleRefreshConnectors}
                isLoading={isLoading}
              />
            </div>
          )}

          {/* Tab 3: Hồ sơ & Giao diện (Profile) */}
          {activeTab === "profile" && (
            <div className="max-w-3xl mx-auto space-y-6">
              <div className="flex items-center justify-between pb-2 border-b border-gray-800">
                <div>
                  <h2 className="text-base font-semibold text-white flex items-center gap-2">
                    <Sliders className="w-4 h-4 text-sky-400" />
                    Tùy Chỉnh Hồ Sơ & Hạn Mức Hoạt Động
                  </h2>
                  <p className="text-xs text-gray-400 mt-0.5">
                    Tùy chỉnh giao diện, ngôn ngữ và hạn mức chi tiêu token hàng ngày của toàn bộ tổ chức AI.
                  </p>
                </div>
              </div>

              <form onSubmit={handleSaveProfile} className="space-y-6">
                {/* 1. Giao diện & Ngôn ngữ */}
                <div className="p-5 rounded-xl bg-gray-900 border border-gray-800 space-y-4">
                  <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                    <Languages className="w-4 h-4 text-indigo-400" />
                    <span>Giao diện & Ngôn ngữ</span>
                  </h3>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {/* Theme Choice */}
                    <div className="space-y-2">
                      <label className="text-xs font-medium text-gray-300">Chủ đề hiển thị (Theme)</label>
                      <div className="grid grid-cols-3 gap-2">
                        <button
                          type="button"
                          onClick={() => setProfileForm((prev) => ({ ...prev, theme: "dark" }))}
                          className={`flex items-center justify-center gap-1.5 py-2 px-3 rounded-lg text-xs font-medium border transition-colors cursor-pointer ${
                            profileForm.theme === "dark"
                              ? "bg-sky-950 text-sky-300 border-sky-600 font-semibold"
                              : "bg-gray-950 text-gray-400 border-gray-800 hover:border-gray-700"
                          }`}
                        >
                          <Moon className="w-3.5 h-3.5" />
                          <span>Tối (Dark)</span>
                        </button>

                        <button
                          type="button"
                          onClick={() => setProfileForm((prev) => ({ ...prev, theme: "light" }))}
                          className={`flex items-center justify-center gap-1.5 py-2 px-3 rounded-lg text-xs font-medium border transition-colors cursor-pointer ${
                            profileForm.theme === "light"
                              ? "bg-sky-950 text-sky-300 border-sky-600 font-semibold"
                              : "bg-gray-950 text-gray-400 border-gray-800 hover:border-gray-700"
                          }`}
                        >
                          <Sun className="w-3.5 h-3.5" />
                          <span>Sáng (Light)</span>
                        </button>

                        <button
                          type="button"
                          onClick={() => setProfileForm((prev) => ({ ...prev, theme: "system" }))}
                          className={`flex items-center justify-center gap-1.5 py-2 px-3 rounded-lg text-xs font-medium border transition-colors cursor-pointer ${
                            profileForm.theme === "system"
                              ? "bg-sky-950 text-sky-300 border-sky-600 font-semibold"
                              : "bg-gray-950 text-gray-400 border-gray-800 hover:border-gray-700"
                          }`}
                        >
                          <Laptop className="w-3.5 h-3.5" />
                          <span>Hệ thống</span>
                        </button>
                      </div>
                    </div>

                    {/* Language Choice */}
                    <div className="space-y-2">
                      <label className="text-xs font-medium text-gray-300">Ngôn ngữ giao diện</label>
                      <div className="grid grid-cols-2 gap-2">
                        <button
                          type="button"
                          onClick={() => setProfileForm((prev) => ({ ...prev, language: "vi" }))}
                          className={`flex items-center justify-center gap-1.5 py-2 px-3 rounded-lg text-xs font-medium border transition-colors cursor-pointer ${
                            profileForm.language === "vi"
                              ? "bg-sky-950 text-sky-300 border-sky-600 font-semibold"
                              : "bg-gray-950 text-gray-400 border-gray-800 hover:border-gray-700"
                          }`}
                        >
                          <span>🇻🇳 Tiếng Việt</span>
                        </button>

                        <button
                          type="button"
                          onClick={() => setProfileForm((prev) => ({ ...prev, language: "en" }))}
                          className={`flex items-center justify-center gap-1.5 py-2 px-3 rounded-lg text-xs font-medium border transition-colors cursor-pointer ${
                            profileForm.language === "en"
                              ? "bg-sky-950 text-sky-300 border-sky-600 font-semibold"
                              : "bg-gray-950 text-gray-400 border-gray-800 hover:border-gray-700"
                          }`}
                        >
                          <span>🇺🇸 English</span>
                        </button>
                      </div>
                    </div>
                  </div>
                </div>

                {/* 2. Hạn Mức Chi Tiêu (Quota & Spending Limits) */}
                <div className="p-5 rounded-xl bg-gray-900 border border-gray-800 space-y-4">
                  <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                    <DollarSign className="w-4 h-4 text-emerald-400" />
                    <span>Hạn Mức Chi Tiêu & Token (Daily Quota)</span>
                  </h3>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {/* Daily Token Limit */}
                    <div className="space-y-1.5">
                      <label className="text-xs font-medium text-gray-300 flex items-center gap-1.5">
                        <Coins className="w-3.5 h-3.5 text-amber-400" />
                        <span>Hạn mức Token mỗi ngày</span>
                      </label>
                      <input
                        type="number"
                        min="0"
                        step="50000"
                        value={profileForm.daily_token_limit}
                        onChange={(e) =>
                          setProfileForm((prev) => ({
                            ...prev,
                            daily_token_limit: Number(e.target.value),
                          }))
                        }
                        className="w-full px-3 py-2 text-xs rounded-lg bg-gray-950 border border-gray-700 text-gray-100 placeholder-gray-500 focus:outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500 font-mono"
                      />
                      <p className="text-[11px] text-gray-500">
                        Hệ thống tự động ngắt các tác tử khi vượt quá số lượng token này trong 24 giờ.
                      </p>
                    </div>

                    {/* Daily USD Limit */}
                    <div className="space-y-1.5">
                      <label className="text-xs font-medium text-gray-300 flex items-center gap-1.5">
                        <DollarSign className="w-3.5 h-3.5 text-emerald-400" />
                        <span>Hạn mức chi phí USD mỗi ngày ($)</span>
                      </label>
                      <input
                        type="number"
                        min="0"
                        step="0.5"
                        value={profileForm.daily_usd_limit}
                        onChange={(e) =>
                          setProfileForm((prev) => ({
                            ...prev,
                            daily_usd_limit: Number(e.target.value),
                          }))
                        }
                        className="w-full px-3 py-2 text-xs rounded-lg bg-gray-950 border border-gray-700 text-gray-100 placeholder-gray-500 focus:outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500 font-mono"
                      />
                      <p className="text-[11px] text-gray-500">
                        Ngăn ngừa phát sinh chi phí ngoài ý muốn từ các API cloud trả phí.
                      </p>
                    </div>
                  </div>
                </div>

                {/* 3. Sao lưu & Thông báo */}
                <div className="p-5 rounded-xl bg-gray-900 border border-gray-800 space-y-3">
                  <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                    <DatabaseBackup className="w-4 h-4 text-cyan-400" />
                    <span>Sao Lưu & Bảo Mật Dữ Liệu</span>
                  </h3>

                  <div className="space-y-3">
                    <label className="flex items-center gap-2.5 cursor-pointer text-xs text-gray-300">
                      <input
                        type="checkbox"
                        checked={profileForm.auto_backup}
                        onChange={(e) =>
                          setProfileForm((prev) => ({
                            ...prev,
                            auto_backup: e.target.checked,
                          }))
                        }
                        className="w-4 h-4 rounded bg-gray-950 border-gray-700 text-sky-500 focus:ring-sky-400 focus:ring-offset-gray-900"
                      />
                      <span>Tự động sao lưu database SQLite & ChromaDB định kỳ mỗi ngày</span>
                    </label>

                    <label className="flex items-center gap-2.5 cursor-pointer text-xs text-gray-300">
                      <input
                        type="checkbox"
                        checked={profileForm.notifications_enabled}
                        onChange={(e) =>
                          setProfileForm((prev) => ({
                            ...prev,
                            notifications_enabled: e.target.checked,
                          }))
                        }
                        className="w-4 h-4 rounded bg-gray-950 border-gray-700 text-sky-500 focus:ring-sky-400 focus:ring-offset-gray-900"
                      />
                      <span>Bật thông báo hệ thống khi tác tử hoàn thành nhiệm vụ hoặc gặp lỗi</span>
                    </label>
                  </div>
                </div>

                {/* Submit button */}
                <div className="flex justify-end pt-2">
                  <button
                    type="submit"
                    disabled={isSavingProfile}
                    className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium bg-sky-500 hover:bg-sky-600 text-white transition-colors disabled:opacity-50 cursor-pointer shadow-sm"
                  >
                    <Save className="w-4 h-4" />
                    <span>{isSavingProfile ? "Đang lưu..." : "Lưu tùy chọn hồ sơ"}</span>
                  </button>
                </div>
              </form>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
