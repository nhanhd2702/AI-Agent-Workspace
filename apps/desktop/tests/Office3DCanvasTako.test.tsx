import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import React from "react";
import { Office3DCanvas, TAKO_22_AGENTS } from "@/components/office/Office3DCanvas";

describe("Office3DCanvas TAKO Standard Tests", () => {
  it("defines exactly 22 Chibi AI Agents across 4 department pods and master commander", () => {
    expect(TAKO_22_AGENTS).toHaveLength(22);

    const commander = TAKO_22_AGENTS.find((a) => a.id === "commander");
    expect(commander).toBeDefined();
    expect(commander?.name).toBe("Người điều phối");

    const contentAgents = TAKO_22_AGENTS.filter((a) => a.department === "Đội Content");
    expect(contentAgents.length).toBeGreaterThanOrEqual(5);

    const funnelsAgents = TAKO_22_AGENTS.filter((a) => a.department === "Đội Funnels");
    expect(funnelsAgents.length).toBeGreaterThanOrEqual(5);

    const loungeAgents = TAKO_22_AGENTS.filter((a) => a.department === "Phòng nghỉ");
    expect(loungeAgents.length).toBeGreaterThanOrEqual(3);
  });

  it("renders 3D Canvas container with controls: zoom in, zoom out, reset view", () => {
    render(<Office3DCanvas />);

    expect(screen.getByTitle("Phóng to")).toBeInTheDocument();
    expect(screen.getByTitle("Thu nhỏ")).toBeInTheDocument();
    expect(screen.getByTitle("Góc nhìn mặc định")).toBeInTheDocument();
  });

  it("triggers onSelectAgent when clicking on an agent in list or detail trigger", () => {
    const onSelect = vi.fn();
    render(<Office3DCanvas onSelectAgent={onSelect} />);

    const quickSelectBtn = screen.getByTestId("agent-quick-select-writer");
    expect(quickSelectBtn).toBeInTheDocument();
    fireEvent.click(quickSelectBtn);

    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "ContentWriter",
      })
    );
  });
});
