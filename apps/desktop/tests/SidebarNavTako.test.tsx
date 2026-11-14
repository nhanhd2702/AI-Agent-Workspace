import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import React from "react";
import { SidebarNav } from "@/components/layout/SidebarNav";

describe("SidebarNav Tako Standard", () => {
  const sampleTasks = [
    {
      id: "task-1",
      title: "Tôi muốn xây kênh chia sẻ marketing",
      group: "today" as const,
      status: "running" as const,
      agentId: "DeepResearcher",
    },
    {
      id: "task-2",
      title: "Viết kịch bản quảng cáo AI Agent Tako",
      group: "today" as const,
      status: "done" as const,
      agentId: "ContentWriter",
    },
    {
      id: "task-3",
      title: "Thiết kế Landing Page phễu bán hàng",
      group: "yesterday" as const,
      status: "awaiting_review" as const,
      agentId: "UIDesigner",
    },
  ];

  it("renders search bar with ⌘K shortcut and [+] Tạo task mới button", () => {
    const onNewTask = vi.fn();
    render(<SidebarNav onNewTask={onNewTask} />);

    expect(screen.getByPlaceholderText(/Tìm kiếm/i)).toBeInTheDocument();
    expect(screen.getByText("⌘K")).toBeInTheDocument();

    const newTaskBtn = screen.getByRole("button", { name: /Tạo task mới/i });
    expect(newTaskBtn).toBeInTheDocument();
    fireEvent.click(newTaskBtn);
    expect(onNewTask).toHaveBeenCalledTimes(1);
  });

  it("renders the 5 standard Tako menu items with proper links and badges", () => {
    render(<SidebarNav officeBadge={2} brainBadge={1} />);

    expect(screen.getByText("Văn phòng AI")).toBeInTheDocument();
    expect(screen.getByText("Tự động")).toBeInTheDocument();
    expect(screen.getByText("Thư viện")).toBeInTheDocument();
    expect(screen.getByText("Brain")).toBeInTheDocument();
    expect(screen.getByText("Hội thoại khách")).toBeInTheDocument();

    // Badges
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
  });

  it("renders tasks grouped by time with distinct Chibi avatar indicators", () => {
    const onSelectTask = vi.fn();
    render(
      <SidebarNav
        tasks={sampleTasks}
        selectedTaskId="task-1"
        onSelectTask={onSelectTask}
      />
    );

    expect(screen.getByText("Hôm nay")).toBeInTheDocument();
    expect(screen.getByText("Hôm qua")).toBeInTheDocument();
    expect(screen.getByText(/Tôi muốn xây kênh chia sẻ marketing/i)).toBeInTheDocument();
    expect(screen.getByText(/Viết kịch bản quảng cáo AI Agent/i)).toBeInTheDocument();

    // Check click task item
    const task2 = screen.getByText(/Viết kịch bản quảng cáo AI Agent/i);
    fireEvent.click(task2);
    expect(onSelectTask).toHaveBeenCalledWith("task-2");
  });

  it("renders settings and footer utilities", () => {
    render(<SidebarNav />);
    expect(screen.getByText("Cài đặt")).toBeInTheDocument();
  });
});
