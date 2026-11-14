import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import React from "react";
import { ActionCollapseBox, ActionItem } from "@/components/chat/ActionCollapseBox";
import { HumanDecisionCard } from "@/components/chat/HumanDecisionCard";

describe("ActionCollapseBox Component", () => {
  const sampleActions: ActionItem[] = [
    {
      id: "act-1",
      title: "Quét cấu trúc dự án & thư viện Next.js",
      durationMs: 44,
      status: "completed",
      detail: "Read package.json, src/app/layout.tsx, tailwind.config.js",
    },
    {
      id: "act-2",
      title: "Gọi API phân tích từ khóa đối thủ qua SerpApi",
      durationMs: 89,
      status: "completed",
      detail: "GET https://api.serp.example/v1/search?q=ai+agents+2026",
    },
    {
      id: "act-3",
      title: "Biên soạn dàn bài 5 phần cho Landing Page",
      durationMs: 1200,
      status: "completed",
      detail: "Generate 5 sections: Hero, Problem, Solution, Pricing, FAQ",
    },
  ];

  it("renders summary showing total operations and total duration badge", () => {
    render(<ActionCollapseBox actions={sampleActions} isRunning={false} />);

    expect(screen.getByText(/3 thao tác/i)).toBeInTheDocument();
    expect(screen.getByText(/1.3s/i)).toBeInTheDocument(); // total ~1333ms -> 1.3s
  });

  it("toggles collapse to show each individual action with duration in ms", () => {
    render(<ActionCollapseBox actions={sampleActions} isRunning={false} />);

    // Initially collapsed
    expect(screen.queryByText("Quét cấu trúc dự án & thư viện Next.js")).not.toBeInTheDocument();

    // Click toggle button
    const toggleBtn = screen.getByRole("button", { name: /chi tiết/i });
    fireEvent.click(toggleBtn);

    // Now actions should be visible
    expect(screen.getByText("Quét cấu trúc dự án & thư viện Next.js")).toBeInTheDocument();
    expect(screen.getByText("44ms")).toBeInTheDocument();
    expect(screen.getByText("89ms")).toBeInTheDocument();
    expect(screen.getByText("1.2s")).toBeInTheDocument();
  });

  it("shows spinner when isRunning is true", () => {
    render(<ActionCollapseBox actions={sampleActions} isRunning={true} />);

    expect(screen.getByTestId("action-spinner")).toBeInTheDocument();
  });
});

describe("HumanDecisionCard Component", () => {
  it("renders decision gate prompt, credit cost warning and action buttons", () => {
    const onApprove = vi.fn();
    const onModify = vi.fn();

    render(
      <HumanDecisionCard
        title="Xác nhận tiếp tục phân tích chuyên sâu"
        description="Đã dùng hết 1.2/2.0 credit dùng thử. Cho phép tác tử chạy thêm 10 bước chuyên sâu?"
        estimatedCredits={0.8}
        onApprove={onApprove}
        onModify={onModify}
      />
    );

    expect(screen.getByText("Xác nhận tiếp tục phân tích chuyên sâu")).toBeInTheDocument();
    expect(screen.getByText(/Đã dùng hết 1.2\/2.0 credit/i)).toBeInTheDocument();
    expect(screen.getByText(/0.8 credit/i)).toBeInTheDocument();

    const approveBtn = screen.getByRole("button", { name: /Đồng ý cho chạy tiếp/i });
    fireEvent.click(approveBtn);
    expect(onApprove).toHaveBeenCalledTimes(1);

    const modifyBtn = screen.getByRole("button", { name: /Chỉnh sửa yêu cầu/i });
    fireEvent.click(modifyBtn);
    expect(onModify).toHaveBeenCalledTimes(1);
  });
});
