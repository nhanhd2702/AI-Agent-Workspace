import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import React from "react";
import OfficePage from "@/app/office/page";

describe("OfficePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders 5 department groups with agent status badges, skill count, and '+ Thêm vào phòng' action", async () => {
    global.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      if (url.includes("/api/v1/departments")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            status: "success",
            data: [
              {
                id: "dept-content",
                name: "Đội Content",
                status: "active",
                agents_count: 1,
                agents: [
                  {
                    id: "agent-content-writer",
                    name: "ContentWriter",
                    display_name: "Content Writer",
                    role: "Copywriter",
                    department_id: "dept-content",
                    default_model: "gemini-2.5-flash",
                    status: "busy",
                    skills_count: 4,
                  },
                ],
              },
              { id: "dept-funnels", name: "Đội Funnels", status: "active", agents_count: 0, agents: [] },
              { id: "dept-rd", name: "Nghiên cứu & Phát triển", status: "active", agents_count: 0, agents: [] },
              { id: "dept-ecommerce", name: "Thương mại điện tử", status: "active", agents_count: 0, agents: [] },
            ],
          }),
        });
      }
      if (url.includes("/api/v1/agents/agent-free") && init?.method === "PUT") {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            status: "success",
            data: {
              id: "agent-free",
              name: "FreeAgent",
              display_name: "Free Agent",
              role: "Helper",
              department_id: "dept-content",
              status: "idle",
              skills_count: 2,
            },
          }),
        });
      }
      if (url.includes("/api/v1/agents")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            status: "success",
            data: [
              {
                id: "agent-content-writer",
                name: "ContentWriter",
                display_name: "Content Writer",
                role: "Copywriter",
                department_id: "dept-content",
                default_model: "gemini-2.5-flash",
                status: "busy",
                skills_count: 4,
              },
              {
                id: "agent-free",
                name: "FreeAgent",
                display_name: "Free Agent",
                role: "Helper",
                department_id: null,
                default_model: "gemini-2.5-flash",
                status: "idle",
                skills_count: 2,
              },
            ],
          }),
        });
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({ status: "success", data: {} }) });
    });

    await act(async () => {
      render(<OfficePage />);
    });

    await waitFor(() => {
      expect(screen.getAllByText("Đội Content").length).toBeGreaterThan(0);
    });

    expect(screen.getAllByText("Đội Funnels").length).toBeGreaterThan(0);
    expect(screen.getByText("Nghiên cứu & Phát triển")).toBeInTheDocument();
    expect(screen.getByText("Thương mại điện tử")).toBeInTheDocument();
    expect(screen.getByText("Chưa vào phòng")).toBeInTheDocument();

    expect(screen.getAllByText("Đang chạy").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Nghỉ").length).toBeGreaterThan(0);
    expect(screen.getByText("4 kỹ năng")).toBeInTheDocument();

    const addButtons = screen.getAllByRole("button", { name: /\+ thêm vào phòng/i });
    expect(addButtons.length).toBeGreaterThanOrEqual(1);

    fireEvent.click(addButtons[0]);
    expect(screen.getByText(/thêm agent vào phòng/i)).toBeInTheDocument();
  });

  it("validates whitespace inputs, displays modal errors inside the dialog, and prevents duplicate submission", async () => {
    const createFetchMock = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      if (url.includes("/api/v1/departments")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            status: "success",
            data: [
              { id: "dept-content", name: "Đội Content", status: "active", agents_count: 0, agents: [] },
              { id: "dept-funnels", name: "Đội Funnels", status: "active", agents_count: 0, agents: [] },
              { id: "dept-rd", name: "Nghiên cứu & Phát triển", status: "active", agents_count: 0, agents: [] },
              { id: "dept-ecommerce", name: "Thương mại điện tử", status: "active", agents_count: 0, agents: [] },
            ],
          }),
        });
      }
      if (url.includes("/api/v1/agents") && init?.method === "POST") {
        return Promise.resolve({
          ok: false,
          status: 409,
          json: async () => ({ detail: "Agent with name 'SeoWriter' already exists" }),
        });
      }
      if (url.includes("/api/v1/agents")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ status: "success", data: [] }),
        });
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({ status: "success", data: {} }) });
    });

    global.fetch = createFetchMock;

    await act(async () => {
      render(<OfficePage />);
    });

    await waitFor(() => {
      expect(screen.getAllByText("Đội Content").length).toBeGreaterThan(0);
    });

    const addButtons = screen.getAllByRole("button", { name: /\+ thêm vào phòng/i });
    fireEvent.click(addButtons[0]);

    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();

    // Enter whitespace-only values
    const nameInput = screen.getByPlaceholderText("VD: SeoWriter");
    const displayInput = screen.getByPlaceholderText("VD: Chuyên viên SEO");
    const roleInput = screen.getByPlaceholderText("VD: SEO Content Specialist");

    fireEvent.change(nameInput, { target: { value: "   " } });
    fireEvent.change(displayInput, { target: { value: "   " } });
    fireEvent.change(roleInput, { target: { value: "   " } });

    const submitBtn = screen.getByRole("button", { name: /xác nhận/i });
    fireEvent.submit(submitBtn.closest("form")!);

    // Modal error rendered INSIDE the dialog; POST /api/v1/agents must NOT be called
    await waitFor(() => {
      const alert = dialog.querySelector('[role="alert"]');
      expect(alert).not.toBeNull();
    });
    expect(createFetchMock).not.toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/agents"),
      expect.objectContaining({ method: "POST" })
    );

    // Fill valid fields and submit -> backend returns 409 -> error rendered INSIDE modal
    fireEvent.change(nameInput, { target: { value: "SeoWriter" } });
    fireEvent.change(displayInput, { target: { value: "SEO Writer" } });
    fireEvent.change(roleInput, { target: { value: "SEO Specialist" } });

    fireEvent.submit(submitBtn.closest("form")!);

    await waitFor(() => {
      const alert = dialog.querySelector('[role="alert"]');
      expect(alert).not.toBeNull();
      expect(alert).toHaveTextContent(/already exists/i);
    });
  });

  it("shows error banner with Retry button and disables '+ Thêm vào phòng' on synthetic departments when loadOfficeData fails", async () => {
    let shouldFail = true;
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (shouldFail) {
        return Promise.resolve({
          ok: false,
          status: 500,
          json: async () => ({ detail: "Backend unavailable" }),
        });
      }
      if (url.includes("/api/v1/departments")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            status: "success",
            data: [
              { id: "dept-content", name: "Đội Content", status: "active", agents_count: 0, agents: [] },
            ],
          }),
        });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({ status: "success", data: [] }),
      });
    });

    await act(async () => {
      render(<OfficePage />);
    });

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/Backend unavailable/i);
    });

    // Synthetic departments must have disabled '+ Thêm vào phòng' buttons
    const addButtons = screen.getAllByRole("button", { name: /\+ thêm vào phòng/i });
    expect(addButtons.length).toBeGreaterThanOrEqual(1);
    for (const btn of addButtons) {
      expect(btn).toBeDisabled();
    }

    // Retry succeeds -> alert disappears, real dept button enabled while missing synthetic core depts remain disabled
    shouldFail = false;
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /thử lại/i }));
    });

    await waitFor(() => {
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });

    const contentSection = screen.getByTestId("department-group-dept-content");
    expect(contentSection.querySelector("button")).not.toBeDisabled();
  });
});
