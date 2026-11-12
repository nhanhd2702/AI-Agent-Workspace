"use client";

import React, { useRef, useState, useEffect, useCallback } from "react";
import {
  Play,
  Pause,
  Volume2,
  VolumeX,
  Maximize2,
  Minimize2,
  RotateCcw,
  Film,
  Music,
} from "lucide-react";

export interface MediaPlayerProps {
  src: string;
  poster?: string;
  title?: string;
  type?: "video" | "audio";
  className?: string;
  onTimeUpdate?: (currentTime: number) => void;
  onEnded?: () => void;
}

const SPEED_OPTIONS = [0.5, 1, 1.25, 1.5, 2];

export function formatTime(seconds: number): string {
  if (isNaN(seconds) || seconds < 0) return "0:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s < 10 ? "0" : ""}${s}`;
}

export function MediaPlayer({
  src,
  poster,
  title,
  type = "video",
  className = "",
  onTimeUpdate,
  onEnded,
}: MediaPlayerProps) {
  const mediaRef = useRef<HTMLVideoElement | HTMLAudioElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);

  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [volume, setVolume] = useState(1);
  const [isMuted, setIsMuted] = useState(false);
  const [playbackRate, setPlaybackRate] = useState(1);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [showSpeedMenu, setShowSpeedMenu] = useState(false);

  // Sync state with HTML media events
  const handleTimeUpdate = useCallback(() => {
    if (mediaRef.current) {
      const cur = mediaRef.current.currentTime;
      setCurrentTime(cur);
      onTimeUpdate?.(cur);
    }
  }, [onTimeUpdate]);

  const handleLoadedMetadata = () => {
    if (mediaRef.current) {
      setDuration(mediaRef.current.duration || 0);
    }
  };

  const handleEnded = () => {
    setIsPlaying(false);
    onEnded?.();
  };

  const togglePlay = () => {
    if (!mediaRef.current) return;
    if (isPlaying) {
      mediaRef.current.pause();
      setIsPlaying(false);
    } else {
      mediaRef.current.play().then(
        () => setIsPlaying(true),
        (err) => console.warn("Playback error:", err)
      );
    }
  };

  const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = parseFloat(e.target.value);
    if (mediaRef.current) {
      mediaRef.current.currentTime = val;
      setCurrentTime(val);
    }
  };

  const handleVolumeChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = parseFloat(e.target.value);
    setVolume(val);
    if (mediaRef.current) {
      mediaRef.current.volume = val;
      if (val === 0) {
        setIsMuted(true);
        mediaRef.current.muted = true;
      } else if (isMuted) {
        setIsMuted(false);
        mediaRef.current.muted = false;
      }
    }
  };

  const toggleMute = () => {
    if (!mediaRef.current) return;
    const nextMuted = !isMuted;
    setIsMuted(nextMuted);
    mediaRef.current.muted = nextMuted;
    if (!nextMuted && volume === 0) {
      setVolume(0.5);
      mediaRef.current.volume = 0.5;
    }
  };

  const handleSpeedSelect = (rate: number) => {
    setPlaybackRate(rate);
    if (mediaRef.current) {
      mediaRef.current.playbackRate = rate;
    }
    setShowSpeedMenu(false);
  };

  const toggleFullscreen = () => {
    if (!containerRef.current) return;
    if (!document.fullscreenElement) {
      containerRef.current.requestFullscreen?.().then(() => setIsFullscreen(true));
    } else {
      document.exitFullscreen?.().then(() => setIsFullscreen(false));
    }
  };

  useEffect(() => {
    const onFsChange = () => {
      setIsFullscreen(Boolean(document.fullscreenElement));
    };
    document.addEventListener("fullscreenchange", onFsChange);
    return () => {
      document.removeEventListener("fullscreenchange", onFsChange);
    };
  }, []);

  return (
    <div
      ref={containerRef}
      className={`flex flex-col bg-slate-950 border border-slate-800 rounded-xl overflow-hidden shadow-xl text-slate-200 select-none ${className}`}
      data-testid="media-player"
    >
      {/* Title Header if provided */}
      {title && (
        <div className="flex items-center gap-2 px-4 py-2.5 bg-slate-900 border-b border-slate-800 text-xs font-medium text-slate-300">
          {type === "video" ? (
            <Film className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
          ) : (
            <Music className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
          )}
          <span className="truncate">{title}</span>
        </div>
      )}

      {/* Main Media Viewport */}
      <div className="relative flex items-center justify-center bg-black/60 min-h-[200px] max-h-[500px] overflow-hidden group">
        {type === "video" ? (
          <video
            ref={mediaRef as React.RefObject<HTMLVideoElement>}
            src={src}
            poster={poster}
            className="w-full h-full max-h-[480px] object-contain"
            onTimeUpdate={handleTimeUpdate}
            onLoadedMetadata={handleLoadedMetadata}
            onEnded={handleEnded}
            onClick={togglePlay}
            playsInline
          />
        ) : (
          <div className="flex flex-col items-center justify-center p-8 gap-3">
            <div className="w-16 h-16 rounded-full bg-cyan-950/80 border border-cyan-800/50 flex items-center justify-center text-cyan-400">
              <Music className="w-8 h-8" />
            </div>
            <audio
              ref={mediaRef as React.RefObject<HTMLAudioElement>}
              src={src}
              onTimeUpdate={handleTimeUpdate}
              onLoadedMetadata={handleLoadedMetadata}
              onEnded={handleEnded}
            />
          </div>
        )}

        {/* Center overlay big play button when paused */}
        {!isPlaying && (
          <button
            type="button"
            onClick={togglePlay}
            aria-label="Phát"
            className="absolute inset-0 m-auto w-14 h-14 rounded-full bg-cyan-600/90 hover:bg-cyan-500 text-white flex items-center justify-center shadow-lg transition-transform hover:scale-110 focus:outline-none"
          >
            <Play className="w-6 h-6 fill-white ml-0.5" />
          </button>
        )}
      </div>

      {/* Playback Controls Bar */}
      <div className="flex flex-col bg-slate-900/95 border-t border-slate-800 px-4 py-2.5 gap-2 text-xs">
        {/* Seek Progress Bar */}
        <div className="flex items-center gap-2 w-full">
          <span className="text-[11px] font-mono text-slate-400 w-10 text-right">
            {formatTime(currentTime)}
          </span>
          <input
            type="range"
            min={0}
            max={duration || 100}
            step={0.1}
            value={currentTime}
            onChange={handleSeek}
            aria-label="Tiến trình phát"
            className="w-full h-1.5 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-cyan-400 hover:h-2 transition-all"
          />
          <span className="text-[11px] font-mono text-slate-400 w-10">
            {formatTime(duration)}
          </span>
        </div>

        {/* Bottom Actions Row */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {/* Play / Pause Toggle */}
            <button
              type="button"
              onClick={togglePlay}
              aria-label={isPlaying ? "Tạm dừng" : "Phát"}
              className="p-1.5 rounded-lg text-slate-200 hover:text-white hover:bg-slate-800 transition-colors"
            >
              {isPlaying ? (
                <Pause className="w-4 h-4" />
              ) : (
                <Play className="w-4 h-4 fill-current ml-0.5" />
              )}
            </button>

            {/* Restart Button */}
            <button
              type="button"
              onClick={() => {
                if (mediaRef.current) {
                  mediaRef.current.currentTime = 0;
                  setCurrentTime(0);
                }
              }}
              aria-label="Phát lại từ đầu"
              className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
            >
              <RotateCcw className="w-3.5 h-3.5" />
            </button>

            {/* Volume / Mute Controls */}
            <div className="flex items-center gap-1.5 group/vol">
              <button
                type="button"
                onClick={toggleMute}
                aria-label={isMuted || volume === 0 ? "Bật âm thanh" : "Tắt tiếng"}
                className="p-1.5 rounded-lg text-slate-300 hover:text-white hover:bg-slate-800 transition-colors"
              >
                {isMuted || volume === 0 ? (
                  <VolumeX className="w-4 h-4 text-rose-400" />
                ) : (
                  <Volume2 className="w-4 h-4" />
                )}
              </button>
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={isMuted ? 0 : volume}
                onChange={handleVolumeChange}
                aria-label="Âm lượng"
                className="w-16 h-1 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-cyan-400"
              />
            </div>

            {/* Formatted time status */}
            <span className="hidden sm:inline-block text-[11px] font-mono text-slate-400">
              {formatTime(currentTime)} / {formatTime(duration)}
            </span>
          </div>

          <div className="flex items-center gap-2">
            {/* Speed Selector */}
            <div className="relative">
              <button
                type="button"
                onClick={() => setShowSpeedMenu(!showSpeedMenu)}
                aria-label={`Tốc độ phát (${playbackRate}x)`}
                className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-[11px] font-medium transition-colors"
              >
                {playbackRate}x
              </button>
              {showSpeedMenu && (
                <div className="absolute bottom-full right-0 mb-1 py-1 w-20 bg-slate-800 border border-slate-700 rounded-lg shadow-xl z-20">
                  {SPEED_OPTIONS.map((rate) => (
                    <button
                      key={rate}
                      type="button"
                      onClick={() => handleSpeedSelect(rate)}
                      className={`w-full text-left px-3 py-1 text-xs hover:bg-slate-700 ${
                        rate === playbackRate ? "text-cyan-400 font-bold" : "text-slate-300"
                      }`}
                    >
                      {rate}x
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Fullscreen Button (for video) */}
            {type === "video" && (
              <button
                type="button"
                onClick={toggleFullscreen}
                aria-label={isFullscreen ? "Thoát toàn màn hình" : "Toàn màn hình"}
                className="p-1.5 rounded-lg text-slate-300 hover:text-white hover:bg-slate-800 transition-colors"
              >
                {isFullscreen ? (
                  <Minimize2 className="w-4 h-4" />
                ) : (
                  <Maximize2 className="w-4 h-4" />
                )}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
