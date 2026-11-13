"use client";

import React, { useState, useRef, useEffect } from "react";
import {
  User,
  Bot,
  Send,
  Radio,
  Clock,
  Sparkles,
  ArrowRightLeft,
  CheckCircle2,
  AlertCircle,
  MessageSquare,
} from "lucide-react";
import { InboxConversation, InboxMessage } from "@/lib/types";

export interface ThreadPanelProps {
  conversation: InboxConversation | null;
  messages: InboxMessage[];
  isAiGenerating?: boolean;
  onTakeover: (convId: string) => void | Promise<void>;
  onRelease: (convId: string) => void | Promise<void>;
  onSendReply: (content: string) => void | Promise<void>;
  isLoadingMessages?: boolean;
}

export function ThreadPanel({
  conversation,
  messages,
  isAiGenerating = false,
  onTakeover,
  onRelease,
  onSendReply,
  isLoadingMessages = false,
}: ThreadPanelProps) {
  const [inputText, setInputText] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (typeof messagesEndRef.current?.scrollIntoView === "function") {
      messagesEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, isAiGenerating]);

  if (!conversation) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center bg-gray-950 text-gray-400 p-8">
        <MessageSquare className="w-16 h-16 text-gray-700 mb-4 stroke-1" />
        <h3 className="text-lg font-medium text-gray-300">Chưa chọn cuộc hội thoại</h3>
        <p className="text-sm text-gray-500 mt-1">Chọn một khách hàng từ danh sách bên trái để xem nội dung trao đổi.</p>
      </div>
    );
  }

  const handleSend = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const trimmed = inputText.trim();
    if (!trimmed || isSubmitting) return;

    setIsSubmitting(true);
    try {
      await onSendReply(trimmed);
      setInputText("");
    } finally {
      setIsSubmitting(false);
    }
  };

  const getChannelBadge = (channel: string) => {
    const ch = channel.toLowerCase();
    switch (ch) {
      case "zalo":
        return (
          <span className="px-2 py-0.5 rounded text-xs font-semibold bg-blue-900/40 text-blue-400 border border-blue-700/50">
            Zalo
          </span>
        );
      case "telegram":
        return (
          <span className="px-2 py-0.5 rounded text-xs font-semibold bg-sky-900/40 text-sky-400 border border-sky-700/50">
            Telegram
          </span>
        );
      default:
        return (
          <span className="px-2 py-0.5 rounded text-xs font-semibold bg-purple-900/40 text-purple-400 border border-purple-700/50">
            Nội bộ
          </span>
        );
    }
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-gray-950 overflow-hidden" data-testid="thread-panel">
      {/* Conversation Header */}
      <header className="px-6 py-4 bg-gray-900/90 border-b border-gray-800 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-gray-800 border border-gray-700 flex items-center justify-center text-sky-400 font-bold shrink-0">
            {conversation.participant_name ? conversation.participant_name.charAt(0).toUpperCase() : "U"}
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base font-semibold text-white tracking-wide">
                {conversation.participant_name || "Khách hàng ẩn danh"}
              </h2>
              {getChannelBadge(conversation.channel)}
              {conversation.is_human_takeover ? (
                <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-amber-500/10 text-amber-400 border border-amber-500/30 flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
                  Người tiếp quản
                </span>
              ) : (
                <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                  AI Tự động
                </span>
              )}
            </div>
            <p className="text-xs text-gray-400 mt-0.5">
              ID: {conversation.id} {conversation.channel_conv_id ? `• Channel ID: ${conversation.channel_conv_id}` : ""}
            </p>
          </div>
        </div>

        {/* Takeover / Release Control Button */}
        <div>
          {conversation.is_human_takeover ? (
            <div className="flex items-center gap-2">
              <span className="text-xs text-amber-300 hidden sm:inline">
                Bạn đang trực tiếp trả lời
              </span>
              <button
                type="button"
                onClick={() => onRelease(conversation.id)}
                className="px-3.5 py-1.5 rounded-lg bg-gray-800 hover:bg-gray-700 text-sky-400 border border-sky-500/30 hover:border-sky-500/60 text-xs font-medium transition-colors flex items-center gap-1.5 cursor-pointer shadow-sm"
              >
                <Bot className="w-3.5 h-3.5" />
                <span>Giao lại cho AI</span>
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => onTakeover(conversation.id)}
              className="px-4 py-1.5 rounded-lg bg-amber-500 hover:bg-amber-600 text-gray-950 font-semibold text-xs transition-colors flex items-center gap-1.5 cursor-pointer shadow-sm"
            >
              <ArrowRightLeft className="w-3.5 h-3.5" />
              <span>Tôi trả lời</span>
            </button>
          )}
        </div>
      </header>

      {/* Generating / Live AI Status Notice */}
      {isAiGenerating && (
        <div className="bg-sky-950/40 border-b border-sky-800/40 px-6 py-2 flex items-center justify-between text-xs text-sky-300">
          <div className="flex items-center gap-2">
            <Radio className="w-3.5 h-3.5 text-sky-400 animate-pulse" />
            <span>Agent đang trả lời cuộc này...</span>
          </div>
          <span className="text-[11px] text-sky-400/80">Race-safe takeover sẵn sàng</span>
        </div>
      )}

      {/* Messages Thread Container */}
      <div className="flex-1 overflow-y-auto p-6 space-y-4">
        {isLoadingMessages ? (
          <div className="flex justify-center py-12 text-gray-500 text-sm">
            <Clock className="w-5 h-5 animate-spin mr-2" /> Đang tải tin nhắn...
          </div>
        ) : messages.length === 0 ? (
          <div className="text-center py-12 text-gray-500 text-sm">
            Chưa có tin nhắn nào trong cuộc hội thoại này.
          </div>
        ) : (
          messages.map((msg) => {
            const isCustomer = msg.sender_type === "customer";
            const isAgent = msg.sender_type === "agent";
            const isHuman = msg.sender_type === "human";
            const isSystem = msg.sender_type === "system";

            if (isSystem) {
              return (
                <div key={msg.id} className="flex justify-center my-2">
                  <div className="px-3 py-1 rounded-full bg-gray-800/80 text-gray-400 border border-gray-700 text-xs text-center max-w-md">
                    {msg.content}
                  </div>
                </div>
              );
            }

            return (
              <div
                key={msg.id}
                className={`flex gap-3 ${isCustomer ? "justify-start" : "justify-end"}`}
              >
                {isCustomer && (
                  <div className="w-8 h-8 rounded-full bg-gray-800 border border-gray-700 flex items-center justify-center text-gray-300 shrink-0">
                    <User className="w-4 h-4" />
                  </div>
                )}

                <div className={`max-w-[70%] flex flex-col ${isCustomer ? "items-start" : "items-end"}`}>
                  <div className="flex items-center gap-1.5 mb-1 text-[11px] text-gray-400">
                    <span>
                      {isCustomer
                        ? msg.sender_name || "Khách hàng"
                        : isAgent
                        ? "AI Assistant"
                        : msg.sender_name || "Nhân viên hỗ trợ"}
                    </span>
                    {msg.created_at && (
                      <span className="text-gray-500">
                        {new Date(msg.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                      </span>
                    )}
                  </div>

                  <div
                    className={`px-4 py-2.5 rounded-2xl text-sm leading-relaxed shadow-sm ${
                      isCustomer
                        ? "bg-gray-800 text-gray-100 rounded-tl-sm border border-gray-700"
                        : isAgent
                        ? "bg-sky-900/60 text-sky-100 rounded-tr-sm border border-sky-700/50"
                        : "bg-emerald-600 text-white rounded-tr-sm"
                    }`}
                  >
                    <p className="whitespace-pre-wrap">{msg.content}</p>
                  </div>
                </div>

                {!isCustomer && (
                  <div
                    className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 text-white ${
                      isAgent ? "bg-sky-700" : "bg-emerald-700"
                    }`}
                  >
                    {isAgent ? <Bot className="w-4 h-4" /> : <User className="w-4 h-4" />}
                  </div>
                )}
              </div>
            );
          })
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Operator Reply Input Area */}
      <footer className="p-4 bg-gray-900 border-t border-gray-800">
        <form onSubmit={handleSend} className="flex items-center gap-3">
          <input
            type="text"
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            placeholder="Nhập tin nhắn trả lời..."
            className="flex-1 bg-gray-950 border border-gray-800 rounded-xl px-4 py-2.5 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500 transition-colors"
          />
          <button
            type="submit"
            disabled={!inputText.trim() || isSubmitting}
            className="px-4 py-2.5 rounded-xl bg-sky-500 hover:bg-sky-600 disabled:bg-gray-800 disabled:text-gray-600 disabled:cursor-not-allowed text-white font-medium text-sm flex items-center gap-2 transition-colors cursor-pointer shadow-sm"
            aria-label="Gửi"
          >
            <Send className="w-4 h-4" />
            <span className="hidden sm:inline">Gửi</span>
          </button>
        </form>
      </footer>
    </div>
  );
}
