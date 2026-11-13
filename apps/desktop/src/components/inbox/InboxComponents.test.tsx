import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import { ThreadPanel } from "./ThreadPanel";
import InboxPage from "@/app/inbox/page";
import { defaultApiClient } from "@/lib/apiClient";
import { InboxConversation, InboxMessage, ConnectorStatus } from "@/lib/types";

// Mock defaultApiClient
vi.mock("@/lib/apiClient", () => ({
  defaultApiClient: {
    getConversations: vi.fn(),
    getConversationMessages: vi.fn(),
    takeoverConversation: vi.fn(),
    releaseConversation: vi.fn(),
    sendOperatorReply: vi.fn(),
    getConnectorsStatus: vi.fn(),
  },
}));

describe("InboxComponents Unit & Integration Tests", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  const mockConvWaiting: InboxConversation = {
    id: "conv-1",
    project_id: "proj-default",
    channel: "zalo",
    title: "Khách Zalo Nguyễn Văn A",
    participant_name: "Nguyễn Văn A",
    status: "waiting",
    is_human_takeover: false,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };

  const mockConvHuman: InboxConversation = {
    id: "conv-2",
    project_id: "proj-default",
    channel: "telegram",
    title: "Khách Telegram Trần Thị B",
    participant_name: "Trần Thị B",
    status: "in_progress",
    is_human_takeover: true,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };

  const mockMessages: InboxMessage[] = [
    {
      id: "msg-1",
      conversation_id: "conv-1",
      sender_type: "customer",
      sender_name: "Nguyễn Văn A",
      content: "Shop ơi tư vấn giúp em áo khoác",
      created_at: new Date(Date.now() - 60000).toISOString(),
    },
    {
      id: "msg-2",
      conversation_id: "conv-1",
      sender_type: "agent",
      sender_name: "AI Assistant",
      content: "Dạ bên em có các mẫu áo khoác dạ và gió mới về ạ!",
      created_at: new Date(Date.now() - 30000).toISOString(),
    },
  ];

  describe("ThreadPanel", () => {
    it("renders conversation header with participant name, channel badge, and messages", () => {
      render(
        <ThreadPanel
          conversation={mockConvWaiting}
          messages={mockMessages}
          isAiGenerating={false}
          onTakeover={vi.fn()}
          onRelease={vi.fn()}
          onSendReply={vi.fn()}
        />
      );

      expect(screen.getByRole("heading", { name: "Nguyễn Văn A" })).toBeInTheDocument();
      expect(screen.getByText(/Zalo/i)).toBeInTheDocument();
      expect(screen.getByText("Shop ơi tư vấn giúp em áo khoác")).toBeInTheDocument();
      expect(screen.getByText("Dạ bên em có các mẫu áo khoác dạ và gió mới về ạ!")).toBeInTheDocument();
    });

    it("displays 'Agent đang trả lời cuộc này...' when AI is generating", () => {
      render(
        <ThreadPanel
          conversation={mockConvWaiting}
          messages={mockMessages}
          isAiGenerating={true}
          onTakeover={vi.fn()}
          onRelease={vi.fn()}
          onSendReply={vi.fn()}
        />
      );

      expect(screen.getByText(/Agent đang trả lời cuộc này/i)).toBeInTheDocument();
    });

    it("shows 'Tôi trả lời' button when AI is handling and triggers onTakeover", async () => {
      const handleTakeover = vi.fn();
      render(
        <ThreadPanel
          conversation={mockConvWaiting}
          messages={mockMessages}
          isAiGenerating={false}
          onTakeover={handleTakeover}
          onRelease={vi.fn()}
          onSendReply={vi.fn()}
        />
      );

      const takeoverBtn = screen.getByRole("button", { name: /Tôi trả lời/i });
      expect(takeoverBtn).toBeInTheDocument();
      fireEvent.click(takeoverBtn);
      expect(handleTakeover).toHaveBeenCalledWith("conv-1");
    });

    it("shows 'Bạn đang trực tiếp trả lời' and 'Giao lại cho AI' button when in human takeover mode", async () => {
      const handleRelease = vi.fn();
      render(
        <ThreadPanel
          conversation={mockConvHuman}
          messages={mockMessages}
          isAiGenerating={false}
          onTakeover={vi.fn()}
          onRelease={handleRelease}
          onSendReply={vi.fn()}
        />
      );

      expect(screen.getByText(/Bạn đang trực tiếp trả lời/i)).toBeInTheDocument();
      const releaseBtn = screen.getByRole("button", { name: /Giao lại cho AI/i });
      expect(releaseBtn).toBeInTheDocument();
      fireEvent.click(releaseBtn);
      expect(handleRelease).toHaveBeenCalledWith("conv-2");
    });

    it("allows operator to type and send a reply message", async () => {
      const handleSendReply = vi.fn();
      render(
        <ThreadPanel
          conversation={mockConvHuman}
          messages={mockMessages}
          isAiGenerating={false}
          onTakeover={vi.fn()}
          onRelease={vi.fn()}
          onSendReply={handleSendReply}
        />
      );

      const input = screen.getByPlaceholderText(/Nhập tin nhắn trả lời/i);
      fireEvent.change(input, { target: { value: "Chào bạn, mình là nhân viên tư vấn đây ạ." } });
      const sendBtn = screen.getByRole("button", { name: /Gửi/i });
      fireEvent.click(sendBtn);

      await waitFor(() => {
        expect(handleSendReply).toHaveBeenCalledWith("Chào bạn, mình là nhân viên tư vấn đây ạ.");
      });
    });
  });

  describe("Unified Inbox Page", () => {
    const mockConnectors: ConnectorStatus[] = [
      {
        id: "conn-1",
        name: "Zalo OA",
        provider: "zalo",
        status: "needs_reauth",
        is_enabled: true,
        qr_code_url: "https://example.com/qr/zalo",
      },
      {
        id: "conn-2",
        name: "Telegram Bot",
        provider: "telegram",
        status: "connected",
        is_enabled: true,
      },
    ];

    it("renders tabs 'Chờ', 'Đang xử lý', 'Tất cả', channel filter, and QR re-auth banner", async () => {
      vi.mocked(defaultApiClient.getConversations).mockResolvedValue([
        mockConvWaiting,
        mockConvHuman,
      ]);
      vi.mocked(defaultApiClient.getConnectorsStatus).mockResolvedValue(mockConnectors);
      vi.mocked(defaultApiClient.getConversationMessages).mockResolvedValue(mockMessages);

      render(<InboxPage />);

      // Wait for initial load
      await waitFor(() => {
        expect(screen.getByText("Hộp thư Khách hàng (Unified Inbox)")).toBeInTheDocument();
      });

      // Verify tabs exist
      expect(screen.getByRole("button", { name: /^Chờ$/i })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /^Đang xử lý$/i })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /^Tất cả$/i })).toBeInTheDocument();

      // Verify channel filters
      expect(screen.getByRole("button", { name: /^Zalo$/i })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /^Telegram$/i })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /^Nội bộ$/i })).toBeInTheDocument();

      // Verify QR re-auth banner appears when session needs re-auth
      expect(screen.getByText(/kết nối Zalo OA cần quét lại mã QR/i)).toBeInTheDocument();
    });
  });
});
