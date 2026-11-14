import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import React from "react";
import { TaskDetailsPanel, TaskDetailsData } from "@/components/chat/TaskDetailsPanel";

describe("TaskDetailsPanel Component", () => {
  const sampleTask: TaskDetailsData = {
    id: "task-101",
    title: "Thiết kế Landing Page khóa học Solopreneur",
    description: "Xây dựng phễu trang đích chuyển đổi cao tặng cẩm nang kinh doanh solo",
    currentStage: "in_progress", // "in_progress" | "delivered" | "waiting_human" | "approved" | "published"
    workflow: [
      { step: 1, agentName: "GrowthAdvisor", role: "Định vị & USP", status: "completed" },
      { step: 2, agentName: "ContentWriter", role: "Soạn kịch bản & nội dung", status: "in_progress" },
      { step: 3, agentName: "UIDesigner", role: "Thiết kế Interactive Web", status: "pending" },
    ],
    deliverables: [
      {
        id: "del-1",
        name: "landing_page_solopreneur.html",
        type: "html",
        size: "42 KB",
        content: "<!DOCTYPE html><html><body><h1>Khóa học Solopreneur</h1></body></html>",
      },
      {
        id: "del-2",
        name: "kich_ban_hook_video.md",
        type: "markdown",
        size: "4.8 KB",
        content: "# 5 Hook Video TikTok\n1. Bạn đang làm việc 14 tiếng/ngày?",
      },
    ],
    files: [
      { name: "brand_guideline.pdf", size: "1.2 MB", uploadedAt: "10:30" },
      { name: "logo_dark.png", size: "240 KB", uploadedAt: "10:32" },
    ],
    browserPages: [
      { id: "page-1", title: "Preview: Localhost 3000", url: "http://localhost:3000/preview" },
    ],
  };

  it("renders 3 top tabs: Việc, Tệp (N), Trình duyệt (M)", () => {
    render(<TaskDetailsPanel task={sampleTask} />);

    expect(screen.getByRole("tab", { name: /^Việc$/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Tệp \(2\)/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Trình duyệt \(1\)/i })).toBeInTheDocument();
  });

  it("renders 5-stage progress ribbon with current stage highlighted", () => {
    render(<TaskDetailsPanel task={sampleTask} />);

    expect(screen.getAllByText("Đang làm").length).toBeGreaterThan(0);
    expect(screen.getByText("Đã bàn giao")).toBeInTheDocument();
    expect(screen.getByText("Chờ anh")).toBeInTheDocument();
    expect(screen.getByText("Đã duyệt")).toBeInTheDocument();
    expect(screen.getByText("Đã đăng")).toBeInTheDocument();
  });

  it("renders DÒNG CÔNG VIỆC pipeline and agents", () => {
    render(<TaskDetailsPanel task={sampleTask} />);

    expect(screen.getByText("DÒNG CÔNG VIỆC")).toBeInTheDocument();
    expect(screen.getByText("GrowthAdvisor")).toBeInTheDocument();
    expect(screen.getByText("ContentWriter")).toBeInTheDocument();
    expect(screen.getByText("UIDesigner")).toBeInTheDocument();
  });

  it("renders BÀN GIAO deliverables and opens preview on clicking 'Mở'", () => {
    render(<TaskDetailsPanel task={sampleTask} />);

    expect(screen.getByText("BÀN GIAO")).toBeInTheDocument();
    expect(screen.getByText("landing_page_solopreneur.html")).toBeInTheDocument();

    const openBtns = screen.getAllByRole("button", { name: /Mở/i });
    expect(openBtns.length).toBeGreaterThan(0);
    fireEvent.click(openBtns[0]);

    // Check that HtmlSandboxViewer preview modal or container is opened
    expect(screen.getByTestId("html-sandbox-preview")).toBeInTheDocument();
  });

  it("switches to Tệp tab and displays file list", () => {
    render(<TaskDetailsPanel task={sampleTask} />);

    const filesTab = screen.getByRole("tab", { name: /Tệp \(2\)/i });
    fireEvent.click(filesTab);

    expect(screen.getByText("brand_guideline.pdf")).toBeInTheDocument();
    expect(screen.getByText("logo_dark.png")).toBeInTheDocument();
  });
});
