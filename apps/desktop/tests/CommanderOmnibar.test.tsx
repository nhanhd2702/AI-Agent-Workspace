import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import React from "react";
import { CommanderOmnibar } from "@/components/chat/CommanderOmnibar";

describe("CommanderOmnibar Component", () => {
  it("renders omnibar inputs, attachment icons, model selector and submit button", () => {
    const onSubmit = vi.fn();
    render(<CommanderOmnibar onSubmit={onSubmit} isStreaming={false} />);

    expect(screen.getByPlaceholderText(/Hôm nay bạn muốn hoàn thành việc gì/i)).toBeInTheDocument();
    expect(screen.getByTitle("Đính kèm tệp")).toBeInTheDocument();
    expect(screen.getByTitle("Đính kèm ảnh")).toBeInTheDocument();
    expect(screen.getByTitle("Ảnh chụp màn hình")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Gửi lệnh/i })).toBeInTheDocument();
  });

  it("opens popup 6 tabs when clicking on 'Gửi tới Người điều phối'", () => {
    render(<CommanderOmnibar onSubmit={vi.fn()} isStreaming={false} />);

    const destButton = screen.getByTestId("target-dest-btn");
    expect(destButton).toBeInTheDocument();
    fireEvent.click(destButton);

    // 6 tabs in popup
    expect(screen.getByRole("tab", { name: /^Agent$/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /^Đội$/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /^Skills$/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /^Connectors$/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /^Thư viện$/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /^Trang$/i })).toBeInTheDocument();

    // Search bar inside popup
    expect(screen.getByPlaceholderText(/Tìm kiếm agent/i)).toBeInTheDocument();
  });

  it("filters agents inside popup when typing in search input", () => {
    render(<CommanderOmnibar onSubmit={vi.fn()} isStreaming={false} />);

    fireEvent.click(screen.getByTestId("target-dest-btn"));
    const searchInput = screen.getByPlaceholderText(/Tìm kiếm agent/i);

    fireEvent.change(searchInput, { target: { value: "DeepResearcher" } });
    expect(screen.getByText("DeepResearcher")).toBeInTheDocument();
  });

  it("toggles Rảnh tay (Voice / Handsfree) mode", () => {
    render(<CommanderOmnibar onSubmit={vi.fn()} isStreaming={false} />);

    const handsfreeBtn = screen.getByRole("button", { name: /Rảnh tay/i });
    expect(handsfreeBtn).toBeInTheDocument();
    fireEvent.click(handsfreeBtn);
    expect(handsfreeBtn).toHaveClass("bg-indigo-600");
  });

  it("submits prompt when clicking send button", () => {
    const onSubmit = vi.fn();
    render(<CommanderOmnibar onSubmit={onSubmit} isStreaming={false} />);

    const textarea = screen.getByPlaceholderText(/Hôm nay bạn muốn hoàn thành việc gì/i);
    fireEvent.change(textarea, { target: { value: "Thiết kế phễu bán hàng" } });

    const sendBtn = screen.getByRole("button", { name: /Gửi lệnh/i });
    fireEvent.click(sendBtn);

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        prompt: "Thiết kế phễu bán hàng",
      })
    );
  });
});
