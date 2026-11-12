import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import React from "react";
import BoardPage from "@/app/board/page";

describe("BoardPage Integration Tests", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("loads projects and tasks, opens TurnTimelineDrawer with logs, and calls PATCH /state", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      if (url.includes("/api/v1/projects")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            status: "success",
            data: [{ id: "proj-default", name: "Văn phòng Mặc định" }],
          }),
        });
      }
      if (url.includes("/api/v1/tasks/t-live/logs")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            status: "success",
            data: [
              {
                id: "turn-live-1",
                log_type: "turn",
                turn_number: 1,
                agent_name: "ContentWriter",
                action: "write_hook",
                tool: "llm_router",
                duration_ms: 180,
                tokens: 500,
                status: "completed",
                steps: [
                  { name: "Step A", status: "completed" },
                  { name: "Step B", status: "completed" },
                  { name: "Step C", status: "completed" },
                ],
                created_at: "2026-11-12T10:00:00+00:00",
              },
            ],
          }),
        });
      }
      if (url.includes("/api/v1/tasks/t-live/state") && init?.method === "PATCH") {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            status: "success",
            data: {
              id: "t-live",
              project_id: "proj-default",
              title: "Viết bài PR sản phẩm",
              status: "waiting_review",
              agent_name: "ContentWriter",
              turn_count: 1,
            },
          }),
        });
      }
      if (url.includes("/api/v1/reviews")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ status: "success", data: [] }),
        });
      }
      if (url.includes("/api/v1/tasks")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            status: "success",
            data: [
              {
                id: "t-live",
                project_id: "proj-default",
                title: "Viết bài PR sản phẩm",
                status: "running",
                agent_name: "ContentWriter",
                turn_count: 1,
              },
            ],
          }),
        });
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({ status: "success", data: {} }) });
    });

    global.fetch = fetchMock;

    await act(async () => {
      render(<BoardPage />);
    });

    await waitFor(() => {
      expect(screen.getAllByText("Viết bài PR sản phẩm").length).toBeGreaterThanOrEqual(1);
    });

    // Click task title inside Kanban card to open TurnTimelineDrawer
    const card = screen.getByTestId("kanban-card-t-live");
    const taskTitleBtn = card.querySelector("button");
    expect(taskTitleBtn).not.toBeNull();
    fireEvent.click(taskTitleBtn!);

    await waitFor(() => {
      expect(screen.getByText("Các Lượt")).toBeInTheDocument();
      expect(screen.getByText("180 ms")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /xem thêm 1 bước/i })).toBeInTheDocument();
    });

    // Move task via accessible select
    const select = screen.getByLabelText("Chuyển trạng thái cho Viết bài PR sản phẩm");
    fireEvent.change(select, { target: { value: "waiting_review" } });

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/tasks/t-live/state"),
        expect.objectContaining({ method: "PATCH" })
      );
    });
  });
});
