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
      expect(screen.getByText("Đội Content")).toBeInTheDocument();
    });

    expect(screen.getByText("Đội Funnels")).toBeInTheDocument();
    expect(screen.getByText("Nghiên cứu & Phát triển")).toBeInTheDocument();
    expect(screen.getByText("Thương mại điện tử")).toBeInTheDocument();
    expect(screen.getByText("Chưa vào phòng")).toBeInTheDocument();

    expect(screen.getByText("Đang chạy")).toBeInTheDocument();
    expect(screen.getByText("Nghỉ")).toBeInTheDocument();
    expect(screen.getByText("4 kỹ năng")).toBeInTheDocument();

    const addButtons = screen.getAllByRole("button", { name: /\+ thêm vào phòng/i });
    expect(addButtons.length).toBeGreaterThanOrEqual(1);

    fireEvent.click(addButtons[0]);
    expect(screen.getByText(/thêm agent vào phòng/i)).toBeInTheDocument();
  });
});
