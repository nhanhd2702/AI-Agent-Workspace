import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import { LlmConfigForm } from "./LlmConfigForm";
import { ConnectorHealthList } from "./ConnectorHealthList";
import SettingsPage from "@/app/settings/page";
import { LlmProviderConfig, ConnectorHealthItem, UserProfileSettings } from "@/lib/types";

describe("SettingsComponents Unit & Integration Tests (Task 5.1)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("LlmConfigForm", () => {
    const mockProviders: Record<string, LlmProviderConfig> = {
      gemini: {
        provider: "gemini",
        name: "Google Gemini",
        has_key: true,
        masked_key: "****************1234",
        default_model: "gemini-2.5-flash",
        base_url: null,
        is_enabled: true,
        status: "connected",
        updated_at: "2026-03-01T00:00:00Z",
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
        has_key: true,
        masked_key: "****************7766",
        default_model: "claude-3-5-sonnet-20241022",
        base_url: null,
        is_enabled: true,
        status: "connected",
        updated_at: "2026-03-01T00:00:00Z",
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
        updated_at: "2026-03-01T00:00:00Z",
      },
    };

    it("renders provider cards with masked keys, status badges, and edit toggle", async () => {
      const handleSave = vi.fn().mockResolvedValue(true);
      const handleTest = vi.fn().mockResolvedValue({ success: true, message: "Kết nối thành công" });

      render(
        <LlmConfigForm
          providers={mockProviders}
          onSaveProvider={handleSave}
          onTestConnection={handleTest}
        />
      );

      // Verify provider names appear
      expect(screen.getByText("Google Gemini")).toBeInTheDocument();
      expect(screen.getByText("OpenAI")).toBeInTheDocument();
      expect(screen.getByText("Anthropic Claude")).toBeInTheDocument();
      expect(screen.getByText("DeepSeek")).toBeInTheDocument();
      expect(screen.getByText("Ollama (Local)")).toBeInTheDocument();

      // Verify masked key rendered for Gemini
      expect(screen.getByText("****************1234")).toBeInTheDocument();

      // Click Edit on OpenAI to reveal input fields
      const editButtons = screen.getAllByRole("button", { name: /Chỉnh sửa|Cấu hình/i });
      fireEvent.click(editButtons[1]); // OpenAI edit button

      // Input for API Key should now be visible
      const apiKeyInput = screen.getByPlaceholderText(/Nhập API key/i);
      expect(apiKeyInput).toBeInTheDocument();

      fireEvent.change(apiKeyInput, { target: { value: "sk-proj-NewSecretKey4321" } });

      // Save button
      const saveBtn = screen.getByRole("button", { name: /Lưu cấu hình|Lưu/i });
      fireEvent.click(saveBtn);

      await waitFor(() => {
        expect(handleSave).toHaveBeenCalledWith(
          expect.objectContaining({
            provider: "openai",
            api_key: "sk-proj-NewSecretKey4321",
          })
        );
      });
    });

    it("triggers connection ping and displays latency/success message", async () => {
      const handleSave = vi.fn().mockResolvedValue(true);
      const handleTest = vi.fn().mockResolvedValue({
        success: true,
        message: "Kết nối Google Gemini thành công (42ms)",
      });

      render(
        <LlmConfigForm
          providers={mockProviders}
          onSaveProvider={handleSave}
          onTestConnection={handleTest}
        />
      );

      const testButtons = screen.getAllByRole("button", { name: /Kiểm tra kết nối/i });
      fireEvent.click(testButtons[0]); // Test Gemini

      await waitFor(() => {
        expect(handleTest).toHaveBeenCalledWith("gemini", expect.anything());
        expect(screen.getByText(/Kết nối Google Gemini thành công/i)).toBeInTheDocument();
      });
    });
  });

  describe("ConnectorHealthList", () => {
    const mockConnectors: ConnectorHealthItem[] = [
      {
        id: "ffmpeg",
        name: "FFmpeg Media Processor",
        category: "runtime",
        healthy: true,
        status: "ready",
        message: "Tìm thấy binary FFmpeg",
        last_checked: "2026-03-01T00:00:00Z",
      },
      {
        id: "playwright",
        name: "Playwright Chromium",
        category: "runtime",
        healthy: true,
        status: "ready",
        message: "Chromium headless sandbox sẵn sàng",
        last_checked: "2026-03-01T00:00:00Z",
      },
      {
        id: "shell",
        name: "Shell Sandbox",
        category: "runtime",
        healthy: true,
        status: "ready",
        message: "Allowlist executor an toàn",
        last_checked: "2026-03-01T00:00:00Z",
      },
      {
        id: "chromadb",
        name: "ChromaDB Vector Store",
        category: "storage",
        healthy: true,
        status: "ready",
        message: "Vector collection hoạt động",
        last_checked: "2026-03-01T00:00:00Z",
      },
      {
        id: "youtube",
        name: "YouTube Data API",
        category: "external",
        healthy: false,
        status: "disconnected",
        message: "Chưa cấu hình API key",
        last_checked: "2026-03-01T00:00:00Z",
      },
      {
        id: "telegram",
        name: "Telegram Bot",
        category: "external",
        healthy: false,
        status: "disconnected",
        message: "Chưa kết nối bot token",
        last_checked: "2026-03-01T00:00:00Z",
      },
      {
        id: "zalo",
        name: "Zalo OA",
        category: "external",
        healthy: false,
        status: "disconnected",
        message: "Chưa kết nối OA token",
        last_checked: "2026-03-01T00:00:00Z",
      },
    ];

    it("renders health badges for all 7 required connectors and calls refresh", async () => {
      const handleRefresh = vi.fn().mockResolvedValue(true);

      render(
        <ConnectorHealthList
          connectors={mockConnectors}
          onRefresh={handleRefresh}
          isLoading={false}
        />
      );

      // Verify all 7 required connectors are displayed
      expect(screen.getByText("FFmpeg Media Processor")).toBeInTheDocument();
      expect(screen.getByText("Playwright Chromium")).toBeInTheDocument();
      expect(screen.getByText("Shell Sandbox")).toBeInTheDocument();
      expect(screen.getByText("ChromaDB Vector Store")).toBeInTheDocument();
      expect(screen.getByText("YouTube Data API")).toBeInTheDocument();
      expect(screen.getByText("Telegram Bot")).toBeInTheDocument();
      expect(screen.getByText("Zalo OA")).toBeInTheDocument();

      // Click Làm mới (Refresh)
      const refreshBtn = screen.getByRole("button", { name: /Làm mới|Kiểm tra lại/i });
      fireEvent.click(refreshBtn);

      expect(handleRefresh).toHaveBeenCalled();
    });
  });

  describe("SettingsPage Integration", () => {
    it("renders 4 tabs and switches between LLM, Connectors, Profile, and Monitoring views", async () => {
      render(<SettingsPage />);

      // Verify 4 tabs are present
      expect(screen.getByRole("tab", { name: /Cấu hình AI \(LLM\)/i })).toBeInTheDocument();
      expect(screen.getByRole("tab", { name: /Kết nối & Công cụ \(Connectors\)/i })).toBeInTheDocument();
      expect(screen.getByRole("tab", { name: /Hồ sơ & Giao diện \(Profile\)/i })).toBeInTheDocument();
      expect(screen.getByRole("tab", { name: /Giám sát & Chi phí/i })).toBeInTheDocument();

      // Default tab is LLM
      expect(screen.getByText(/Quản lý API Key các nhà cung cấp mô hình AI/i)).toBeInTheDocument();

      // Switch to Connectors tab
      fireEvent.click(screen.getByRole("tab", { name: /Kết nối & Công cụ \(Connectors\)/i }));
      expect(screen.getByText(/Trạng thái kiểm tra kết nối các công cụ & runtime ngoại vi/i)).toBeInTheDocument();

      // Switch to Profile tab
      fireEvent.click(screen.getByRole("tab", { name: /Hồ sơ & Giao diện \(Profile\)/i }));
      expect(screen.getByText(/Tùy chỉnh giao diện, ngôn ngữ và hạn mức chi tiêu/i)).toBeInTheDocument();

      // Switch to Monitoring tab
      fireEvent.click(screen.getByRole("tab", { name: /Giám sát & Chi phí/i }));
      expect(screen.getByText(/Giám Sát & Chi Phí Token/i)).toBeInTheDocument();
    });
  });
});
