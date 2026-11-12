"use client";

import React, { useState, useEffect, useMemo } from "react";
import {
  Film,
  AlertTriangle,
  Clock,
  Sparkles,
  Edit2,
  Trash2,
  Check,
  X,
  Layers,
  ChevronRight,
  PlayCircle,
} from "lucide-react";
import { defaultApiClient } from "@/lib/apiClient";
import type { StoryboardData, StoryboardSceneData } from "@/lib/types";

export interface StoryboardViewerProps {
  storyboard?: {
    styleName?: string;
    style_name?: string;
    warnings?: string[];
    pacing_warnings?: string[];
    totalDuration?: number;
    total_duration?: number;
    scenes?: Array<{
      sceneId?: string;
      scene_id?: string;
      id?: string;
      durationSec?: number;
      duration?: number;
      overlayText?: string;
      overlay_text?: string;
      effect?: string;
      visualNotes?: string;
      visual_notes?: string;
      startSec?: number;
      endSec?: number;
      start?: number;
      end?: number;
    }>;
  };
  artifactId?: string;
  onApproveRender?: (storyboard: any) => void | Promise<void>;
  onUpdateStoryboard?: (storyboard: any) => void;
  className?: string;
}

const COMMON_EFFECTS = [
  { id: "none", label: "Không hiệu ứng (None)" },
  { id: "zoom", label: "Phóng to (Zoom In)" },
  { id: "major_zoom", label: "Zoom mạnh (Major Zoom)" },
  { id: "major_split", label: "Chia màn hình (Major Split)" },
  { id: "shake", label: "Rung giật (Shake)" },
  { id: "glitch", label: "Nhiễu sóng (Glitch)" },
  { id: "fade", label: "Mờ dần (Fade)" },
];

function normalizeRawScene(s: any, idx: number): StoryboardSceneData {
  const sid = String(s.sceneId || s.scene_id || s.id || `s${idx + 1}`);
  const dur = Number(s.durationSec ?? s.duration ?? (s.end && s.start ? s.end - s.start : 3.0));
  return {
    sceneId: sid,
    scene_id: sid,
    durationSec: dur,
    duration: dur,
    overlayText: String(s.overlayText ?? s.overlay_text ?? s.text ?? ""),
    overlay_text: String(s.overlay_text ?? s.overlayText ?? s.text ?? ""),
    effect: String(s.effect || "none"),
    visualNotes: s.visualNotes ?? s.visual_notes ?? "",
    visual_notes: s.visual_notes ?? s.visualNotes ?? "",
    startSec: s.startSec ?? s.start,
    endSec: s.endSec ?? s.end,
    start: s.start ?? s.startSec,
    end: s.end ?? s.endSec,
  };
}

export function StoryboardViewer({
  storyboard: initialStoryboard,
  artifactId,
  onApproveRender,
  onUpdateStoryboard,
  className = "",
}: StoryboardViewerProps) {
  const [styleName, setStyleName] = useState<string>(
    initialStoryboard?.styleName || initialStoryboard?.style_name || "Rainmaker Style"
  );
  const [scenes, setScenes] = useState<StoryboardSceneData[]>(() => {
    if (initialStoryboard?.scenes && Array.isArray(initialStoryboard.scenes)) {
      return initialStoryboard.scenes.map(normalizeRawScene);
    }
    return [];
  });
  const [warnings, setWarnings] = useState<string[]>(
    initialStoryboard?.warnings || initialStoryboard?.pacing_warnings || []
  );
  const [isLoading, setIsLoading] = useState(false);
  const [isApproving, setIsApproving] = useState(false);

  // Editing state for overlay text
  const [editingSceneId, setEditingSceneId] = useState<string | null>(null);
  const [tempOverlayText, setTempOverlayText] = useState<string>("");

  // Editing state for effect selector
  const [effectPopoverSceneId, setEffectPopoverSceneId] = useState<string | null>(null);

  const prevStoryboardRef = React.useRef(initialStoryboard);

  // Sync when prop changes externally (skip on initial mount)
  useEffect(() => {
    if (prevStoryboardRef.current !== initialStoryboard && initialStoryboard) {
      prevStoryboardRef.current = initialStoryboard;
      if (initialStoryboard.styleName || initialStoryboard.style_name) {
        setStyleName(initialStoryboard.styleName || initialStoryboard.style_name || "Rainmaker Style");
      }
      if (initialStoryboard.scenes && Array.isArray(initialStoryboard.scenes)) {
        setScenes(initialStoryboard.scenes.map(normalizeRawScene));
      }
      if (initialStoryboard.warnings || initialStoryboard.pacing_warnings) {
        setWarnings(initialStoryboard.warnings || initialStoryboard.pacing_warnings || []);
      }
    }
  }, [initialStoryboard]);

  // Fetch from API if artifactId provided and scenes empty
  useEffect(() => {
    if (artifactId && scenes.length === 0) {
      setIsLoading(true);
      defaultApiClient
        .getArtifactStoryboard(artifactId)
        .then((data) => {
          if (data) {
            setStyleName(data.styleName || "Rainmaker Style");
            setScenes(data.scenes || []);
            setWarnings(data.warnings || []);
          }
        })
        .catch((err) => {
          console.error("Failed to fetch storyboard for artifact:", err);
        })
        .finally(() => setIsLoading(false));
    }
  }, [artifactId]);

  // Recalculate total duration live
  const totalDuration = useMemo(() => {
    return scenes.reduce((acc, s) => acc + (s.durationSec || s.duration || 0), 0);
  }, [scenes]);

  const notifyChange = (updatedScenes: StoryboardSceneData[], updatedWarnings = warnings) => {
    const updatedData: StoryboardData = {
      styleName,
      totalDuration,
      warnings: updatedWarnings,
      scenes: updatedScenes,
    };
    onUpdateStoryboard?.(updatedData);
  };

  // Drop Scene Action ("Bỏ cảnh")
  const handleDeleteScene = async (sceneId: string) => {
    const updated = scenes.filter((s) => s.sceneId !== sceneId && s.scene_id !== sceneId);
    setScenes(updated);
    notifyChange(updated);

    if (artifactId) {
      try {
        await defaultApiClient.updateStoryboardScene(artifactId, sceneId, { action: "delete" });
      } catch (err) {
        console.warn("Failed to sync scene deletion with backend:", err);
      }
    }
  };

  // Start editing text ("Sửa chữ")
  const handleStartEditText = (scene: StoryboardSceneData) => {
    setEditingSceneId(scene.sceneId);
    setTempOverlayText(scene.overlayText);
  };

  // Save edited text ("Lưu")
  const handleSaveText = async (sceneId: string) => {
    const updated = scenes.map((s) => {
      if (s.sceneId === sceneId || s.scene_id === sceneId) {
        return {
          ...s,
          overlayText: tempOverlayText,
          overlay_text: tempOverlayText,
        };
      }
      return s;
    });
    setScenes(updated);
    setEditingSceneId(null);
    notifyChange(updated);

    if (artifactId) {
      try {
        await defaultApiClient.updateStoryboardScene(artifactId, sceneId, {
          overlayText: tempOverlayText,
        });
      } catch (err) {
        console.warn("Failed to sync text update with backend:", err);
      }
    }
  };

  // Change Effect ("Đổi hiệu ứng")
  const handleChangeEffect = async (sceneId: string, newEffect: string) => {
    const updated = scenes.map((s) => {
      if (s.sceneId === sceneId || s.scene_id === sceneId) {
        return {
          ...s,
          effect: newEffect,
        };
      }
      return s;
    });
    setScenes(updated);
    setEffectPopoverSceneId(null);
    notifyChange(updated);

    if (artifactId) {
      try {
        await defaultApiClient.updateStoryboardScene(artifactId, sceneId, {
          effect: newEffect,
        });
      } catch (err) {
        console.warn("Failed to sync effect update with backend:", err);
      }
    }
  };

  // Approve & Render ("Duyệt, dựng luôn")
  const handleApprove = () => {
    const payload: StoryboardData = {
      styleName,
      totalDuration,
      warnings,
      scenes,
    };
    const res = onApproveRender?.(payload);
    if (res && typeof (res as any).then === "function") {
      setIsApproving(true);
      (res as Promise<void>)
        .catch((err) => console.error("Error approving render:", err))
        .finally(() => setIsApproving(false));
    }
  };

  return (
    <div
      className={`flex flex-col bg-slate-950 border border-slate-800 rounded-xl overflow-hidden shadow-2xl text-slate-200 ${className}`}
      data-testid="storyboard-viewer"
    >
      {/* Top Header Toolbar */}
      <div className="flex flex-wrap items-center justify-between px-5 py-3.5 bg-slate-900 border-b border-slate-800 gap-3">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-cyan-950/80 border border-cyan-800/60 text-cyan-400">
            <Film className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base font-semibold text-white tracking-tight">
                {styleName}
              </h2>
              <span className="text-[11px] font-mono px-2 py-0.5 rounded-full bg-cyan-900/40 text-cyan-300 border border-cyan-800/50">
                {scenes.length} cảnh
              </span>
            </div>
            <p className="text-xs text-slate-400">
              Kịch bản phân cảnh & nhịp độ video (Interactive Timeline)
            </p>
          </div>
        </div>

        {/* Live Recalculated Total Duration */}
        <div className="flex items-center gap-2 bg-slate-800/80 border border-slate-700/80 px-3 py-1.5 rounded-lg shadow-sm">
          <Clock className="w-4 h-4 text-cyan-400" />
          <span className="text-xs text-slate-400">Tổng thời lượng:</span>
          <span className="text-sm font-bold font-mono text-cyan-300">
            {totalDuration.toFixed(1)} giây
          </span>
        </div>
      </div>

      {/* Pacing Warnings Banner */}
      {warnings && warnings.length > 0 && (
        <div className="flex flex-col gap-1.5 px-5 py-3 bg-amber-950/40 border-b border-amber-800/50 text-amber-200">
          <div className="flex items-center gap-2 text-xs font-semibold text-amber-300">
            <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />
            <span>Cảnh báo nhịp độ (Pacing Warning)</span>
          </div>
          <ul className="list-disc list-inside space-y-0.5 text-xs text-amber-200/90 pl-1">
            {warnings.map((w, idx) => (
              <li key={idx} className="leading-relaxed">
                {w}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Main Timeline Scenes List */}
      <div className="flex-1 overflow-y-auto p-5 space-y-3.5 max-h-[620px]">
        {isLoading ? (
          <div className="py-12 text-center text-xs text-slate-500">
            Đang tải dữ liệu kịch bản phân cảnh...
          </div>
        ) : scenes.length === 0 ? (
          <div className="py-12 text-center text-xs text-slate-500">
            Không có phân cảnh nào trong kịch bản.
          </div>
        ) : (
          scenes.map((scene, idx) => {
            const isEditing = editingSceneId === scene.sceneId;
            const isEffectOpen = effectPopoverSceneId === scene.sceneId;
            const dur = scene.durationSec || scene.duration || 0;

            return (
              <div
                key={scene.sceneId || idx}
                className="group relative flex flex-col sm:flex-row items-start sm:items-center justify-between p-4 bg-slate-900/70 border border-slate-800 hover:border-slate-700/80 rounded-xl transition-all gap-4"
                data-testid={`scene-card-${scene.sceneId}`}
              >
                {/* Left: Scene Order & Timing */}
                <div className="flex items-center gap-3 shrink-0">
                  <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-slate-800 border border-slate-700 text-xs font-mono font-bold text-slate-300">
                    {idx + 1}
                  </div>
                  <div>
                    <span className="text-xs font-medium text-slate-300 block">
                      Cảnh {idx + 1}
                    </span>
                    <span className="text-[11px] font-mono text-cyan-400">
                      {dur.toFixed(1)}s
                      {scene.startSec !== undefined && scene.endSec !== undefined && (
                        <span className="text-slate-500 ml-1">
                          ({scene.startSec.toFixed(1)}s - {scene.endSec.toFixed(1)}s)
                        </span>
                      )}
                    </span>
                  </div>
                </div>

                {/* Middle: Overlay Text & Visual Notes */}
                <div className="flex-1 w-full min-w-0 px-1">
                  {isEditing ? (
                    <div className="flex items-center gap-2">
                      <input
                        type="text"
                        value={tempOverlayText}
                        onChange={(e) => setTempOverlayText(e.target.value)}
                        className="flex-1 bg-slate-800 border border-cyan-500/60 rounded px-2.5 py-1 text-xs text-white focus:outline-none focus:ring-1 focus:ring-cyan-400"
                        placeholder="Nhập chữ hiển thị / phụ đề..."
                        autoFocus
                      />
                      <button
                        type="button"
                        onClick={() => handleSaveText(scene.sceneId)}
                        className="px-2.5 py-1 bg-cyan-600 hover:bg-cyan-500 text-white rounded text-xs font-medium flex items-center gap-1"
                      >
                        <Check className="w-3.5 h-3.5" />
                        <span>Lưu</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => setEditingSceneId(null)}
                        className="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded text-xs"
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  ) : (
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-medium text-slate-100 font-sans">
                          {scene.overlayText || (
                            <span className="italic text-slate-500">
                              (Chưa có chữ hiển thị)
                            </span>
                          )}
                        </span>
                      </div>
                      {scene.visualNotes && (
                        <p className="text-[11px] text-slate-400 mt-0.5 truncate">
                          Ghi chú: {scene.visualNotes}
                        </p>
                      )}
                    </div>
                  )}
                </div>

                {/* Right: Effect Badge & Scene Actions */}
                <div className="flex items-center gap-2 shrink-0 self-end sm:self-center">
                  {/* Effect Selection */}
                  <div className="relative">
                    <button
                      type="button"
                      onClick={() =>
                        setEffectPopoverSceneId(isEffectOpen ? null : scene.sceneId)
                      }
                      aria-label="Đổi hiệu ứng"
                      className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 text-xs font-medium transition-colors"
                    >
                      <Sparkles className="w-3 h-3 text-cyan-400" />
                      <span className="capitalize">{scene.effect || "none"}</span>
                    </button>

                    {isEffectOpen && (
                      <div className="absolute right-0 bottom-full mb-1 w-48 bg-slate-900 border border-slate-700 rounded-lg shadow-2xl py-1 z-30">
                        <div className="px-3 py-1 text-[10px] font-bold text-slate-400 border-b border-slate-800 uppercase tracking-wider">
                          Chọn hiệu ứng
                        </div>
                        {COMMON_EFFECTS.map((eff) => (
                          <button
                            key={eff.id}
                            type="button"
                            onClick={() => handleChangeEffect(scene.sceneId, eff.id)}
                            className={`w-full text-left px-3 py-1.5 text-xs hover:bg-slate-800 transition-colors flex items-center justify-between ${
                              scene.effect === eff.id
                                ? "text-cyan-400 font-bold bg-slate-800/50"
                                : "text-slate-300"
                            }`}
                          >
                            <span>{eff.label}</span>
                            {scene.effect === eff.id && (
                              <Check className="w-3 h-3 text-cyan-400" />
                            )}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Sửa chữ Action Button (always accessible) */}
                  {!isEditing && (
                    <button
                      type="button"
                      onClick={() => handleStartEditText(scene)}
                      className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white text-xs font-medium border border-slate-700"
                    >
                      Sửa chữ
                    </button>
                  )}

                  {/* Bỏ cảnh Action Button */}
                  <button
                    type="button"
                    onClick={() => handleDeleteScene(scene.sceneId)}
                    aria-label="Bỏ cảnh"
                    className="flex items-center gap-1 px-2.5 py-1 rounded bg-rose-950/60 hover:bg-rose-900/80 border border-rose-800/60 text-rose-300 hover:text-rose-100 text-xs font-medium transition-colors"
                  >
                    <Trash2 className="w-3 h-3" />
                    <span>Bỏ cảnh</span>
                  </button>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Bottom Actions Footer */}
      <div className="flex flex-wrap items-center justify-between px-5 py-3.5 bg-slate-900 border-t border-slate-800 gap-3">
        <div className="text-xs text-slate-400">
          <span>
            {scenes.length} phân cảnh • Tổng thời lượng:{" "}
            <strong className="text-cyan-300 font-mono">
              {totalDuration.toFixed(1)}s
            </strong>
          </span>
        </div>

        {/* Duyệt, dựng luôn Button */}
        <button
          type="button"
          onClick={handleApprove}
          disabled={isApproving || scenes.length === 0}
          className="flex items-center gap-2 px-5 py-2 rounded-lg bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white font-medium text-xs shadow-lg shadow-cyan-950/50 disabled:opacity-50 disabled:cursor-not-allowed transition-all transform active:scale-95"
        >
          <PlayCircle className="w-4 h-4" />
          <span>{isApproving ? "Đang gửi lệnh dựng..." : "Duyệt, dựng luôn"}</span>
        </button>
      </div>
    </div>
  );
}
