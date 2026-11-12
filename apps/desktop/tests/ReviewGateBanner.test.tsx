import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import React from "react";
import { ReviewGateBanner } from "@/components/reviews/ReviewGateBanner";

describe("ReviewGateBanner Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // Brief Step 1 test
  it("requires feedback >= 5 chars before submitting reject", () => {
    const onDecide = vi.fn();
    render(
      <ReviewGateBanner
        review={{ id: "r1", gateType: "storyboard", summary: "Duyệt kịch bản" }}
        onDecide={onDecide}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /đặt lại/i }));
    expect(screen.getByRole("button", { name: /xác nhận từ chối/i })).toBeDisabled();
  });

  it("enables reject confirmation once trimmed feedback >= 5 chars and submits reject payload", () => {
    const onDecide = vi.fn();
    render(
      <ReviewGateBanner
        review={{ id: "r1", gateType: "storyboard", summary: "Duyệt kịch bản 60s" }}
        onDecide={onDecide}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /đặt lại/i }));
    const confirmBtn = screen.getByRole("button", { name: /xác nhận từ chối/i });
    const textarea = screen.getByRole("textbox");

    // Whitespace-only or short feedback stays disabled
    fireEvent.change(textarea, { target: { value: "  ab  " } });
    expect(confirmBtn).toBeDisabled();

    fireEvent.change(textarea, { target: { value: "Cần sửa lại hook 3s đầu" } });
    expect(confirmBtn).not.toBeDisabled();

    fireEvent.click(confirmBtn);
    expect(onDecide).toHaveBeenCalledTimes(1);
    expect(onDecide).toHaveBeenCalledWith("reject", {
      feedbackText: "Cần sửa lại hook 3s đầu",
    });
  });

  it("triggers approve callback when Phê duyệt is clicked", () => {
    const onDecide = vi.fn();
    render(
      <ReviewGateBanner
        review={{ id: "r2", gateType: "publish", summary: "Xuất bản bài viết" }}
        onDecide={onDecide}
      />
    );

    expect(screen.getByText(/publish/i)).toBeInTheDocument();
    expect(screen.getByText("Xuất bản bài viết")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /phê duyệt/i }));
    expect(onDecide).toHaveBeenCalledTimes(1);
    expect(onDecide).toHaveBeenCalledWith("approve");
  });

  it("supports inline edit flow and submits editedContent on confirm", () => {
    const onDecide = vi.fn();
    render(
      <ReviewGateBanner
        review={{
          id: "r3",
          gateType: "copy",
          summary: "Nội dung bài đăng Facebook",
          editedContent: "Bản nháp cũ",
        }}
        onDecide={onDecide}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /chỉnh sửa/i }));
    const editor = screen.getByRole("textbox");
    fireEvent.change(editor, { target: { value: "Bản đã chỉnh sửa hoàn chỉnh" } });

    const saveEditBtn = screen.getByRole("button", { name: /lưu & phê duyệt|xác nhận chỉnh sửa/i });
    fireEvent.click(saveEditBtn);

    expect(onDecide).toHaveBeenCalledTimes(1);
    expect(onDecide).toHaveBeenCalledWith(
      "edit",
      expect.objectContaining({
        editedContent: "Bản đã chỉnh sửa hoàn chỉnh",
      })
    );
  });

  it("disables actions when review is expired or already decided", () => {
    const onDecide = vi.fn();
    const { rerender } = render(
      <ReviewGateBanner
        review={{
          id: "r4",
          gateType: "storyboard",
          summary: "Quá hạn duyệt",
          status: "expired",
        }}
        onDecide={onDecide}
      />
    );

    expect(screen.getByText(/hết hạn/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /phê duyệt/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /chỉnh sửa/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /đặt lại/i })).toBeDisabled();

    rerender(
      <ReviewGateBanner
        review={{
          id: "r5",
          gateType: "storyboard",
          summary: "Đã duyệt xong",
          status: "approved",
        }}
        onDecide={onDecide}
      />
    );
    expect(screen.getByText(/đã phê duyệt/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /phê duyệt/i })).not.toBeInTheDocument();
  });
});
