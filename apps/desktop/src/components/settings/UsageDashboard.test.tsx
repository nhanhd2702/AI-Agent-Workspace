import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import { UsageDashboard } from "./UsageDashboard";
import { MonitoringDashboardData } from "@/lib/types";
import { defaultApiClient } from "@/lib/apiClient";

describe("UsageDashboard Component Tests (Task 5.2)", () => {
  const mockData: MonitoringDashboardData = {
    period: "7d",
    total_tokens: 154200,
    total_cost_usd: 1.482,
    prompt_tokens: 54200,
    completion_tokens: 100000,
    total_requests: 48,
    by_agent: [
      {
        agent_id: "agent-commander",
        agent_name: "Master Commander",
        requests: 20,
        tokens: 64200,
        cost_usd: 0.65,
        percentage: 43.86,
      },
      {
        agent_id: "agent-copywriter",
        agent_name: "Content Writer",
        requests: 18,
        tokens: 50000,
        cost_usd: 0.55,
        percentage: 37.11,
      },
    ],
    by_model: [
      {
        model_name: "gemini-2.5-flash",
        requests: 30,
        tokens: 90000,
        cost_usd: 0.82,
      },
      {
        model_name: "claude-3-5-sonnet",
        requests: 18,
        tokens: 64200,
        cost_usd: 0.662,
      },
    ],
    daily_trends: [
      { date: "2026-03-01", tokens: 20000, cost_usd: 0.2, requests: 8 },
      { date: "2026-03-02", tokens: 35000, cost_usd: 0.35, requests: 12 },
    ],
    task_stats: {
      total: 15,
      completed: 12,
      failed: 2,
      in_progress: 1,
      success_rate_pct: 80.0,
    },
    quota: {
      daily_limit_usd: 10.0,
      spent_today_usd: 1.482,
      remaining_today_usd: 8.518,
      percentage_used: 14.82,
      warning_triggered: false,
      exceeded: false,
      daily_token_limit: 1000000,
      tokens_spent_today: 154200,
    },
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders KPI summary cards with tokens, cost, requests, and success rate", async () => {
    render(<UsageDashboard initialData={mockData} />);

    // KPI cards
    expect(screen.getByText(/154,200|154200/)).toBeInTheDocument();
    expect(screen.getByText(/\$1\.482|\$1\.48/)).toBeInTheDocument();
    expect(screen.getByText("48")).toBeInTheDocument(); // Requests
    expect(screen.getByText(/80(\.0)?%/)).toBeInTheDocument(); // Success rate
  });

  it("renders period selector buttons and allows changing periods", async () => {
    const handlePeriodChange = vi.fn();
    render(<UsageDashboard initialData={mockData} onPeriodChange={handlePeriodChange} />);

    expect(screen.getByRole("button", { name: /Hôm nay/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /7 ngày/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /30 ngày/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Tất cả/i })).toBeInTheDocument();

    // Click 30 ngày button
    fireEvent.click(screen.getByRole("button", { name: /30 ngày/i }));
    expect(handlePeriodChange).toHaveBeenCalledWith("30d");
  });

  it("renders breakdown lists for agents and models", async () => {
    render(<UsageDashboard initialData={mockData} />);

    // Agent breakdown
    expect(screen.getByText("Master Commander")).toBeInTheDocument();
    expect(screen.getByText("Content Writer")).toBeInTheDocument();

    // Model breakdown
    expect(screen.getByText("gemini-2.5-flash")).toBeInTheDocument();
    expect(screen.getByText("claude-3-5-sonnet")).toBeInTheDocument();
  });

  it("renders task statistics widget with completed, failed, and in-progress counts", async () => {
    render(<UsageDashboard initialData={mockData} />);

    expect(screen.getByText("12")).toBeInTheDocument(); // completed
    expect(screen.getByText("2")).toBeInTheDocument(); // failed
    expect(screen.getByText("1")).toBeInTheDocument(); // in progress
  });

  it("triggers CSV export when clicking 'Xuất CSV' button", async () => {
    const handleExport = vi.fn();
    render(<UsageDashboard initialData={mockData} onExportCsv={handleExport} />);

    const exportBtn = screen.getByRole("button", { name: /Xuất CSV/i });
    expect(exportBtn).toBeInTheDocument();
    fireEvent.click(exportBtn);

    expect(handleExport).toHaveBeenCalled();
  });

  it("toggles 30-second auto-refresh option", async () => {
    render(<UsageDashboard initialData={mockData} />);

    const toggle = screen.getByRole("checkbox", { name: /Tự động làm mới/i });
    expect(toggle).toBeInTheDocument();
    fireEvent.click(toggle);
    expect(toggle).toBeChecked();
  });
});
