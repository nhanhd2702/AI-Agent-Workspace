import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import HomePage from "@/app/page";

// Mock the API client
vi.mock("@/lib/apiClient", () => {
  return {
    ApiClient: vi.fn().mockImplementation(() => ({
      checkHealth: vi.fn().mockResolvedValue({ status: "ok" }),
      listAgents: vi.fn().mockResolvedValue([
        { id: "agent-1", name: "ContentWriter", role: "Sáng tạo nội dung", status: "idle" },
      ]),
      listTasks: vi.fn().mockResolvedValue([
        { id: "task-1", title: "Nghiên cứu thị trường AI Agents 2026", status: "completed" },
      ]),
      createTask: vi.fn().mockResolvedValue({ id: "task-new", title: "Task Mới", status: "queued" }),
      executeTask: vi.fn().mockResolvedValue({ status: "executing" }),
      streamMediaUrl: vi.fn().mockReturnValue("http://localhost:8765/media/1"),
    })),
  };
});

describe("HomePage - 3-Column Split-Screen (TAKO Architecture)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders 3 columns simultaneously: Column 1 (Sidebar), Column 2 (Chat Feed & Omnibar), Column 3 (Task Details)", async () => {
    render(<HomePage />);

    // Column 1: Sidebar Nav items
    expect(screen.getByText("Văn phòng AI")).toBeInTheDocument();
    expect(screen.getByText("Tự động")).toBeInTheDocument();
    expect(screen.getByText("Thư viện")).toBeInTheDocument();
    expect(screen.getByText("Brain")).toBeInTheDocument();
    expect(screen.getByText("Hội thoại khách")).toBeInTheDocument();

    // Column 2: Omnibar in center
    expect(screen.getByPlaceholderText(/Hôm nay bạn muốn hoàn thành việc gì/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Gửi lệnh/i })).toBeInTheDocument();

    // Column 3: Task Details Panel on right
    expect(screen.getByRole("tab", { name: /^Việc$/i })).toBeInTheDocument();
    expect(screen.getByText(/DÒNG CÔNG VIỆC/i)).toBeInTheDocument();
  });

  it("submits prompt from Omnibar and updates chat feed", async () => {
    render(<HomePage />);

    const omnibarInput = screen.getByPlaceholderText(/Hôm nay bạn muốn hoàn thành việc gì/i);
    fireEvent.change(omnibarInput, { target: { value: "Viết kịch bản TikTok mới" } });

    const sendBtn = screen.getByRole("button", { name: /Gửi lệnh/i });
    fireEvent.click(sendBtn);

    await waitFor(() => {
      expect(screen.getAllByText("Viết kịch bản TikTok mới").length).toBeGreaterThan(0);
    });
  });
});
