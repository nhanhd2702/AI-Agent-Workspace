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

  it("does not recreate WebSocket when opening drawer or receiving task_status events", async () => {
    const wsInstances: Array<{
      url: string;
      close: ReturnType<typeof vi.fn>;
      onmessage: ((e: { data: string }) => void) | null;
      onclose: (() => void) | null;
    }> = [];

    class MockWebSocket {
      url: string;
      close = vi.fn();
      onmessage: ((e: { data: string }) => void) | null = null;
      onclose: (() => void) | null = null;
      constructor(url: string) {
        this.url = url;
        wsInstances.push(this);
      }
    }

    const originalWs = global.WebSocket;
    (global as unknown as { WebSocket: typeof WebSocket }).WebSocket =
      MockWebSocket as unknown as typeof WebSocket;

    try {
      global.fetch = vi.fn().mockImplementation((url: string) => {
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
        if (url.includes("/api/v1/tasks/t-ws/logs")) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({ status: "success", data: [] }),
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
                  id: "t-ws",
                  project_id: "proj-default",
                  title: "WS Stability Task",
                  status: "running",
                  agent_name: "ContentWriter",
                  turn_count: 0,
                },
              ],
            }),
          });
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ status: "success", data: {} }) });
      });

      await act(async () => {
        render(<BoardPage />);
      });

      await waitFor(() => {
        expect(wsInstances).toHaveLength(1);
      });

      const initialWs = wsInstances[0];

      // Open drawer for the already-streamed task
      const card = screen.getByTestId("kanban-card-t-ws");
      const taskBtn = card.querySelector("button");
      await act(async () => {
        fireEvent.click(taskBtn!);
      });

      await waitFor(() => {
        expect(screen.getByText("Các Lượt")).toBeInTheDocument();
      });

      // Emit task_status WS event for selected task
      await act(async () => {
        initialWs.onmessage?.({
          data: JSON.stringify({
            event: "task_status",
            task_id: "t-ws",
            status: "waiting_review",
          }),
        });
      });

      // WebSocket must NOT have been closed or recreated
      expect(wsInstances).toHaveLength(1);
      expect(initialWs.close).not.toHaveBeenCalled();
    } finally {
      global.WebSocket = originalWs;
    }
  });

  it("ignores stale Task A logs response when Task B is selected quickly", async () => {
    let resolveTaskALogs!: (value: Response) => void;
    let resolveTaskBLogs!: (value: Response) => void;

    global.fetch = vi.fn().mockImplementation((url: string) => {
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
      if (url.includes("/api/v1/tasks/task-a/logs")) {
        return new Promise((res) => {
          resolveTaskALogs = res;
        });
      }
      if (url.includes("/api/v1/tasks/task-b/logs")) {
        return new Promise((res) => {
          resolveTaskBLogs = res;
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
              { id: "task-a", project_id: "proj-default", title: "Task Alpha", status: "running" },
              { id: "task-b", project_id: "proj-default", title: "Task Beta", status: "running" },
            ],
          }),
        });
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({ status: "success", data: {} }) });
    });

    await act(async () => {
      render(<BoardPage />);
    });

    await waitFor(() => {
      expect(screen.getByTestId("kanban-card-task-a")).toBeInTheDocument();
    });

    // Click Task A (slow) then Task B (fast)
    fireEvent.click(screen.getByTestId("kanban-card-task-a").querySelector("button")!);
    fireEvent.click(screen.getByTestId("kanban-card-task-b").querySelector("button")!);

    // Resolve Task B first
    await act(async () => {
      resolveTaskBLogs({
        ok: true,
        status: 200,
        json: async () => ({
          status: "success",
          data: [
            {
              id: "turn-b",
              log_type: "turn",
              turn_number: 1,
              agent_name: "AgentBeta",
              action: "action_b",
              duration_ms: 222,
              status: "completed",
              created_at: "2026-11-12T10:00:00+00:00",
            },
          ],
        }),
      } as unknown as Response);
    });

    await waitFor(() => {
      expect(screen.getByText("222 ms")).toBeInTheDocument();
      expect(screen.getByText("action_b")).toBeInTheDocument();
    });

    // Now resolve stale Task A response
    await act(async () => {
      resolveTaskALogs({
        ok: true,
        status: 200,
        json: async () => ({
          status: "success",
          data: [
            {
              id: "turn-a",
              log_type: "turn",
              turn_number: 1,
              agent_name: "AgentAlpha",
              action: "stale_action_a",
              duration_ms: 999,
              status: "completed",
              created_at: "2026-11-12T10:00:00+00:00",
            },
          ],
        }),
      } as unknown as Response);
    });

    // Task B logs must still be displayed; stale Task A logs must NOT overwrite
    expect(screen.getByText("222 ms")).toBeInTheDocument();
    expect(screen.getByText("action_b")).toBeInTheDocument();
    expect(screen.queryByText("999 ms")).not.toBeInTheDocument();
    expect(screen.queryByText("stale_action_a")).not.toBeInTheDocument();
  });

  it("shows visible error banner with Retry button on loadBoardData failure and uses empty list when backend returns []", async () => {
    let shouldFail = true;
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (shouldFail) {
        return Promise.resolve({
          ok: false,
          status: 500,
          json: async () => ({ detail: "Internal Server Error" }),
        });
      }
      if (url.includes("/api/v1/projects") || url.includes("/api/v1/tasks")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ status: "success", data: [] }),
        });
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({ status: "success", data: [] }) });
    });

    await act(async () => {
      render(<BoardPage />);
    });

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/Internal Server Error/i);
    });
    // Should NOT silently inject demo tasks when backend fails
    expect(screen.queryByText(/Soạn kịch bản TikTok 60s/i)).not.toBeInTheDocument();

    const retryBtn = screen.getByRole("button", { name: /thử lại/i });
    shouldFail = false;
    await act(async () => {
      fireEvent.click(retryBtn);
    });

    await waitFor(() => {
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });
    expect(screen.getByText("0 công việc")).toBeInTheDocument();
  });
});
