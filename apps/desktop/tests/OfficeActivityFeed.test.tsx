import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import React from "react";
import { OfficeKpiRibbon } from "@/components/office/OfficeKpiRibbon";
import { OfficeActivityFeed, ActivityFeedItem } from "@/components/office/OfficeActivityFeed";

describe("OfficeKpiRibbon Component", () => {
  it("renders 4 KPI metrics: Token hôm nay, Đang làm, Chờ anh (highlighted), Việc xong hôm nay", () => {
    render(
      <OfficeKpiRibbon
        tokenCount="561K"
        runningCount={2}
        waitingReviewCount={1}
        completedCount={8}
        commanderBrief="Chào anh! Đội Content đang viết 2 kịch bản, 1 việc đang chờ anh duyệt."
      />
    );

    expect(screen.getByText("Token hôm nay")).toBeInTheDocument();
    expect(screen.getByText("561K")).toBeInTheDocument();

    expect(screen.getByText("Đang làm")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();

    expect(screen.getByText("Chờ anh")).toBeInTheDocument();
    const waitingBadge = screen.getByTestId("kpi-waiting-badge");
    expect(waitingBadge).toHaveTextContent("1");
    expect(waitingBadge).toHaveClass("bg-amber-500/20");

    expect(screen.getByText("Việc xong hôm nay")).toBeInTheDocument();
    expect(screen.getByText("8")).toBeInTheDocument();

    expect(screen.getByText(/Chào anh! Đội Content đang viết 2 kịch bản/i)).toBeInTheDocument();
  });
});

describe("OfficeActivityFeed Component", () => {
  const sampleActivities: ActivityFeedItem[] = [
    {
      id: "act-1",
      agentName: "ContentWriter",
      actionType: "delivered", // "received" | "running" | "delivered" | "completed"
      time: "10:14",
      title: "Bàn giao kịch bản video TikTok 60s hook tài chính",
      deliverable: {
        name: "kich_ban_hook_tai_chinh.md",
        type: "markdown",
        content: "# Hook Tài Chính: Đừng để tiền đứng im!",
      },
    },
    {
      id: "act-2",
      agentName: "UIDesigner",
      actionType: "running",
      time: "10:12",
      title: "Đang dựng cấu trúc interactive HTML landing page",
    },
    {
      id: "act-3",
      agentName: "HookMaster",
      actionType: "completed",
      time: "10:05",
      title: "Hoàn tất 3 góc độ mở đầu video triệu view",
    },
  ];

  it("renders feed header 'Vừa làm gì' and activity items with badges", () => {
    render(<OfficeActivityFeed activities={sampleActivities} />);

    expect(screen.getByText("Vừa làm gì")).toBeInTheDocument();
    expect(screen.getByText(/Bàn giao kịch bản video TikTok 60s/i)).toBeInTheDocument();
    expect(screen.getByText(/Đang dựng cấu trúc interactive HTML/i)).toBeInTheDocument();
    expect(screen.getByText("10:14")).toBeInTheDocument();
  });

  it("opens deliverable preview modal when clicking '[Mở]' on deliverable item", () => {
    render(<OfficeActivityFeed activities={sampleActivities} />);

    const openBtns = screen.getAllByRole("button", { name: /Mở/i });
    expect(openBtns.length).toBeGreaterThan(0);
    fireEvent.click(openBtns[0]);

    expect(screen.getByTestId("activity-deliverable-modal")).toBeInTheDocument();
    expect(screen.getByText(/Hook Tài Chính: Đừng để tiền đứng im!/i)).toBeInTheDocument();
  });
});
