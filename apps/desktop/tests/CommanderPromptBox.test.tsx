import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import React from "react";
import { CommanderPromptBox } from "@/components/chat/CommanderPromptBox";
import { SidebarNav } from "@/components/layout/SidebarNav";
import { ApiClient } from "@/lib/apiClient";
import { ApiError } from "@/lib/types";

describe("CommanderPromptBox & Workspace Shell Tests", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("Brief base test case", () => {
    it("disables submit over 2000 chars and opens @mention menu on @", () => {
      const onSubmit = vi.fn();
      render(
        <CommanderPromptBox
          agents={[{ id: "1", name: "ContentWriter", displayName: "ContentWriter", role: "Writer", status: "idle" }]}
          onSubmit={onSubmit}
        />
      );
      const input = screen.getByRole("textbox");
      act(() => {
        fireEvent.change(input, { target: { value: "@" } });
      });
      expect(screen.getByText("ContentWriter")).toBeInTheDocument();
      act(() => {
        fireEvent.change(input, { target: { value: "x".repeat(2001) } });
      });
      expect(screen.getByRole("button", { name: /gửi/i })).toBeDisabled();
    });
  });

  describe("Validation & Empty submit handling", () => {
    it("disables submit button when input is empty or only whitespace", () => {
      const onSubmit = vi.fn();
      render(<CommanderPromptBox onSubmit={onSubmit} />);
      const submitBtn = screen.getByRole("button", { name: /gửi/i });
      expect(submitBtn).toBeDisabled();

      const input = screen.getByRole("textbox");
      act(() => {
        fireEvent.change(input, { target: { value: "    " } });
      });
      expect(submitBtn).toBeDisabled();

      act(() => {
        fireEvent.change(input, { target: { value: "Viết bài Facebook mới" } });
      });
      expect(submitBtn).not.toBeDisabled();
    });

    it("displays character counter and shows limit warning when exceeding 2000 chars", () => {
      render(<CommanderPromptBox />);
      const input = screen.getByRole("textbox");
      act(() => {
        fireEvent.change(input, { target: { value: "Xin chào" } });
      });
      expect(screen.getByText("8 / 2000")).toBeInTheDocument();

      act(() => {
        fireEvent.change(input, { target: { value: "a".repeat(2001) } });
      });
      expect(screen.getByText("2001 / 2000")).toBeInTheDocument();
      expect(screen.getByText(/giới hạn 2.000 ký tự/i)).toBeInTheDocument();
    });
  });

  describe("@mention autocomplete popover", () => {
    const agents = [
      { id: "1", name: "ContentWriter", displayName: "Content Writer", role: "Content Creator", status: "idle" },
      { id: "2", name: "UIDesigner", display_name: "UI Designer", role: "Design Specialist", status: "idle" },
      { id: "3", name: "DeepResearcher", displayName: "Deep Researcher", role: "Research Analyst", status: "idle" },
    ];

    it("filters agents case-insensitively and handles both displayName and display_name", () => {
      render(<CommanderPromptBox agents={agents} />);
      const input = screen.getByRole("textbox");

      act(() => {
        fireEvent.change(input, { target: { value: "@ui" } });
      });
      expect(screen.getByText("UI Designer")).toBeInTheDocument();
      expect(screen.queryByText("Deep Researcher")).not.toBeInTheDocument();
    });

    it("supports keyboard navigation ArrowDown/ArrowUp, Enter to select, and Escape to dismiss", () => {
      render(<CommanderPromptBox agents={agents} />);
      const input = screen.getByRole("textbox");

      act(() => {
        fireEvent.change(input, { target: { value: "@" } });
      });
      expect(screen.getByText("Content Writer")).toBeInTheDocument();

      // Press ArrowDown to move to second item (UIDesigner)
      act(() => {
        fireEvent.keyDown(input, { key: "ArrowDown" });
      });
      // Press Enter to select
      act(() => {
        fireEvent.keyDown(input, { key: "Enter" });
      });

      // Should insert @UIDesigner into the prompt
      expect(input).toHaveValue("@UIDesigner ");
      // Popover should close
      expect(screen.queryByText("UI Designer")).not.toBeInTheDocument();

      // Test Escape dismissal
      act(() => {
        fireEvent.change(input, { target: { value: "@UIDesigner @deep" } });
      });
      expect(screen.getByText("Deep Researcher")).toBeInTheDocument();
      act(() => {
        fireEvent.keyDown(input, { key: "Escape" });
      });
      expect(screen.queryByText("Deep Researcher")).not.toBeInTheDocument();
    });

    it("inserts agent name when clicked from autocomplete popover", () => {
      render(<CommanderPromptBox agents={agents} />);
      const input = screen.getByRole("textbox");

      act(() => {
        fireEvent.change(input, { target: { value: "Nhờ @cont" } });
      });
      const item = screen.getByText("Content Writer");
      act(() => {
        fireEvent.click(item);
      });

      expect(input).toHaveValue("Nhờ @ContentWriter ");
    });
  });

  describe("File Attachments & 10 file limit", () => {
    it("attaches files and enforces <= 10 limit with error feedback", () => {
      render(<CommanderPromptBox />);

      const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
      expect(fileInput).toBeTruthy();

      // Create 11 mock files
      const files = Array.from({ length: 11 }, (_, i) => new File([`content ${i}`], `file_${i + 1}.pdf`, { type: "application/pdf" }));

      act(() => {
        fireEvent.change(fileInput, { target: { files } });
      });

      // Error banner / text should show max 10 attachments warning
      expect(screen.getByText(/tối đa 10 tệp/i)).toBeInTheDocument();

      // Only 10 files should be retained
      expect(screen.getByText("file_1.pdf")).toBeInTheDocument();
      expect(screen.getByText("file_10.pdf")).toBeInTheDocument();
      expect(screen.queryByText("file_11.pdf")).not.toBeInTheDocument();
    });

    it("allows removing attached files", () => {
      render(<CommanderPromptBox />);
      const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
      const file = new File(["test data"], "brief.md", { type: "text/markdown" });

      act(() => {
        fireEvent.change(fileInput, { target: { files: [file] } });
      });
      expect(screen.getByText("brief.md")).toBeInTheDocument();

      const removeBtn = screen.getByRole("button", { name: /xóa brief\.md/i });
      act(() => {
        fireEvent.click(removeBtn);
      });

      expect(screen.queryByText("brief.md")).not.toBeInTheDocument();
    });
  });

  describe("Auto-pilot vs Co-pilot Mode Toggle", () => {
    it("defaults to copilot and allows toggling to autopilot on submit", async () => {
      const onSubmit = vi.fn();
      render(<CommanderPromptBox onSubmit={onSubmit} />);

      const input = screen.getByRole("textbox");
      act(() => {
        fireEvent.change(input, { target: { value: "Lập kế hoạch nội dung tuần này" } });
      });

      // Default submit is copilot
      const submitBtn = screen.getByRole("button", { name: /gửi/i });
      await act(async () => {
        fireEvent.click(submitBtn);
      });
      expect(onSubmit).toHaveBeenCalledWith(
        expect.objectContaining({
          prompt: "Lập kế hoạch nội dung tuần này",
          mode: "copilot",
        })
      );

      // Re-enter prompt for second submission with autopilot
      act(() => {
        fireEvent.change(input, { target: { value: "Lập kế hoạch nội dung tuần này" } });
      });

      // Toggle to Auto-pilot (Rảnh tay)
      const autopilotBtn = screen.getByRole("button", { name: /rảnh tay/i });
      act(() => {
        fireEvent.click(autopilotBtn);
      });

      await act(async () => {
        fireEvent.click(submitBtn);
      });
      expect(onSubmit).toHaveBeenCalledWith(
        expect.objectContaining({
          prompt: "Lập kế hoạch nội dung tuần này",
          mode: "autopilot",
        })
      );
    });
  });

  describe("SidebarNav Component", () => {
    it("renders required top action, nav labels, and time-grouped tasks", () => {
      const onNewTask = vi.fn();
      const onSelectTask = vi.fn();
      const onNavigate = vi.fn();

      const tasks = [
        { id: "t-1", title: "Nghiên cứu thị trường AI", group: "today" as const },
        { id: "t-2", title: "Viết kịch bản video TikTok", group: "yesterday" as const },
        { id: "t-3", title: "Thiết kế landing page", group: "past7days" as const },
      ];

      render(
        <SidebarNav
          tasks={tasks}
          selectedTaskId="t-1"
          onNewTask={onNewTask}
          onSelectTask={onSelectTask}
          onNavigate={onNavigate}
        />
      );

      // Top action
      const newTaskBtn = screen.getByRole("button", { name: /tạo task mới/i });
      expect(newTaskBtn).toBeInTheDocument();
      fireEvent.click(newTaskBtn);
      expect(onNewTask).toHaveBeenCalled();

      // Navigation items
      expect(screen.getByText("Văn phòng AI")).toBeInTheDocument();
      expect(screen.getByText("Tự động")).toBeInTheDocument();
      expect(screen.getByText("Thư viện")).toBeInTheDocument();
      expect(screen.getByText("Brain")).toBeInTheDocument();
      expect(screen.getByText("Hội thoại khách")).toBeInTheDocument();

      // Time groups
      expect(screen.getByText("Hôm nay")).toBeInTheDocument();
      expect(screen.getByText("Hôm qua")).toBeInTheDocument();
      expect(screen.getByText("7 ngày qua")).toBeInTheDocument();

      // Tasks
      const taskItem = screen.getByText("Nghiên cứu thị trường AI");
      expect(taskItem).toBeInTheDocument();
      fireEvent.click(taskItem);
      expect(onSelectTask).toHaveBeenCalledWith("t-1");
    });
  });

  describe("ApiClient Unit Tests", () => {
    it("attaches X-Local-Auth-Token header and fetches agents", async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          status: "success",
          data: [
            {
              id: "agent-1",
              name: "ContentWriter",
              display_name: "Content Writer",
              role: "Writer",
              status: "idle",
            },
          ],
        }),
      });
      global.fetch = mockFetch;

      const client = new ApiClient({ token: "test-secret-token", baseUrl: "http://127.0.0.1:8765" });
      const agents = await client.listAgents();

      expect(mockFetch).toHaveBeenCalledWith(
        "http://127.0.0.1:8765/api/v1/agents",
        expect.objectContaining({
          headers: expect.objectContaining({
            "X-Local-Auth-Token": "test-secret-token",
          }),
        })
      );
      expect(agents).toHaveLength(1);
      expect(agents[0].displayName).toBe("Content Writer");
      expect(agents[0].name).toBe("ContentWriter");
    });

    it("parses task prompt and returns structured task response", async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          status: "success",
          data: {
            task_id: "task-abc123",
            intent: "content_generation",
            task_type: "article",
            mentioned_agents: ["ContentWriter"],
            urls: [],
            attachment_ids: [],
            entities: {},
          },
        }),
      });
      global.fetch = mockFetch;

      const client = new ApiClient({ token: "test-token" });
      const result = await client.parseTask("Lập bài viết mới @ContentWriter", { mode: "copilot" });

      expect(mockFetch).toHaveBeenCalledWith(
        "http://127.0.0.1:8765/api/v1/tasks/parse",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            projectId: "proj-default",
            promptText: "Lập bài viết mới @ContentWriter",
            attachments: [],
            mode: "copilot",
          }),
        })
      );
      expect(result.taskId).toBe("task-abc123");
      expect(result.mentionedAgents).toEqual(["ContentWriter"]);
    });

    it("throws ApiError when backend returns 401 or 422", async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 401,
        json: async () => ({ detail: "Invalid or missing X-Local-Auth-Token" }),
      });
      global.fetch = mockFetch;

      const client = new ApiClient({ token: "wrong-token" });
      await expect(client.listAgents()).rejects.toThrow(ApiError);
    });
  });
});
