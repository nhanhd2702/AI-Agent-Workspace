"use client";

import React, { useState, useEffect, useCallback, useMemo, useRef } from "react";
import {
  MessageSquare,
  Search,
  Filter,
  AlertTriangle,
  QrCode,
  RefreshCw,
  Clock,
  CheckCircle2,
  ExternalLink,
} from "lucide-react";
import { SidebarNav } from "@/components/layout/SidebarNav";
import { ThreadPanel } from "@/components/inbox/ThreadPanel";
import { defaultApiClient } from "@/lib/apiClient";
import { InboxConversation, InboxMessage, ConnectorStatus } from "@/lib/types";

type StatusTab = "waiting" | "in_progress" | "all";
type ChannelFilter = "all" | "zalo" | "telegram" | "internal";

export default function InboxPage() {
  const [conversations, setConversations] = useState<InboxConversation[]>([]);
  const [selectedConvId, setSelectedConvId] = useState<string | null>(null);
  const [messages, setMessages] = useState<InboxMessage[]>([]);
  const [connectors, setConnectors] = useState<ConnectorStatus[]>([]);
  const [activeTab, setActiveTab] = useState<StatusTab>("waiting");
  const [channelFilter, setChannelFilter] = useState<ChannelFilter>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingMessages, setIsLoadingMessages] = useState(false);
  const [isAiGenerating, setIsAiGenerating] = useState(false);
  const [showQrModal, setShowQrModal] = useState<string | null>(null);

  // Load conversations & connectors
  const loadData = useCallback(async () => {
    setIsLoading(true);
    try {
      const [convList, connList] = await Promise.all([
        defaultApiClient.getConversations({
          status: activeTab === "all" ? undefined : activeTab,
          channel: channelFilter === "all" ? undefined : channelFilter,
        }).catch(() => []),
        defaultApiClient.getConnectorsStatus().catch(() => []),
      ]);
      setConversations(convList);
      setConnectors(connList);

      if (convList.length > 0 && !selectedConvId) {
        setSelectedConvId(convList[0].id);
      }
    } catch {
      // Fallback
    } finally {
      setIsLoading(false);
    }
  }, [activeTab, channelFilter, selectedConvId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Load messages whenever selected conversation changes
  const loadMessages = useCallback(async (convId: string) => {
    setIsLoadingMessages(true);
    try {
      const msgs = await defaultApiClient.getConversationMessages(convId);
      setMessages(msgs);
    } catch {
      setMessages([]);
    } finally {
      setIsLoadingMessages(false);
    }
  }, []);

  useEffect(() => {
    if (selectedConvId) {
      loadMessages(selectedConvId);
    } else {
      setMessages([]);
    }
  }, [selectedConvId, loadMessages]);

  const selectedConvIdRef = useRef<string | null>(selectedConvId);
  selectedConvIdRef.current = selectedConvId;

  // Real-time WebSocket connection for live inbox updates
  useEffect(() => {
    if (typeof WebSocket === "undefined") return;
    let ws: WebSocket | null = null;
    let isMounted = true;

    try {
      const wsUrl = defaultApiClient.getInboxWebSocketUrl();
      ws = new WebSocket(wsUrl);

      ws.onmessage = (event) => {
        if (!isMounted) return;
        try {
          const data = typeof event.data === "string" ? JSON.parse(event.data) : event.data;
          if (!data || !data.type) return;

          if (data.type === "inbox.message") {
            const msg = data.message;
            const convId = data.conversation_id;
            if (msg && convId) {
              if (selectedConvIdRef.current === convId) {
                setMessages((prev) => {
                  if (prev.some((m) => m.id === msg.id)) return prev;
                  return [...prev, msg];
                });
              }

              setConversations((prev) =>
                prev.map((c) =>
                  c.id === convId
                    ? {
                        ...c,
                        status: c.is_human_takeover ? "in_progress" : c.status,
                        last_message: {
                          id: msg.id,
                          sender_type: msg.sender_type,
                          sender_name: msg.sender_name,
                          content: msg.content,
                          created_at: msg.created_at,
                        },
                        updated_at: msg.created_at || new Date().toISOString(),
                      }
                    : c
                )
              );
            }
          } else if (data.type === "inbox.takeover") {
            const convId = data.conversation_id;
            if (selectedConvIdRef.current === convId) {
              setIsAiGenerating(false);
            }
            if (data.conversation) {
              setConversations((prev) =>
                prev.map((c) => (c.id === convId ? data.conversation : c))
              );
            } else {
              setConversations((prev) =>
                prev.map((c) =>
                  c.id === convId
                    ? { ...c, is_human_takeover: true, status: "in_progress" }
                    : c
                )
              );
            }
          } else if (data.type === "inbox.release") {
            const convId = data.conversation_id;
            if (data.conversation) {
              setConversations((prev) =>
                prev.map((c) => (c.id === convId ? data.conversation : c))
              );
            } else {
              setConversations((prev) =>
                prev.map((c) =>
                  c.id === convId ? { ...c, is_human_takeover: false } : c
                )
              );
            }
          } else if (data.type === "inbox.ai_start") {
            if (selectedConvIdRef.current === data.conversation_id) {
              setIsAiGenerating(true);
            }
          } else if (data.type === "inbox.ai_done") {
            if (selectedConvIdRef.current === data.conversation_id) {
              setIsAiGenerating(false);
            }
          }
        } catch {
          // ignore parsing error
        }
      };

      ws.onerror = () => {
        // ws error fallback
      };
    } catch {
      // ws creation error fallback
    }

    return () => {
      isMounted = false;
      if (ws) {
        ws.close();
      }
    };
  }, []);

  const selectedConversation = useMemo(() => {
    return conversations.find((c) => c.id === selectedConvId) || null;
  }, [conversations, selectedConvId]);

  // Filtered conversation list
  const filteredConversations = useMemo(() => {
    return conversations.filter((c) => {
      // Tab filter
      if (activeTab === "waiting" && c.status !== "waiting" && c.is_human_takeover) return false;
      if (activeTab === "in_progress" && c.status !== "in_progress" && !c.is_human_takeover) return false;

      // Channel filter
      if (channelFilter !== "all" && c.channel.toLowerCase() !== channelFilter) return false;

      // Search query
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const nameMatch = c.participant_name?.toLowerCase().includes(q);
        const titleMatch = c.title?.toLowerCase().includes(q);
        const msgMatch = c.last_message?.content?.toLowerCase().includes(q);
        if (!nameMatch && !titleMatch && !msgMatch) return false;
      }

      return true;
    });
  }, [conversations, activeTab, channelFilter, searchQuery]);

  // Check for connectors that need re-authentication
  const reauthConnector = useMemo(() => {
    return connectors.find(
      (c) => c.status === "needs_reauth" || c.status === "expired"
    );
  }, [connectors]);

  // Handlers
  const handleTakeover = async (convId: string) => {
    try {
      const res = await defaultApiClient.takeoverConversation(convId);
      if (res.conversation) {
        setConversations((prev) =>
          prev.map((c) => (c.id === convId ? res.conversation : c))
        );
      }
      setIsAiGenerating(false);
    } catch {
      // Handle error
    }
  };

  const handleRelease = async (convId: string) => {
    try {
      const res = await defaultApiClient.releaseConversation(convId);
      if (res.conversation) {
        setConversations((prev) =>
          prev.map((c) => (c.id === convId ? res.conversation : c))
        );
      }
    } catch {
      // Handle error
    }
  };

  const handleSendReply = async (content: string) => {
    if (!selectedConvId) return;
    try {
      const newMsg = await defaultApiClient.sendOperatorReply(selectedConvId, content);
      setMessages((prev) => [...prev, newMsg]);
      // Update last message in conversation list
      setConversations((prev) =>
        prev.map((c) =>
          c.id === selectedConvId
            ? {
                ...c,
                status: "in_progress",
                last_message: {
                  id: newMsg.id,
                  sender_type: newMsg.sender_type,
                  sender_name: newMsg.sender_name,
                  content: newMsg.content,
                  created_at: newMsg.created_at,
                },
              }
            : c
        )
      );
    } catch {
      // Handle error
    }
  };

  const handleNavigate = (navId: string) => {
    if (typeof window === "undefined") return;
    if (navId === "workspace") window.location.assign("/");
    else if (navId === "office") window.location.assign("/office");
    else if (navId === "board") window.location.assign("/board");
    else if (navId === "brain") window.location.assign("/brain");
    else if (navId === "customer_chat" || navId === "inbox") window.location.assign("/inbox");
  };

  return (
    <div className="flex h-screen bg-gray-950 text-gray-100 overflow-hidden">
      {/* Sidebar Navigation */}
      <SidebarNav
        activeNav="customer_chat"
        onNavigate={handleNavigate}
        onNewTask={() => {
          if (typeof window !== "undefined") window.location.assign("/");
        }}
      />

      {/* Main Inbox Workspace */}
      <div className="flex-1 flex flex-col h-full overflow-hidden">
        {/* QR Re-Authentication Warning Banner */}
        {reauthConnector && (
          <div className="bg-amber-950/80 border-b border-amber-600/40 px-6 py-2.5 flex items-center justify-between text-amber-200 text-xs">
            <div className="flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />
              <span>
                Cảnh báo: Phiên kết nối {reauthConnector.name} cần quét lại mã QR để tiếp tục đồng bộ tin nhắn.
              </span>
            </div>
            {reauthConnector.qr_code_url && (
              <button
                type="button"
                onClick={() => setShowQrModal(reauthConnector.qr_code_url || null)}
                className="px-2.5 py-1 rounded bg-amber-600 hover:bg-amber-500 text-gray-950 font-semibold text-xs flex items-center gap-1.5 transition-colors cursor-pointer"
              >
                <QrCode className="w-3.5 h-3.5" />
                <span>Quét mã QR</span>
              </button>
            )}
          </div>
        )}

        {/* Inbox Split View: Conversation List & Thread Panel */}
        <div className="flex-1 flex overflow-hidden">
          {/* Left Column: Conversation Directory */}
          <section className="w-80 md:w-96 border-r border-gray-800 bg-gray-900 flex flex-col h-full shrink-0">
            {/* Header & Tabs */}
            <div className="p-4 border-b border-gray-800 space-y-3">
              <div className="flex items-center justify-between">
                <h1 className="text-base font-bold text-white flex items-center gap-2">
                  <MessageSquare className="w-4 h-4 text-sky-400" />
                  <span>Hộp thư Khách hàng (Unified Inbox)</span>
                </h1>
                <button
                  type="button"
                  onClick={loadData}
                  className="p-1 rounded text-gray-400 hover:text-white transition-colors"
                  aria-label="Tải lại"
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                </button>
              </div>

              {/* Status Tabs: Chờ / Đang xử lý / Tất cả */}
              <div className="grid grid-cols-3 gap-1 bg-gray-950 p-1 rounded-lg text-xs font-medium">
                <button
                  type="button"
                  onClick={() => setActiveTab("waiting")}
                  className={`py-1.5 rounded-md text-center transition-colors ${
                    activeTab === "waiting"
                      ? "bg-amber-500/20 text-amber-300 font-semibold border border-amber-500/40"
                      : "text-gray-400 hover:text-gray-200"
                  }`}
                >
                  Chờ
                </button>
                <button
                  type="button"
                  onClick={() => setActiveTab("in_progress")}
                  className={`py-1.5 rounded-md text-center transition-colors ${
                    activeTab === "in_progress"
                      ? "bg-sky-500/20 text-sky-300 font-semibold border border-sky-500/40"
                      : "text-gray-400 hover:text-gray-200"
                  }`}
                >
                  Đang xử lý
                </button>
                <button
                  type="button"
                  onClick={() => setActiveTab("all")}
                  className={`py-1.5 rounded-md text-center transition-colors ${
                    activeTab === "all"
                      ? "bg-gray-800 text-white font-semibold"
                      : "text-gray-400 hover:text-gray-200"
                  }`}
                >
                  Tất cả
                </button>
              </div>

              {/* Channel Filter Pills: Zalo / Telegram / Nội bộ */}
              <div className="flex items-center gap-1.5 overflow-x-auto text-xs pb-1">
                <button
                  type="button"
                  onClick={() => setChannelFilter("all")}
                  className={`px-2.5 py-1 rounded-full whitespace-nowrap transition-colors ${
                    channelFilter === "all"
                      ? "bg-gray-700 text-white font-medium"
                      : "bg-gray-800 text-gray-400 hover:text-gray-200"
                  }`}
                >
                  Tất cả kênh
                </button>
                <button
                  type="button"
                  onClick={() => setChannelFilter("zalo")}
                  className={`px-2.5 py-1 rounded-full whitespace-nowrap transition-colors ${
                    channelFilter === "zalo"
                      ? "bg-blue-600 text-white font-medium"
                      : "bg-gray-800 text-blue-400 hover:bg-gray-700"
                  }`}
                >
                  Zalo
                </button>
                <button
                  type="button"
                  onClick={() => setChannelFilter("telegram")}
                  className={`px-2.5 py-1 rounded-full whitespace-nowrap transition-colors ${
                    channelFilter === "telegram"
                      ? "bg-sky-600 text-white font-medium"
                      : "bg-gray-800 text-sky-400 hover:bg-gray-700"
                  }`}
                >
                  Telegram
                </button>
                <button
                  type="button"
                  onClick={() => setChannelFilter("internal")}
                  className={`px-2.5 py-1 rounded-full whitespace-nowrap transition-colors ${
                    channelFilter === "internal"
                      ? "bg-purple-600 text-white font-medium"
                      : "bg-gray-800 text-purple-400 hover:bg-gray-700"
                  }`}
                >
                  Nội bộ
                </button>
              </div>

              {/* Search input */}
              <div className="relative">
                <Search className="w-3.5 h-3.5 text-gray-400 absolute left-3 top-2.5" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Tìm theo tên khách, nội dung..."
                  className="w-full bg-gray-950 border border-gray-800 rounded-lg pl-8 pr-3 py-1.5 text-xs text-gray-200 placeholder-gray-500 focus:outline-none focus:border-sky-500"
                />
              </div>
            </div>

            {/* Conversation List Items */}
            <div className="flex-1 overflow-y-auto divide-y divide-gray-800/60">
              {isLoading ? (
                <div className="flex justify-center py-10 text-gray-500 text-xs">
                  <Clock className="w-4 h-4 animate-spin mr-2" /> Đang tải danh sách...
                </div>
              ) : filteredConversations.length === 0 ? (
                <div className="text-center py-12 px-4 text-gray-500 text-xs">
                  Không tìm thấy cuộc hội thoại nào phù hợp.
                </div>
              ) : (
                filteredConversations.map((conv) => {
                  const isSelected = conv.id === selectedConvId;
                  return (
                    <button
                      key={conv.id}
                      type="button"
                      onClick={() => setSelectedConvId(conv.id)}
                      className={`w-full p-4 text-left flex items-start gap-3 transition-colors cursor-pointer ${
                        isSelected
                          ? "bg-gray-800/90 border-l-4 border-sky-500"
                          : "hover:bg-gray-800/40"
                      }`}
                    >
                      <div className="w-9 h-9 rounded-full bg-gray-800 border border-gray-700 flex items-center justify-center font-bold text-sky-400 shrink-0 text-sm">
                        {conv.participant_name ? conv.participant_name.charAt(0).toUpperCase() : "K"}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between mb-1">
                          <h4 className="text-xs font-semibold text-white truncate">
                            {conv.participant_name || "Khách hàng"}
                          </h4>
                          <span className="text-[10px] text-gray-400 shrink-0">
                            {conv.channel.toUpperCase()}
                          </span>
                        </div>
                        <p className="text-xs text-gray-400 truncate">
                          {conv.last_message?.content || conv.title || "Chưa có tin nhắn..."}
                        </p>
                        <div className="flex items-center gap-2 mt-1.5">
                          {conv.is_human_takeover ? (
                            <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-500/10 text-amber-400 border border-amber-500/30">
                              Người xử lý
                            </span>
                          ) : (
                            <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                              AI
                            </span>
                          )}
                          {conv.status === "waiting" && (
                            <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-rose-500/10 text-rose-400 border border-rose-500/30">
                              Cần trả lời
                            </span>
                          )}
                        </div>
                      </div>
                    </button>
                  );
                })
              )}
            </div>
          </section>

          {/* Right Column: Thread Panel */}
          <ThreadPanel
            conversation={selectedConversation}
            messages={messages}
            isAiGenerating={isAiGenerating}
            onTakeover={handleTakeover}
            onRelease={handleRelease}
            onSendReply={handleSendReply}
            isLoadingMessages={isLoadingMessages}
          />
        </div>
      </div>

      {/* QR Re-Auth Modal */}
      {showQrModal && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-gray-900 border border-gray-800 rounded-2xl max-w-sm w-full p-6 text-center shadow-2xl">
            <h3 className="text-base font-bold text-white mb-2">Quét mã QR kết nối</h3>
            <p className="text-xs text-gray-400 mb-4">
              Mở ứng dụng Zalo trên điện thoại, vào phần Quét mã QR để xác thực lại phiên kết nối OA.
            </p>
            <div className="w-48 h-48 mx-auto bg-white p-3 rounded-xl shadow-inner flex items-center justify-center mb-4">
              <QrCode className="w-36 h-36 text-gray-900" />
            </div>
            <button
              type="button"
              onClick={() => setShowQrModal(null)}
              className="w-full py-2 rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-200 text-xs font-medium transition-colors"
            >
              Đóng
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
