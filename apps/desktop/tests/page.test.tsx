import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";
import React from "react";
import HomePage from "@/app/page";

describe("HomePage Integration Tests", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders workspace shell, sidebar, and prompt box without crashing in offline fallback", async () => {
    // Mock fetch to simulate offline / backend not running
    global.fetch = vi.fn().mockRejectedValue(new Error("Connection refused"));

    await act(async () => {
      render(<HomePage />);
    });

    expect(screen.getByText("Văn Phòng AI (AI Agent Workspace)")).toBeInTheDocument();
    expect(screen.getByText("Tạo task mới")).toBeInTheDocument();
    expect(screen.getAllByText(/Tổng hành dinh/i).length).toBeGreaterThan(0);
    expect(screen.getByText("Hôm nay bạn muốn hoàn thành việc gì?")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText(/chế độ cục bộ \(offline\)/i)).toBeInTheDocument();
    });

    // Submitting prompt in offline mode creates a local task cleanly
    const input = screen.getByRole("textbox");
    act(() => {
      fireEvent.change(input, { target: { value: "Viết bài review công nghệ mới" } });
    });

    const submitBtn = screen.getByRole("button", { name: /gửi/i });
    await act(async () => {
      fireEvent.click(submitBtn);
    });

    await waitFor(() => {
      expect(screen.getByText(/chế độ ngoại tuyến/i)).toBeInTheDocument();
    });

    expect(screen.getByText("Viết bài review công nghệ mới")).toBeInTheDocument();
  });

  it("fetches agents and updates status when backend is online", async () => {
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/api/v1/health")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ status: "ok", service: "ai-agent-workspace-backend", version: "0.1.0" }),
        });
      }
      if (url.includes("/api/v1/agents")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            status: "success",
            data: [
              { id: "agent-growth", name: "GrowthAdvisor", display_name: "Growth Advisor", role: "Tư vấn tăng trưởng" },
            ],
          }),
        });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({ status: "success", data: {} }),
      });
    });

    await act(async () => {
      render(<HomePage />);
    });

    await waitFor(() => {
      expect(screen.getByText(/backend 8765 sẵn sàng/i)).toBeInTheDocument();
    });

    expect(screen.getByText("1 Agent")).toBeInTheDocument();
  });
});
