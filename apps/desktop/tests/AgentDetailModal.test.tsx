import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import React from "react";
import { AgentDetailModal } from "@/components/office/AgentDetailModal";
import { AgentVisual } from "@/components/office/Office3DCanvas";

describe("AgentDetailModal Component", () => {
  const sampleAgent: AgentVisual = {
    id: "writer",
    name: "ContentWriter",
    displayName: "Trần Viết Văn",
    role: "Biên tập kịch bản & nội dung viral",
    department: "Đội Content",
    color: "#10b981",
    status: "working",
    thought: "Đang soạn kịch bản video TikTok 60s hook tài chính...",
    gridX: 3.5,
    gridY: -3,
    skills: ["Kịch bản TikTok 60s", "W-Structure", "Storytelling"],
    model: "Claude 3.7 Sonnet",
  };

  it("renders agent identity, department, skills list, and model badge", () => {
    render(<AgentDetailModal agent={sampleAgent} onClose={vi.fn()} />);

    expect(screen.getByText("ContentWriter")).toBeInTheDocument();
    expect(screen.getByText("Trần Viết Văn")).toBeInTheDocument();
    expect(screen.getByText("Biên tập kịch bản & nội dung viral")).toBeInTheDocument();
    expect(screen.getByText("Đội Content")).toBeInTheDocument();
    expect(screen.getByText("Claude 3.7 Sonnet")).toBeInTheDocument();

    // Skills
    expect(screen.getByText("Kịch bản TikTok 60s")).toBeInTheDocument();
    expect(screen.getByText("W-Structure")).toBeInTheDocument();
    expect(screen.getByText("Storytelling")).toBeInTheDocument();
  });

  it("triggers onUseAgent when clicking 'Dùng agent này'", () => {
    const onUseAgent = vi.fn();
    render(<AgentDetailModal agent={sampleAgent} onClose={vi.fn()} onUseAgent={onUseAgent} />);

    const useBtn = screen.getByRole("button", { name: /Dùng agent này/i });
    fireEvent.click(useBtn);

    expect(onUseAgent).toHaveBeenCalledTimes(1);
    expect(onUseAgent).toHaveBeenCalledWith(sampleAgent);
  });

  it("triggers onClose when clicking close button", () => {
    const onClose = vi.fn();
    render(<AgentDetailModal agent={sampleAgent} onClose={onClose} />);

    const closeBtn = screen.getByRole("button", { name: /Đóng/i });
    fireEvent.click(closeBtn);

    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
