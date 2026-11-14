import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";
import React from "react";
import HomePage from "@/app/page";

describe("HomePage Integration Tests", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders workspace shell, 5 Tako menus, and backend status indicator", async () => {
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/api/v1/health")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ status: "ok", service: "ai-agent-workspace-backend", version: "0.1.0" }),
        });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({ status: "success", data: [] }),
      });
    });

    await act(async () => {
      render(<HomePage />);
    });

    expect(screen.getByText("Tạo task mới")).toBeInTheDocument();
    expect(screen.getByText("Văn phòng AI")).toBeInTheDocument();
    expect(screen.getByText("Tự động")).toBeInTheDocument();
    expect(screen.getByText("Thư viện")).toBeInTheDocument();
    expect(screen.getByText("Brain")).toBeInTheDocument();
    expect(screen.getByText("Hội thoại khách")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText(/backend 8765 sẵn sàng/i)).toBeInTheDocument();
    });
  });

  it("handles offline backend gracefully by displaying Backend Offline badge", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("Connection refused"));

    await act(async () => {
      render(<HomePage />);
    });

    await waitFor(() => {
      expect(screen.getByText(/backend offline/i)).toBeInTheDocument();
    });
  });
});
