"use client";

import React, { useEffect, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Clock,
  Edit3,
  RotateCcw,
  ShieldAlert,
  XCircle,
} from "lucide-react";
import type {
  ReviewDecidePayload,
  ReviewDecision,
  ReviewGate,
} from "@/lib/types";

export interface ReviewGateBannerProps {
  review: ReviewGate;
  onDecide: (
    decision: ReviewDecision,
    payload?: ReviewDecidePayload
  ) => void | Promise<void>;
  isSubmitting?: boolean;
  className?: string;
}

const MIN_REJECT_FEEDBACK_LENGTH = 5;

function formatEditValue(review: ReviewGate): string {
  const rawEdited = review.editedContent ?? review.edited_content;
  if (typeof rawEdited === "string") {
    return rawEdited;
  }
  if (rawEdited != null) {
    return JSON.stringify(rawEdited, null, 2);
  }
  if (typeof review.payload === "string") {
    return review.payload;
  }
  if (review.payload != null) {
    return JSON.stringify(review.payload, null, 2);
  }
  return review.summary ?? "";
}

function formatRemainingTime(expiresAt?: string | null): {
  expired: boolean;
  label: string | null;
} {
  if (!expiresAt) {
    return { expired: false, label: null };
  }
  const expiresMs = Date.parse(expiresAt);
  if (Number.isNaN(expiresMs)) {
    return { expired: false, label: null };
  }
  const diffMs = expiresMs - Date.now();
  if (diffMs <= 0) {
    return { expired: true, label: "Đã hết hạn" };
  }
  const totalMinutes = Math.ceil(diffMs / 60000);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours > 0) {
    return { expired: false, label: `Còn ${hours}g ${minutes}p` };
  }
  return { expired: false, label: `Còn ${minutes} phút` };
}

export function ReviewGateBanner({
  review,
  onDecide,
  isSubmitting = false,
  className = "",
}: ReviewGateBannerProps) {
  const gateType = review.gateType || review.gate_type || "hil";
  const status = (review.status || "pending").toLowerCase();
  const expiresAt = review.expiresAt ?? review.expires_at ?? null;

  const [activeMode, setActiveMode] = useState<"idle" | "edit" | "reject">("idle");
  const [feedbackText, setFeedbackText] = useState("");
  const [editedContent, setEditedContent] = useState(() => formatEditValue(review));
  const [localSubmitting, setLocalSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    setActiveMode("idle");
    setFeedbackText("");
    setEditedContent(formatEditValue(review));
    setErrorMessage(null);
    setLocalSubmitting(false);
  }, [
    review.id,
    review.summary,
    review.payload,
    review.editedContent,
    review.edited_content,
  ]);

  const expiryInfo = formatRemainingTime(expiresAt);
  const isExpired = status === "expired" || (status === "pending" && expiryInfo.expired);
  const isDecided =
    status === "approved" || status === "edited" || status === "rejected";
  const isDisabled = isSubmitting || localSubmitting || isExpired || isDecided;

  const trimmedFeedback = feedbackText.trim();
  const canConfirmReject =
    !isDisabled && trimmedFeedback.length >= MIN_REJECT_FEEDBACK_LENGTH;
  const canConfirmEdit = !isDisabled && editedContent.trim().length > 0;

  const handleApprove = async () => {
    if (isDisabled) return;
    setLocalSubmitting(true);
    setErrorMessage(null);
    try {
      await onDecide("approve");
      setActiveMode("idle");
    } catch (err) {
      setErrorMessage(
        err instanceof Error
          ? err.message
          : "Không thể phê duyệt review gate. Vui lòng thử lại."
      );
    } finally {
      setLocalSubmitting(false);
    }
  };

  const handleConfirmEdit = async () => {
    if (!canConfirmEdit) return;
    setLocalSubmitting(true);
    setErrorMessage(null);
    try {
      await onDecide("edit", {
        editedContent,
        ...(trimmedFeedback ? { feedbackText: trimmedFeedback } : {}),
      });
      setActiveMode("idle");
    } catch (err) {
      setErrorMessage(
        err instanceof Error
          ? err.message
          : "Không thể lưu chỉnh sửa. Vui lòng thử lại."
      );
    } finally {
      setLocalSubmitting(false);
    }
  };

  const handleConfirmReject = async () => {
    if (!canConfirmReject) return;
    setLocalSubmitting(true);
    setErrorMessage(null);
    try {
      await onDecide("reject", {
        feedbackText: trimmedFeedback,
      });
      setActiveMode("idle");
      setFeedbackText("");
    } catch (err) {
      setErrorMessage(
        err instanceof Error
          ? err.message
          : "Không thể gửi yêu cầu đặt lại. Vui lòng thử lại."
      );
    } finally {
      setLocalSubmitting(false);
    }
  };

  return (
    <section
      data-testid="review-gate-banner"
      aria-label="Cổng kiểm duyệt Human-in-the-Loop"
      className={`w-full rounded-2xl border p-4 transition-colors ${
        isExpired
          ? "bg-gray-900/90 border-rose-800/60"
          : isDecided
          ? "bg-gray-900/90 border-gray-800"
          : "bg-gray-900 border-amber-500/40 shadow-lg shadow-amber-950/10"
      } ${className}`}
    >
      {/* Header row */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3 min-w-0">
          <div
            className={`mt-0.5 p-2 rounded-xl border shrink-0 ${
              isExpired
                ? "bg-rose-950/60 border-rose-800/50 text-rose-400"
                : status === "approved" || status === "edited"
                ? "bg-emerald-950/60 border-emerald-800/50 text-emerald-400"
                : status === "rejected"
                ? "bg-rose-950/60 border-rose-800/50 text-rose-400"
                : "bg-amber-950/60 border-amber-700/50 text-amber-400"
            }`}
          >
            {status === "approved" || status === "edited" ? (
              <CheckCircle2 className="w-4 h-4" />
            ) : status === "rejected" || isExpired ? (
              <XCircle className="w-4 h-4" />
            ) : (
              <ShieldAlert className="w-4 h-4" />
            )}
          </div>

          <div className="space-y-1 min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold uppercase tracking-wider bg-amber-500/15 text-amber-300 border border-amber-500/30">
                {gateType}
              </span>

              {isExpired ? (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-rose-950/70 text-rose-300 border border-rose-800/60">
                  <Clock className="w-3 h-3" />
                  Đã hết hạn (24h)
                </span>
              ) : status === "approved" ? (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-emerald-950/70 text-emerald-300 border border-emerald-800/60">
                  Đã phê duyệt
                </span>
              ) : status === "edited" ? (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-sky-950/70 text-sky-300 border border-sky-800/60">
                  Đã chỉnh sửa & phê duyệt
                </span>
              ) : status === "rejected" ? (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-rose-950/70 text-rose-300 border border-rose-800/60">
                  Đã từ chối / Đặt lại
                </span>
              ) : (
                expiryInfo.label && (
                  <span className="inline-flex items-center gap-1 text-[11px] text-gray-400">
                    <Clock className="w-3 h-3 text-amber-400" />
                    {expiryInfo.label}
                  </span>
                )
              )}
            </div>

            <p className="text-sm font-medium text-gray-100 leading-relaxed">
              {review.summary || "Yêu cầu kiểm duyệt trước khi tiếp tục thực thi."}
            </p>

            {(review.feedbackText || review.feedback_text) && isDecided && (
              <p className="text-xs text-gray-400 bg-gray-950/60 border border-gray-800 rounded-lg px-2.5 py-1.5">
                Phản hồi: {review.feedbackText || review.feedback_text}
              </p>
            )}
          </div>
        </div>

        {/* Action buttons for pending/expired gates */}
        {!isDecided && (
          <div className="flex flex-wrap items-center gap-2 shrink-0">
            <button
              type="button"
              disabled={isDisabled}
              onClick={handleApprove}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white transition-colors disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
            >
              <CheckCircle2 className="w-3.5 h-3.5" />
              <span>Phê duyệt</span>
            </button>

            <button
              type="button"
              disabled={isDisabled}
              onClick={() => {
                setErrorMessage(null);
                setActiveMode((prev) => (prev === "edit" ? "idle" : "edit"));
              }}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium border transition-colors disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer ${
                activeMode === "edit"
                  ? "bg-sky-900/60 border-sky-500/60 text-sky-200"
                  : "bg-gray-800 hover:bg-gray-700 border-gray-700 text-gray-200"
              }`}
            >
              <Edit3 className="w-3.5 h-3.5 text-sky-400" />
              <span>Chỉnh sửa</span>
            </button>

            <button
              type="button"
              disabled={isDisabled}
              onClick={() => {
                setErrorMessage(null);
                setActiveMode((prev) => (prev === "reject" ? "idle" : "reject"));
              }}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium border transition-colors disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer ${
                activeMode === "reject"
                  ? "bg-rose-950/80 border-rose-500/60 text-rose-200"
                  : "bg-gray-800 hover:bg-rose-950/50 border-gray-700 hover:border-rose-700/60 text-rose-300"
              }`}
            >
              <RotateCcw className="w-3.5 h-3.5" />
              <span>Đặt lại / Từ chối</span>
            </button>
          </div>
        )}
      </div>

      {/* Inline error feedback */}
      {errorMessage && (
        <div
          role="alert"
          className="mt-3 px-3 py-2 rounded-xl bg-rose-950/60 border border-rose-800/70 text-xs text-rose-200 flex items-center gap-2"
        >
          <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
          <span>{errorMessage}</span>
        </div>
      )}

      {/* Inline Edit Panel */}
      {activeMode === "edit" && !isDecided && (
        <div className="mt-3 pt-3 border-t border-gray-800 space-y-2.5">
          <label className="block text-xs font-medium text-sky-300">
            Chỉnh sửa nội dung trước khi phê duyệt
          </label>
          <textarea
            value={editedContent}
            onChange={(e) => setEditedContent(e.target.value)}
            rows={4}
            placeholder="Nhập nội dung đã chỉnh sửa..."
            className="w-full rounded-xl bg-gray-950 border border-gray-700 focus:border-sky-500 focus:outline-none p-2.5 text-xs text-gray-100 placeholder-gray-500 leading-relaxed"
          />
          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              disabled={localSubmitting || isSubmitting}
              onClick={() => setActiveMode("idle")}
              className="px-3 py-1.5 rounded-lg text-xs text-gray-400 hover:text-gray-200 hover:bg-gray-800 transition-colors cursor-pointer disabled:opacity-40"
            >
              Hủy
            </button>
            <button
              type="button"
              disabled={!canConfirmEdit}
              onClick={handleConfirmEdit}
              className="px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-sky-600 hover:bg-sky-500 text-white transition-colors disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
            >
              Lưu & Phê duyệt
            </button>
          </div>
        </div>
      )}

      {/* Inline Reject Feedback Panel */}
      {activeMode === "reject" && !isDecided && (
        <div className="mt-3 pt-3 border-t border-gray-800 space-y-2.5">
          <div className="flex items-center justify-between gap-2">
            <label className="text-xs font-medium text-rose-300">
              Lý do từ chối / yêu cầu làm lại (tối thiểu 5 ký tự)
            </label>
            <span
              className={`text-[11px] font-mono ${
                trimmedFeedback.length >= MIN_REJECT_FEEDBACK_LENGTH
                  ? "text-emerald-400"
                  : "text-amber-400"
              }`}
            >
              {trimmedFeedback.length}/{MIN_REJECT_FEEDBACK_LENGTH}+ ký tự
            </span>
          </div>
          <textarea
            value={feedbackText}
            onChange={(e) => setFeedbackText(e.target.value)}
            rows={3}
            placeholder="Mô tả chi tiết điểm cần sửa để agent chạy lại lượt mới..."
            className="w-full rounded-xl bg-gray-950 border border-gray-700 focus:border-rose-500 focus:outline-none p-2.5 text-xs text-gray-100 placeholder-gray-500 leading-relaxed"
          />
          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              disabled={localSubmitting || isSubmitting}
              onClick={() => {
                setActiveMode("idle");
                setFeedbackText("");
              }}
              className="px-3 py-1.5 rounded-lg text-xs text-gray-400 hover:text-gray-200 hover:bg-gray-800 transition-colors cursor-pointer disabled:opacity-40"
            >
              Hủy
            </button>
            <button
              type="button"
              disabled={!canConfirmReject}
              onClick={handleConfirmReject}
              className="px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-rose-600 hover:bg-rose-500 text-white transition-colors disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
            >
              Xác nhận từ chối
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
