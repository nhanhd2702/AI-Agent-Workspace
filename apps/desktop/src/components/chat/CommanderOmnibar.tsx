"use client";

import React, { useState, useRef, useEffect } from "react";
import {
  Paperclip,
  Image as ImageIcon,
  Camera,
  Send,
  Square,
  Mic,
  ChevronDown,
  Search,
  Sparkles,
  Bot,
  Users,
  Wrench,
  Link2,
  FolderClosed,
  FileText,
  X,
  Check,
} from "lucide-react";
import { AgentChibiAvatar } from "../layout/SidebarNav";

export interface CommanderOmnibarProps {
  onSubmit?: (data: {
    prompt: string;
    targetAgent?: string;
    model?: string;
    team?: string;
    format?: string;
    handsfree?: boolean;
    attachments?: File[];
  }) => void | Promise<void>;
  isStreaming?: boolean;
  onStop?: () => void;
  placeholder?: string;
  className?: string;
}

export type OmnibarTab = "Agent" | "Đội" | "Skills" | "Connectors" | "Thư viện" | "Trang";

export interface AgentItem {
  id: string;
  name: string;
  role: string;
  team: string;
  isCustom?: boolean;
}

export const TAKO_AGENTS: AgentItem[] = [
  { id: "commander", name: "Người điều phối", role: "Chỉ huy tổng & phân chia tác vụ", team: "Tổng bộ" },
  { id: "researcher", name: "DeepResearcher", role: "Nghiên cứu thị trường & dữ liệu sâu", team: "Đội Kỹ thuật" },
  { id: "writer", name: "ContentWriter", role: "Sáng tạo nội dung viral đa kênh", team: "Đội Content" },
  { id: "ui", name: "UIDesigner", role: "Thiết kế giao diện Interactive Web/Landing", team: "Đội Funnels" },
  { id: "video", name: "VideoEditor", role: "Biên tập video & kịch bản động", team: "Đội Media" },
  { id: "funnels", name: "FunnelsAgent", role: "Kiến trúc phễu bán hàng tự động", team: "Đội Funnels" },
  { id: "hook", name: "HookMaster", role: "Tạo tiêu đề & câu móc triệu view", team: "Đội Content" },
  { id: "vsl", name: "VslWriter", role: "Viết kịch bản video bán hàng VSL", team: "Đội Funnels" },
  { id: "cskh", name: "CSKH", role: "Chăm sóc khách hàng & xử lý khiếu nại", team: "Vận hành", isCustom: true },
  { id: "sales", name: "SalesAgent", role: "Tư vấn & chốt đơn tự động", team: "Kinh doanh", isCustom: true },
  { id: "report", name: "ReportAgent", role: "Tổng hợp số liệu & báo cáo tiến độ", team: "Vận hành", isCustom: true },
  { id: "leadmagnet", name: "LeadMagnetMaker", role: "Thiết kế quà tặng hút khách hàng tiềm năng", team: "Đội Funnels" },
  { id: "email", name: "EmailSpecialist", role: "Soạn chuỗi email nuôi dưỡng chuyển đổi cao", team: "Đội Content" },
  { id: "seo", name: "SEOStrategist", role: "Tối ưu hóa công cụ tìm kiếm chuẩn Top 1", team: "Đội Content" },
  { id: "image", name: "ImageStudio", role: "Sinh ảnh minh họa AI & banner chuyên nghiệp", team: "Đội Media" },
  { id: "code", name: "CodeArchitect", role: "Xây dựng mã nguồn & tích hợp API", team: "Đội Kỹ thuật" },
];

export const TAKO_TEAMS = [
  { id: "none", name: "Chưa vào phòng", description: "Tác tử hoạt động độc lập" },
  { id: "content", name: "Đội Content", description: "Chuyên trách bài viết, kịch bản, email, bài PR" },
  { id: "funnels", name: "Đội Funnels", description: "Chuyên trách trang đích, optin, phễu chuyển đổi" },
  { id: "media", name: "Đội Media", description: "Chuyên đồ họa, hình ảnh AI, video ngắn" },
];

export const TAKO_SKILLS = [
  { id: "web_search", name: "Google & Deep Web Search", desc: "Tra cứu thông tin thời gian thực" },
  { id: "html_generator", name: "Interactive HTML Sandbox", desc: "Tạo landing page hoặc mini app chạy offline" },
  { id: "video_script", name: "Viral Video Script 60s", desc: "Viết kịch bản TikTok/Reels giữ chân cao" },
  { id: "canva_connect", name: "Canva Direct Export", desc: "Đồng bộ mẫu thiết kế sang Canva" },
];

export const TAKO_CONNECTORS = [
  { id: "chrome", name: "Chrome Browser Live", desc: "Duyệt web và trích xuất dữ liệu trực tiếp" },
  { id: "files", name: "Local File System", desc: "Đọc ghi tệp trên máy tính an toàn" },
  { id: "zalo", name: "Zalo OA Official", desc: "Nhận và trả lời tin nhắn Zalo khách hàng" },
  { id: "notion", name: "Notion Workspace", desc: "Đồng bộ ghi chú và tài liệu dự án" },
];

export const TAKO_MODELS = [
  { id: "gpt-6-luna", name: "GPT-6 Luna (Mặc định)" },
  { id: "claude-3-7-sonnet", name: "Claude 3.7 Sonnet (Thinking)" },
  { id: "antigravity-cli", name: "⚡ Antigravity CLI (agy -p, Miễn phí)" },
  { id: "gemini-2-5-flash", name: "Gemini 2.5 Flash (Siêu tốc)" },
  { id: "deepseek-r1", name: "DeepSeek R1 (Lý luận sâu)" },
];

export const TAKO_FORMATS = [
  { id: "default", name: "Mặc định (Tự động)" },
  { id: "interactive-html", name: "Interactive HTML (Chạy trực tiếp)" },
  { id: "video-script", name: "Kịch bản Video Dọc 9:16" },
  { id: "markdown-doc", name: "Tài liệu Markdown chuẩn" },
];

export function CommanderOmnibar({
  onSubmit,
  isStreaming = false,
  onStop,
  placeholder = "Hôm nay bạn muốn hoàn thành việc gì? Nói mục tiêu, Người điều phối sẽ chia việc cho đúng Agent...",
  className = "",
}: CommanderOmnibarProps) {
  const [prompt, setPrompt] = useState("");
  const [selectedAgent, setSelectedAgent] = useState<string>("Người điều phối");
  const [selectedModel, setSelectedModel] = useState<string>("GPT-6 Luna");
  const [selectedTeam, setSelectedTeam] = useState<string>("chưa chọn");
  const [selectedFormat, setSelectedFormat] = useState<string>("Mặc định");
  const [isHandsfree, setIsHandsfree] = useState(false);
  const [attachedFiles, setAttachedFiles] = useState<File[]>([]);

  // Popup 6 tabs state
  const [isPopupOpen, setIsPopupOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<OmnibarTab>("Agent");
  const [searchFilter, setSearchFilter] = useState("");

  const popupRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Close popup on outside click
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (popupRef.current && !popupRef.current.contains(event.target as Node)) {
        setIsPopupOpen(false);
      }
    }
    if (isPopupOpen) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [isPopupOpen]);

  const handleSend = () => {
    if ((!prompt.trim() && attachedFiles.length === 0) || isStreaming) return;
    if (onSubmit) {
      onSubmit({
        prompt: prompt.trim(),
        targetAgent: selectedAgent,
        model: selectedModel,
        team: selectedTeam,
        format: selectedFormat,
        handsfree: isHandsfree,
        attachments: attachedFiles,
      });
    }
    setPrompt("");
    setAttachedFiles([]);
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      const newFiles = Array.from(e.target.files);
      setAttachedFiles((prev) => [...prev, ...newFiles]);
    }
  };

  const removeFile = (idx: number) => {
    setAttachedFiles((prev) => prev.filter((_, i) => i !== idx));
  };

  // Filter agents by search query
  const filteredAgents = TAKO_AGENTS.filter(
    (a) =>
      a.name.toLowerCase().includes(searchFilter.toLowerCase()) ||
      a.role.toLowerCase().includes(searchFilter.toLowerCase()) ||
      a.team.toLowerCase().includes(searchFilter.toLowerCase())
  );

  return (
    <div className={`relative w-full bg-slate-900 border border-slate-700/80 rounded-2xl shadow-2xl p-3 flex flex-col gap-2.5 backdrop-blur-md ${className}`}>
      {/* Hidden file inputs */}
      <input
        type="file"
        ref={fileInputRef}
        className="hidden"
        multiple
        onChange={handleFileChange}
      />
      <input
        type="file"
        ref={imageInputRef}
        className="hidden"
        accept="image/*"
        multiple
        onChange={handleFileChange}
      />

      {/* Top Attachment Chips (if any) */}
      {attachedFiles.length > 0 && (
        <div className="flex flex-wrap gap-2 pb-1">
          {attachedFiles.map((file, idx) => (
            <div
              key={idx}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-slate-800 border border-slate-700 text-xs text-slate-200"
            >
              <Paperclip className="w-3 h-3 text-indigo-400" />
              <span className="max-w-[150px] truncate">{file.name}</span>
              <button
                type="button"
                onClick={() => removeFile(idx)}
                className="hover:text-red-400 text-slate-400"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Main Omnibar Input Area */}
      <div className="flex items-start gap-2">
        {/* Left Attachment Actions */}
        <div className="flex items-center gap-1 pt-1.5 text-slate-400">
          <button
            type="button"
            title="Đính kèm tệp"
            onClick={() => fileInputRef.current?.click()}
            className="p-1.5 rounded-lg hover:bg-slate-800 hover:text-slate-200 transition-colors"
          >
            <Paperclip className="w-4 h-4" />
          </button>
          <button
            type="button"
            title="Đính kèm ảnh"
            onClick={() => imageInputRef.current?.click()}
            className="p-1.5 rounded-lg hover:bg-slate-800 hover:text-slate-200 transition-colors"
          >
            <ImageIcon className="w-4 h-4" />
          </button>
          <button
            type="button"
            title="Ảnh chụp màn hình"
            onClick={() => {
              // Trigger screen capture simulation
              alert("Chức năng chụp màn hình sẵn sàng");
            }}
            className="p-1.5 rounded-lg hover:bg-slate-800 hover:text-slate-200 transition-colors"
          >
            <Camera className="w-4 h-4" />
          </button>
        </div>

        {/* Text Input Area */}
        <div className="flex-1 min-w-0">
          <textarea
            ref={textareaRef}
            rows={2}
            value={prompt}
            onChange={(e) => {
              setPrompt(e.target.value);
              e.target.style.height = "auto";
              e.target.style.height = `${Math.min(e.target.scrollHeight, 180)}px`;
            }}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            className="w-full bg-transparent resize-none text-sm text-slate-100 placeholder-slate-400 focus:outline-none focus:ring-0 leading-relaxed max-h-[180px] py-1"
          />
        </div>
      </div>

      {/* Bottom Controls Bar */}
      <div className="flex flex-wrap items-center justify-between gap-2 pt-1 border-t border-slate-800/80 text-xs">
        {/* Left Selectors */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Target Destination Agent/Team Button with 6-Tab Popup */}
          <div className="relative">
            <button
              type="button"
              data-testid="target-dest-btn"
              onClick={() => setIsPopupOpen(!isPopupOpen)}
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-slate-800/90 hover:bg-slate-700/80 border border-slate-700 text-slate-200 font-medium transition-all"
            >
              <span className="text-slate-400 text-[11px]">Gửi tới:</span>
              <AgentChibiAvatar agentId={selectedAgent} size="sm" />
              <span className="text-indigo-300 font-semibold">{selectedAgent}</span>
              <ChevronDown className="w-3.5 h-3.5 text-slate-400" />
            </button>

            {/* 6-Tab Floating Popup */}
            {isPopupOpen && (
              <div
                ref={popupRef}
                className="absolute bottom-full left-0 mb-2 w-80 sm:w-96 bg-slate-900 border border-slate-700 rounded-xl shadow-2xl z-50 overflow-hidden flex flex-col animate-in fade-in zoom-in-95 duration-100"
              >
                {/* 6 Tabs Navigation Header */}
                <div className="flex items-center border-b border-slate-800 bg-slate-950/60 p-1 overflow-x-auto no-scrollbar" role="tablist">
                  {(["Agent", "Đội", "Skills", "Connectors", "Thư viện", "Trang"] as OmnibarTab[]).map((tab) => (
                    <button
                      key={tab}
                      role="tab"
                      aria-selected={activeTab === tab}
                      onClick={() => setActiveTab(tab)}
                      className={`px-3 py-1.5 rounded-md text-xs font-medium whitespace-nowrap transition-all ${
                        activeTab === tab
                          ? "bg-indigo-600 text-white shadow-sm"
                          : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"
                      }`}
                    >
                      {tab}
                    </button>
                  ))}
                </div>

                {/* Tab Search Filter */}
                <div className="p-2 border-b border-slate-800/80 bg-slate-900/50">
                  <div className="relative">
                    <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-2.5" />
                    <input
                      type="text"
                      placeholder={`Tìm kiếm ${activeTab.toLowerCase()}...`}
                      value={searchFilter}
                      onChange={(e) => setSearchFilter(e.target.value)}
                      className="w-full bg-slate-800 text-slate-100 text-xs rounded-lg pl-8 pr-3 py-1.5 border border-slate-700 focus:outline-none focus:border-indigo-500"
                    />
                  </div>
                </div>

                {/* Tab Content List */}
                <div className="max-h-60 overflow-y-auto p-1.5 space-y-1">
                  {/* TAB 1: AGENTS */}
                  {activeTab === "Agent" && (
                    <>
                      <div className="px-2 py-1 text-[10px] font-semibold text-slate-400 uppercase tracking-wider">
                        Danh sách Agent ({filteredAgents.length})
                      </div>
                      {filteredAgents.map((agent) => (
                        <div
                          key={agent.id}
                          onClick={() => {
                            setSelectedAgent(agent.name);
                            setIsPopupOpen(false);
                          }}
                          className={`flex items-center justify-between p-2 rounded-lg cursor-pointer transition-colors ${
                            selectedAgent === agent.name
                              ? "bg-indigo-600/20 border border-indigo-500/40 text-indigo-300"
                              : "hover:bg-slate-800/80 text-slate-300"
                          }`}
                        >
                          <div className="flex items-center gap-2">
                            <AgentChibiAvatar agentId={agent.name} size="sm" />
                            <div>
                              <div className="flex items-center gap-1.5">
                                <span className="font-semibold text-xs">{agent.name}</span>
                                {agent.isCustom && (
                                  <span className="px-1 py-0.2 rounded text-[9px] bg-amber-500/20 text-amber-300 font-mono">
                                    Tùy biến
                                  </span>
                                )}
                              </div>
                              <p className="text-[10px] text-slate-400">{agent.role}</p>
                            </div>
                          </div>
                          {selectedAgent === agent.name && <Check className="w-3.5 h-3.5 text-indigo-400" />}
                        </div>
                      ))}
                    </>
                  )}

                  {/* TAB 2: ĐỘI (TEAMS) */}
                  {activeTab === "Đội" && (
                    <>
                      <div className="px-2 py-1 text-[10px] font-semibold text-slate-400 uppercase tracking-wider">
                        Phòng ban & Nhóm tác tử
                      </div>
                      {TAKO_TEAMS.map((team) => (
                        <div
                          key={team.id}
                          onClick={() => {
                            setSelectedTeam(team.name);
                            setIsPopupOpen(false);
                          }}
                          className={`p-2 rounded-lg cursor-pointer transition-colors ${
                            selectedTeam === team.name
                              ? "bg-indigo-600/20 border border-indigo-500/40 text-indigo-300"
                              : "hover:bg-slate-800/80 text-slate-300"
                          }`}
                        >
                          <div className="font-semibold text-xs flex items-center justify-between">
                            <span>{team.name}</span>
                            {selectedTeam === team.name && <Check className="w-3.5 h-3.5 text-indigo-400" />}
                          </div>
                          <p className="text-[10px] text-slate-400">{team.description}</p>
                        </div>
                      ))}
                    </>
                  )}

                  {/* TAB 3: SKILLS */}
                  {activeTab === "Skills" && (
                    <>
                      <div className="px-2 py-1 text-[10px] font-semibold text-slate-400 uppercase tracking-wider">
                        Kỹ năng chuyên môn
                      </div>
                      {TAKO_SKILLS.map((skill) => (
                        <div
                          key={skill.id}
                          onClick={() => {
                            setPrompt((prev) => `${prev} [Kỹ năng: ${skill.name}]`.trim());
                            setIsPopupOpen(false);
                          }}
                          className="p-2 rounded-lg hover:bg-slate-800/80 text-slate-300 cursor-pointer"
                        >
                          <div className="font-semibold text-xs text-indigo-300">{skill.name}</div>
                          <p className="text-[10px] text-slate-400">{skill.desc}</p>
                        </div>
                      ))}
                    </>
                  )}

                  {/* TAB 4: CONNECTORS */}
                  {activeTab === "Connectors" && (
                    <>
                      <div className="px-2 py-1 text-[10px] font-semibold text-slate-400 uppercase tracking-wider">
                        Cổng kết nối ứng dụng bên ngoài
                      </div>
                      {TAKO_CONNECTORS.map((conn) => (
                        <div
                          key={conn.id}
                          onClick={() => {
                            setPrompt((prev) => `${prev} [Kết nối: ${conn.name}]`.trim());
                            setIsPopupOpen(false);
                          }}
                          className="p-2 rounded-lg hover:bg-slate-800/80 text-slate-300 cursor-pointer"
                        >
                          <div className="font-semibold text-xs text-emerald-300">{conn.name}</div>
                          <p className="text-[10px] text-slate-400">{conn.desc}</p>
                        </div>
                      ))}
                    </>
                  )}

                  {/* TAB 5: THƯ VIỆN */}
                  {activeTab === "Thư viện" && (
                    <div className="p-4 text-center text-slate-400 text-xs">
                      <FolderClosed className="w-8 h-8 text-slate-600 mx-auto mb-1" />
                      Thư viện kết quả mẫu & tệp tải về
                    </div>
                  )}

                  {/* TAB 6: TRANG */}
                  {activeTab === "Trang" && (
                    <div className="p-4 text-center text-slate-400 text-xs">
                      <FileText className="w-8 h-8 text-slate-600 mx-auto mb-1" />
                      Trang tài liệu nội bộ & mẫu template
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Model Selector Dropdown */}
          <div className="relative">
            <select
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
              className="bg-slate-800/90 text-slate-300 text-xs rounded-lg px-2.5 py-1.5 border border-slate-700 hover:border-slate-600 focus:outline-none focus:border-indigo-500 cursor-pointer"
            >
              <option value="GPT-6 Luna">GPT-6 Luna</option>
              <option value="Claude 3.7 Sonnet">Claude 3.7 Sonnet</option>
              <option value="⚡ Antigravity CLI (agy -p)">⚡ Antigravity CLI (agy -p)</option>
              <option value="Gemini 2.5 Flash">Gemini 2.5 Flash</option>
              <option value="DeepSeek R1">DeepSeek R1</option>
            </select>
          </div>

          {/* Team Selector Dropdown */}
          <div className="relative hidden sm:block">
            <select
              value={selectedTeam}
              onChange={(e) => setSelectedTeam(e.target.value)}
              className="bg-slate-800/90 text-slate-300 text-xs rounded-lg px-2.5 py-1.5 border border-slate-700 hover:border-slate-600 focus:outline-none focus:border-indigo-500 cursor-pointer"
            >
              <option value="chưa chọn">Đội: chưa chọn</option>
              <option value="Đội Content">Đội Content</option>
              <option value="Đội Funnels">Đội Funnels</option>
              <option value="Đội Media">Đội Media</option>
            </select>
          </div>

          {/* Output Format Selector Dropdown */}
          <div className="relative hidden md:block">
            <select
              value={selectedFormat}
              onChange={(e) => setSelectedFormat(e.target.value)}
              className="bg-slate-800/90 text-slate-300 text-xs rounded-lg px-2.5 py-1.5 border border-slate-700 hover:border-slate-600 focus:outline-none focus:border-indigo-500 cursor-pointer"
            >
              <option value="Mặc định">Định dạng: Mặc định</option>
              <option value="Interactive HTML">Interactive HTML</option>
              <option value="Video Dọc">Video Dọc</option>
              <option value="Post Facebook">Post Facebook</option>
            </select>
          </div>
        </div>

        {/* Right Actions: Handsfree Voice Toggle & Submit */}
        <div className="flex items-center gap-2">
          {/* Handsfree (Rảnh tay) Mode Toggle */}
          <button
            type="button"
            onClick={() => setIsHandsfree(!isHandsfree)}
            aria-label="Rảnh tay"
            className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-xs font-medium transition-all ${
              isHandsfree
                ? "bg-indigo-600 border-indigo-500 text-white shadow-lg shadow-indigo-600/30 animate-pulse"
                : "bg-slate-800/90 hover:bg-slate-700/80 border-slate-700 text-slate-300"
            }`}
          >
            <Mic className={`w-3.5 h-3.5 ${isHandsfree ? "text-white" : "text-indigo-400"}`} />
            <span>Rảnh tay</span>
          </button>

          {/* Submit / Stop Button */}
          {isStreaming ? (
            <button
              type="button"
              aria-label="Dừng lệnh"
              onClick={onStop}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-600 hover:bg-red-500 text-white font-medium text-xs shadow-md transition-all"
            >
              <Square className="w-3.5 h-3.5 fill-current" />
              <span>Dừng</span>
            </button>
          ) : (
            <button
              type="button"
              aria-label="Gửi lệnh"
              onClick={handleSend}
              disabled={!prompt.trim() && attachedFiles.length === 0}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-medium text-xs shadow-md shadow-indigo-600/20 transition-all"
            >
              <Send className="w-3.5 h-3.5" />
              <span>Gửi</span>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
