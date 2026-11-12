"use client";

import React, { useState, useRef, useEffect, useId } from "react";
import {
  Send,
  Paperclip,
  X,
  FileText,
  Sparkles,
  Bot,
  SlidersHorizontal,
  AlertCircle,
} from "lucide-react";
import { Agent, AttachmentItem, ExecutionMode } from "@/lib/types";

export interface CommanderPromptBoxProps {
  agents?: Agent[];
  onSubmit?: (data: {
    prompt: string;
    mode: ExecutionMode;
    attachments: AttachmentItem[];
  }) => void | Promise<void>;
  isSubmitting?: boolean;
  placeholder?: string;
  className?: string;
}

const DEFAULT_AGENTS: Agent[] = [
  { id: "1", name: "ContentWriter", displayName: "ContentWriter", role: "Sáng tạo nội dung", status: "idle" },
  { id: "2", name: "DeepResearcher", displayName: "DeepResearcher", role: "Nghiên cứu thị trường", status: "idle" },
  { id: "3", name: "ImageStudio", displayName: "ImageStudio", role: "Thiết kế đồ họa", status: "idle" },
  { id: "4", name: "UIDesigner", displayName: "UIDesigner", role: "Thiết kế giao diện", status: "idle" },
  { id: "5", name: "VideoEditor", displayName: "VideoEditor", role: "Biên tập video", status: "idle" },
  { id: "6", name: "FunnelsAgent", displayName: "FunnelsAgent", role: "Chiến lược phễu", status: "idle" },
];

const SUGGESTIONS = [
  "Nghiên cứu kênh YouTube đối thủ và gợi ý 5 chủ đề viral",
  "Viết bài Facebook phân tích xu hướng AI Agents 2026",
  "Thiết kế landing page giới thiệu sản phẩm mới chuẩn SEO",
];

export function CommanderPromptBox({
  agents = DEFAULT_AGENTS,
  onSubmit,
  isSubmitting = false,
  placeholder = "Hôm nay bạn muốn hoàn thành việc gì?",
  className = "",
}: CommanderPromptBoxProps) {
  const [prompt, setPrompt] = useState("");
  const [mode, setMode] = useState<ExecutionMode>("copilot");
  const [attachments, setAttachments] = useState<AttachmentItem[]>([]);
  const [attachmentError, setAttachmentError] = useState<string | null>(null);

  // Mention autocomplete state
  const [mentionQuery, setMentionQuery] = useState<string | null>(null);
  const [mentionIndex, setMentionIndex] = useState(0);
  const [mentionPosition, setMentionPosition] = useState<{ start: number; end: number } | null>(null);

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dropZoneRef = useRef<HTMLDivElement>(null);
  const [isDraggingOver, setIsDraggingOver] = useState(false);

  const fileInputId = useId();

  // Normalize and filter agents for mention
  const normalizedAgents = (agents && agents.length > 0 ? agents : DEFAULT_AGENTS).map((a) => ({
    ...a,
    resolvedDisplayName: a.displayName || a.display_name || a.name,
  }));

  const filteredAgents = mentionQuery !== null
    ? normalizedAgents.filter((agent) => {
        const q = mentionQuery.toLowerCase();
        return (
          agent.name.toLowerCase().includes(q) ||
          agent.resolvedDisplayName.toLowerCase().includes(q)
        );
      })
    : [];

  // Inspect input text to detect '@' mention trigger
  const checkMentionTrigger = (text: string, cursorPos: number) => {
    const textBeforeCursor = text.slice(0, cursorPos);
    // Match '@' followed by non-space characters right up to cursor
    const match = textBeforeCursor.match(/(?:^|\s)@([a-zA-Z0-9_]*)$/);

    if (match) {
      const matchedString = match[0];
      const atIndex = textBeforeCursor.lastIndexOf("@");
      setMentionQuery(match[1]);
      setMentionPosition({ start: atIndex, end: cursorPos });
      setMentionIndex(0);
    } else {
      setMentionQuery(null);
      setMentionPosition(null);
    }
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const val = e.target.value;
    setPrompt(val);
    const cursorPos = e.target.selectionStart || val.length;
    checkMentionTrigger(val, cursorPos);
  };

  const insertMention = (agent: Agent) => {
    if (!mentionPosition || !textareaRef.current) {
      // Fallback: append or replace at end
      setPrompt((prev) => prev.replace(/@\w*$/, `@${agent.name} `));
      setMentionQuery(null);
      return;
    }

    const before = prompt.slice(0, mentionPosition.start);
    const after = prompt.slice(mentionPosition.end);
    const updated = `${before}@${agent.name} ${after}`;

    setPrompt(updated);
    setMentionQuery(null);
    setMentionPosition(null);

    // Restore focus to textarea
    setTimeout(() => {
      if (textareaRef.current) {
        const newCursor = before.length + agent.name.length + 2;
        textareaRef.current.focus();
        textareaRef.current.setSelectionRange(newCursor, newCursor);
      }
    }, 10);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Autocomplete popover keyboard navigation
    if (mentionQuery !== null && filteredAgents.length > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setMentionIndex((prev) => (prev + 1) % filteredAgents.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setMentionIndex((prev) => (prev - 1 + filteredAgents.length) % filteredAgents.length);
        return;
      }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        if (filteredAgents[mentionIndex]) {
          insertMention(filteredAgents[mentionIndex]);
        }
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setMentionQuery(null);
        setMentionPosition(null);
        return;
      }
    }

    // Submit on Enter without Shift
    if (e.key === "Enter" && !e.shiftKey) {
      if (canSubmit) {
        e.preventDefault();
        handleSubmit();
      }
    }
  };

  // File handling (enforces <= 10 attachments)
  const processFiles = (fileList: FileList | File[]) => {
    const incoming = Array.from(fileList);
    const totalCount = attachments.length + incoming.length;

    if (totalCount > 10) {
      setAttachmentError("Tối đa 10 tệp đính kèm mỗi lệnh; các tệp vượt mức đã được loại bỏ.");
    } else {
      setAttachmentError(null);
    }

    const allowedIncoming = incoming.slice(0, Math.max(0, 10 - attachments.length));
    const newItems: AttachmentItem[] = allowedIncoming.map((file, idx) => ({
      id: `att-${Date.now()}-${idx}-${Math.random().toString(36).substring(2, 7)}`,
      name: file.name,
      size: file.size,
      type: file.type || "application/octet-stream",
      file,
    }));

    setAttachments((prev) => [...prev, ...newItems].slice(0, 10));
  };

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      processFiles(e.target.files);
      // Reset input value so re-selecting same file works
      e.target.value = "";
    }
  };

  const removeAttachment = (id: string) => {
    setAttachments((prev) => prev.filter((a) => a.id !== id));
    if (attachments.length - 1 <= 10) {
      setAttachmentError(null);
    }
  };

  // Drag and drop handlers
  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDraggingOver(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDraggingOver(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDraggingOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      processFiles(e.dataTransfer.files);
    }
  };

  const charCount = prompt.length;
  const isOverLimit = charCount > 2000;
  const isTrimmedEmpty = prompt.trim().length === 0;
  const canSubmit = !isTrimmedEmpty && !isOverLimit && !isSubmitting;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    const submittedPrompt = prompt;
    const submittedMode = mode;
    const submittedAttachments = [...attachments];

    try {
      await onSubmit?.({
        prompt: submittedPrompt,
        mode: submittedMode,
        attachments: submittedAttachments,
      });
      // Clear inputs upon submit
      setPrompt("");
      setAttachments([]);
      setAttachmentError(null);
      setMentionQuery(null);
    } catch {
      // Keep input intact if parent throws
    }
  };

  const formatFileSize = (bytes?: number) => {
    if (!bytes) return "";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  return (
    <div className={`w-full max-w-4xl mx-auto ${className}`} data-testid="commander-prompt-box">
      {/* Container with drag-drop zone */}
      <div
        ref={dropZoneRef}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={`relative bg-gray-900 border rounded-2xl shadow-xl transition-all duration-200 overflow-hidden ${
          isDraggingOver
            ? "border-sky-500 ring-2 ring-sky-500/30 bg-sky-950/20"
            : isOverLimit
            ? "border-rose-500/80 ring-1 ring-rose-500/20"
            : "border-gray-800 hover:border-gray-700 focus-within:border-sky-500/80 focus-within:ring-2 focus-within:ring-sky-500/20"
        }`}
      >
        {/* Drag Overlay Notice */}
        {isDraggingOver && (
          <div className="absolute inset-0 z-20 bg-gray-950/80 backdrop-blur-xs flex items-center justify-center border-2 border-dashed border-sky-400 rounded-2xl pointer-events-none">
            <div className="text-center text-sky-400">
              <Paperclip className="w-8 h-8 mx-auto mb-2 animate-bounce" />
              <p className="text-sm font-medium">Thả tệp vào đây để đính kèm (Tối đa 10 tệp)</p>
            </div>
          </div>
        )}

        {/* Autocomplete Popover for @mention */}
        {mentionQuery !== null && filteredAgents.length > 0 && (
          <div
            className="absolute left-4 bottom-24 z-30 w-80 max-h-64 overflow-y-auto bg-gray-800/95 backdrop-blur-md border border-gray-700 rounded-xl shadow-2xl p-1.5 space-y-1 animate-in fade-in slide-in-from-bottom-2 duration-150"
            role="listbox"
            aria-label="Gợi ý chuyên viên AI"
          >
            <div className="px-2 py-1 text-[11px] font-semibold text-gray-400 uppercase tracking-wider flex items-center gap-1.5">
              <Bot className="w-3.5 h-3.5 text-sky-400" />
              <span>Gán chuyên viên (@mention)</span>
            </div>
            {filteredAgents.map((agent, index) => {
              const isSelected = index === mentionIndex;
              return (
                <button
                  key={agent.id}
                  type="button"
                  role="option"
                  aria-selected={isSelected}
                  onClick={() => insertMention(agent)}
                  onMouseEnter={() => setMentionIndex(index)}
                  className={`w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-left text-xs transition-colors cursor-pointer ${
                    isSelected
                      ? "bg-sky-600/30 text-white border border-sky-500/30"
                      : "text-gray-300 hover:bg-gray-700/50"
                  }`}
                >
                  <div className="w-7 h-7 rounded-full bg-gradient-to-br from-sky-500 to-indigo-600 flex items-center justify-center font-bold text-white text-[11px] shrink-0">
                    {agent.name.slice(0, 2).toUpperCase()}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-white truncate flex items-center gap-1.5">
                      <span>{agent.resolvedDisplayName}</span>
                      <span className="text-[10px] text-sky-400 font-mono">@{agent.name}</span>
                    </div>
                    <div className="text-[11px] text-gray-400 truncate">{agent.role}</div>
                  </div>
                </button>
              );
            })}
          </div>
        )}

        {/* Attachment Error Banner */}
        {attachmentError && (
          <div className="px-4 py-2 bg-rose-950/40 border-b border-rose-900/50 text-xs text-rose-300 flex items-center gap-2">
            <AlertCircle className="w-4 h-4 shrink-0 text-rose-400" />
            <span>{attachmentError}</span>
          </div>
        )}

        {/* Attachment Chips List */}
        {attachments.length > 0 && (
          <div className="px-4 pt-3 pb-1 flex flex-wrap gap-2">
            {attachments.map((item) => (
              <div
                key={item.id}
                className="inline-flex items-center gap-2 px-2.5 py-1 rounded-lg bg-gray-800 border border-gray-700 text-xs text-gray-200 shadow-xs"
              >
                <FileText className="w-3.5 h-3.5 text-sky-400 shrink-0" />
                <span className="font-medium truncate max-w-[160px]" title={item.name}>
                  {item.name}
                </span>
                {item.size && (
                  <span className="text-[10px] text-gray-400">({formatFileSize(item.size)})</span>
                )}
                <button
                  type="button"
                  onClick={() => removeAttachment(item.id)}
                  className="text-gray-400 hover:text-rose-400 transition-colors p-0.5 rounded cursor-pointer"
                  aria-label={`Xóa ${item.name}`}
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Main Textarea */}
        <div className="p-4">
          <textarea
            ref={textareaRef}
            value={prompt}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            rows={3}
            className="w-full bg-transparent text-gray-100 placeholder-gray-500 text-sm md:text-base resize-none focus:outline-none leading-relaxed"
            aria-label="Nội dung yêu cầu công việc"
          />
        </div>

        {/* Error Warning for 2000 Character Exceeded */}
        {isOverLimit && (
          <div className="px-4 pb-2 text-xs text-rose-400 flex items-center gap-1.5">
            <AlertCircle className="w-3.5 h-3.5 shrink-0" />
            <span>Giới hạn 2.000 ký tự mỗi lệnh; hãy đính kèm file tài liệu nếu nội dung dài hơn.</span>
          </div>
        )}

        {/* Controls Footer */}
        <div className="px-4 py-3 bg-gray-950/40 border-t border-gray-800/80 flex flex-wrap items-center justify-between gap-3">
          {/* Left Actions: File Picker & Execution Mode Toggle */}
          <div className="flex items-center gap-3">
            {/* Hidden File Input */}
            <input
              id={fileInputId}
              ref={fileInputRef}
              type="file"
              multiple
              onChange={handleFileInputChange}
              className="hidden"
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium text-gray-400 hover:text-gray-200 hover:bg-gray-800 transition-colors cursor-pointer border border-transparent hover:border-gray-700"
              title="Đính kèm tệp (Tối đa 10 tệp)"
            >
              <Paperclip className="w-4 h-4 text-sky-400" />
              <span>Đính kèm tệp</span>
              {attachments.length > 0 && (
                <span className="ml-0.5 px-1.5 py-0.2 rounded-full bg-gray-700 text-[10px] text-gray-300">
                  {attachments.length}/10
                </span>
              )}
            </button>

            {/* Mode Switcher: Co-pilot vs Auto-pilot (Rảnh tay) */}
            <div className="inline-flex items-center p-0.5 rounded-lg bg-gray-800/80 border border-gray-700 text-xs">
              <button
                type="button"
                onClick={() => setMode("copilot")}
                className={`px-2.5 py-1 rounded-md font-medium transition-all cursor-pointer ${
                  mode === "copilot"
                    ? "bg-sky-600 text-white shadow-xs"
                    : "text-gray-400 hover:text-gray-200"
                }`}
                title="Co-pilot: Kiểm duyệt từng bước trước khi thi hành"
              >
                Co-pilot
              </button>
              <button
                type="button"
                onClick={() => setMode("autopilot")}
                className={`px-2.5 py-1 rounded-md font-medium transition-all cursor-pointer ${
                  mode === "autopilot"
                    ? "bg-emerald-600 text-white shadow-xs"
                    : "text-gray-400 hover:text-gray-200"
                }`}
                title="Auto-pilot (Rảnh tay): Chạy tự động trọn gói DAG"
              >
                Rảnh tay
              </button>
            </div>
          </div>

          {/* Right Actions: Character Counter & Submit Button */}
          <div className="flex items-center gap-3">
            <span
              className={`text-xs font-mono transition-colors ${
                isOverLimit
                  ? "text-rose-400 font-semibold"
                  : charCount > 1800
                  ? "text-amber-400"
                  : "text-gray-500"
              }`}
            >
              {charCount} / 2000
            </span>

            <button
              type="button"
              onClick={handleSubmit}
              disabled={!canSubmit}
              className={`inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold transition-all duration-150 cursor-pointer shadow-md ${
                canSubmit
                  ? "bg-sky-500 hover:bg-sky-400 text-white hover:shadow-sky-500/20 active:scale-98"
                  : "bg-gray-800 text-gray-500 cursor-not-allowed shadow-none"
              }`}
              aria-label="Gửi yêu cầu"
            >
              <span>Gửi</span>
              <Send className={`w-4 h-4 ${canSubmit ? "text-white" : "text-gray-500"}`} />
            </button>
          </div>
        </div>
      </div>

      {/* Quick Prompt Suggestions */}
      <div className="mt-3 flex items-center gap-2 overflow-x-auto pb-1 text-xs text-gray-400">
        <span className="shrink-0 flex items-center gap-1 text-gray-500 font-medium">
          <Sparkles className="w-3.5 h-3.5 text-amber-400" />
          Gợi ý nhanh:
        </span>
        {SUGGESTIONS.map((suggestion, idx) => (
          <button
            key={idx}
            type="button"
            onClick={() => {
              setPrompt(suggestion);
              textareaRef.current?.focus();
            }}
            className="shrink-0 px-2.5 py-1 rounded-full bg-gray-800/60 hover:bg-gray-800 text-gray-300 hover:text-white border border-gray-700/60 hover:border-gray-600 transition-colors cursor-pointer"
          >
            {suggestion}
          </button>
        ))}
      </div>
    </div>
  );
}
