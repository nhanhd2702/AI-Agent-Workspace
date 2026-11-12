import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import { KanbanBoard } from "@/components/board/KanbanBoard";

describe("KanbanBoard", () => {
  it("renders 5 Vietnamese status columns and reverts invalid drag transition", async () => {
    const onMoveTask = vi.fn();
    render(
      <KanbanBoard
        tasks={[{ id: "t1", title: "Task 1", status: "running", agentName: "ContentWriter" }]}
        onMoveTask={onMoveTask}
      />
    );

    expect(screen.getByText("Chờ")).toBeInTheDocument();
    expect(screen.getByText("Đang làm")).toBeInTheDocument();
    expect(screen.getByText("Chờ duyệt")).toBeInTheDocument();
    expect(screen.getByText("Đã bàn giao")).toBeInTheDocument();
    expect(screen.getByText("Hoàn tất")).toBeInTheDocument();
    expect(screen.getByText("Task 1")).toBeInTheDocument();
    expect(screen.getByText("@ContentWriter")).toBeInTheDocument();

    // Attempt invalid drag transition: running -> pending ("Chờ")
    const card = screen.getByTestId("kanban-card-t1");
    const pendingColumn = screen.getByTestId("kanban-column-pending");

    fireEvent.dragStart(card);
    fireEvent.dragOver(pendingColumn);
    fireEvent.drop(pendingColumn);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });

    // Card remains inside Đang làm (running), not moved to Chờ (pending)
    const runningColumn = screen.getByTestId("kanban-column-running");
    expect(runningColumn).toHaveTextContent("Task 1");
    expect(pendingColumn).not.toHaveTextContent("Task 1");
    expect(onMoveTask).not.toHaveBeenCalled();
  });

  it("reverts optimistic move when onMoveTask rejects", async () => {
    const onMoveTask = vi.fn().mockRejectedValue(new Error("409 Conflict: Invalid transition"));
    render(
      <KanbanBoard
        tasks={[{ id: "t2", title: "Task 2", status: "running", agentName: "UIDesigner" }]}
        onMoveTask={onMoveTask}
      />
    );

    const select = screen.getByLabelText("Chuyển trạng thái cho Task 2");
    fireEvent.change(select, { target: { value: "waiting_review" } });

    await waitFor(() => {
      expect(onMoveTask).toHaveBeenCalledWith("t2", "waiting_review");
    });

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/409 Conflict/i);
    });

    const runningColumn = screen.getByTestId("kanban-column-running");
    expect(runningColumn).toHaveTextContent("Task 2");
  });

  it("toggles between Kanban and List view and opens task details", () => {
    const onSelectTask = vi.fn();
    render(
      <KanbanBoard
        tasks={[
          { id: "t1", title: "Alpha Task", status: "pending", agentName: "Commander" },
          { id: "t2", title: "Beta Task", status: "waiting_review", agentName: "ContentWriter" },
        ]}
        onMoveTask={vi.fn()}
        onSelectTask={onSelectTask}
      />
    );

    const listBtn = screen.getByRole("button", { name: /danh sách/i });
    fireEvent.click(listBtn);

    expect(screen.getByTestId("task-list-view")).toBeInTheDocument();
    expect(screen.getByText("Alpha Task")).toBeInTheDocument();
    expect(screen.getByText("Beta Task")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Beta Task"));
    expect(onSelectTask).toHaveBeenCalledWith(expect.objectContaining({ id: "t2" }));
  });

  it("reverts ONLY the failed card without clobbering concurrent moves or other card states", async () => {
    let rejectMoveA!: (reason?: unknown) => void;
    let resolveMoveB!: () => void;

    const onMoveTask = vi.fn().mockImplementation((taskId: string) => {
      if (taskId === "tA") {
        return new Promise((_res, rej) => {
          rejectMoveA = rej;
        });
      }
      return new Promise<void>((res) => {
        resolveMoveB = res;
      });
    });

    render(
      <KanbanBoard
        tasks={[
          { id: "tA", title: "Task A", status: "running", agentName: "ContentWriter" },
          { id: "tB", title: "Task B", status: "running", agentName: "UIDesigner" },
        ]}
        onMoveTask={onMoveTask}
      />
    );

    const selectA = screen.getByLabelText("Chuyển trạng thái cho Task A");
    const selectB = screen.getByLabelText("Chuyển trạng thái cho Task B");

    // Start moving Task A (will fail later) and Task B (will succeed) concurrently
    fireEvent.change(selectA, { target: { value: "waiting_review" } });
    fireEvent.change(selectB, { target: { value: "delivered" } });

    await waitFor(() => {
      expect(onMoveTask).toHaveBeenCalledWith("tA", "waiting_review");
      expect(onMoveTask).toHaveBeenCalledWith("tB", "delivered");
    });

    // Resolve Task B first
    resolveMoveB();

    // Reject Task A
    rejectMoveA(new Error("409 Conflict on Task A"));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("409 Conflict on Task A");
    });

    // Task A reverted to running (Đang làm), while Task B stays in delivered (Đã bàn giao)
    expect(screen.getByTestId("kanban-column-running")).toHaveTextContent("Task A");
    expect(screen.getByTestId("kanban-column-delivered")).toHaveTextContent("Task B");
  });

  it("allows resuming paused -> running and advancing approved -> delivered via select", async () => {
    const onMoveTask = vi.fn().mockResolvedValue(undefined);
    render(
      <KanbanBoard
        tasks={[
          { id: "t-paused", title: "Paused Task", status: "paused", agentName: "ContentWriter" },
          { id: "t-approved", title: "Approved Task", status: "approved", agentName: "UIDesigner" },
        ]}
        onMoveTask={onMoveTask}
      />
    );

    const pausedSelect = screen.getByLabelText("Chuyển trạng thái cho Paused Task");
    fireEvent.change(pausedSelect, { target: { value: "running" } });

    const approvedSelect = screen.getByLabelText("Chuyển trạng thái cho Approved Task");
    fireEvent.change(approvedSelect, { target: { value: "delivered" } });

    await waitFor(() => {
      expect(onMoveTask).toHaveBeenCalledWith("t-paused", "running");
      expect(onMoveTask).toHaveBeenCalledWith("t-approved", "delivered");
    });
  });
});
