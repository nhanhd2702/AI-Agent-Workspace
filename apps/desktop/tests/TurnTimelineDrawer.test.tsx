import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import React from "react";
import { TurnTimelineDrawer } from "@/components/board/TurnTimelineDrawer";

describe("TurnTimelineDrawer", () => {
  it("renders chronological turns and expands hidden steps with 'Xem thêm X bước'", () => {
    const onClose = vi.fn();
    render(
      <TurnTimelineDrawer
        isOpen={true}
        task={{ id: "t1", title: "Viết kịch bản video", status: "running", agentName: "ContentWriter" }}
        logs={[
          {
            id: "turn-1",
            logType: "turn",
            turnNumber: 1,
            agentName: "ContentWriter",
            action: "draft_script",
            tool: "llm_router",
            status: "completed",
            durationMs: 350,
            tokens: 1200,
            createdAt: "2026-11-12T10:00:00+00:00",
            steps: [
              { name: "Bước 1: Đọc brief", status: "completed" },
              { name: "Bước 2: Phân tích hook", status: "completed" },
              { name: "Bước 3: Viết thân bài", status: "completed" },
              { name: "Bước 4: Rà soát CTA", status: "completed" },
              { name: "Bước 5: Xuất bản nháp", status: "completed" },
            ],
          },
        ]}
        onClose={onClose}
      />
    );

    expect(screen.getByText("Các Lượt")).toBeInTheDocument();
    expect(screen.getByText("Viết kịch bản video")).toBeInTheDocument();
    expect(screen.getByText("350 ms")).toBeInTheDocument();
    expect(screen.getByText("1,200 tokens")).toBeInTheDocument();

    expect(screen.getByText("Bước 1: Đọc brief")).toBeInTheDocument();
    expect(screen.getByText("Bước 2: Phân tích hook")).toBeInTheDocument();
    expect(screen.queryByText("Bước 3: Viết thân bài")).not.toBeInTheDocument();

    const expandBtn = screen.getByRole("button", { name: /xem thêm 3 bước/i });
    fireEvent.click(expandBtn);

    expect(screen.getByText("Bước 3: Viết thân bài")).toBeInTheDocument();
    expect(screen.getByText("Bước 5: Xuất bản nháp")).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("tracks step and payload expansion independently when log entry id is empty", () => {
    render(
      <TurnTimelineDrawer
        isOpen={true}
        task={{ id: "t2", title: "No ID Logs", status: "running" }}
        logs={[
          {
            id: "",
            logType: "turn",
            turnNumber: 1,
            agentName: "AgentOne",
            steps: [
              { name: "First A", status: "completed" },
              { name: "First B", status: "completed" },
              { name: "First Hidden Step", status: "completed" },
            ],
            inputPayload: { hello: "one" },
          },
          {
            id: "",
            logType: "turn",
            turnNumber: 2,
            agentName: "AgentTwo",
            steps: [
              { name: "Second A", status: "completed" },
              { name: "Second B", status: "completed" },
              { name: "Second Hidden Step", status: "completed" },
            ],
            inputPayload: { hello: "two" },
          },
        ]}
        onClose={vi.fn()}
      />
    );

    const expandBtns = screen.getAllByRole("button", { name: /xem thêm 1 bước/i });
    expect(expandBtns).toHaveLength(2);
    fireEvent.click(expandBtns[0]);

    expect(screen.getByText("First Hidden Step")).toBeInTheDocument();
    expect(screen.queryByText("Second Hidden Step")).not.toBeInTheDocument();
  });
});
