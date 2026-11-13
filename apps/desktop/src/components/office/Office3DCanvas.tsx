"use client";

import React, { useEffect, useRef, useState, useCallback } from "react";
import {
  Maximize2,
  Minimize2,
  RotateCcw,
  ZoomIn,
  ZoomOut,
  Users,
  PenTool,
  GitMerge,
  Compass,
  ShoppingCart,
  Sparkles,
  Info,
  CheckCircle2,
  Terminal,
} from "lucide-react";

export interface AgentVisual {
  id: string;
  name: string;
  displayName: string;
  role: string;
  department: string;
  color: string;
  status: "idle" | "working" | "review";
  thought: string;
  gridX: number;
  gridY: number;
}

const DEFAULT_AGENTS: AgentVisual[] = [
  // Đội Content (Pod 1 - top-left)
  {
    id: "content-writer",
    name: "ContentWriter",
    displayName: "Trần Viết Văn",
    role: "Biên tập kịch bản & nội dung",
    department: "Đội Content",
    color: "#38bdf8", // Sky
    status: "working",
    thought: "Đang viết hook kịch bản TikTok 60s...",
    gridX: -3.5,
    gridY: -3,
  },
  {
    id: "seo-expert",
    name: "SEOExpert",
    displayName: "Lê Tối Ưu",
    role: "Tối ưu hóa SEO & Search",
    department: "Đội Content",
    color: "#06b6d4", // Cyan
    status: "idle",
    thought: "Sẵn sàng phân tích từ khóa",
    gridX: -2.5,
    gridY: -4.5,
  },
  {
    id: "copywriter",
    name: "Copywriter",
    displayName: "Nguyễn Chốt Đơn",
    role: "Viết lời chào hàng & Headline",
    department: "Đội Content",
    color: "#60a5fa", // Blue
    status: "idle",
    thought: "Headline chuyển đổi cao 85%",
    gridX: -4.5,
    gridY: -4.5,
  },

  // Đội Funnels (Pod 2 - top-right)
  {
    id: "funnel-builder",
    name: "FunnelBuilder",
    displayName: "Hoàng Phễu Bán",
    role: "Thiết kế luồng phễu & Conversion",
    department: "Đội Funnels",
    color: "#a855f7", // Purple
    status: "working",
    thought: "Tối ưu Landing page Solopreneur...",
    gridX: 3.5,
    gridY: -3,
  },
  {
    id: "sales-closer",
    name: "SalesCloser",
    displayName: "Vũ Chốt Sale",
    role: "Kịch bản bán hàng & xử lý từ chối",
    department: "Đội Funnels",
    color: "#c084fc", // Violet
    status: "idle",
    thought: "Sẵn sàng kịch bản chốt đơn",
    gridX: 2.5,
    gridY: -4.5,
  },
  {
    id: "ad-specialist",
    name: "AdSpecialist",
    displayName: "Đặng Quảng Cáo",
    role: "Targeting & tối ưu Ads ROI",
    department: "Đội Funnels",
    color: "#818cf8", // Indigo
    status: "idle",
    thought: "ROAS mục tiêu 4.5x",
    gridX: 4.5,
    gridY: -4.5,
  },

  // Nghiên cứu & R&D (Pod 3 - bottom-left)
  {
    id: "deep-researcher",
    name: "DeepResearcher",
    displayName: "Phạm Nghiên Cứu",
    role: "Thu thập & phân tích dữ liệu sâu",
    department: "Nghiên cứu & Phát triển",
    color: "#34d399", // Emerald
    status: "working",
    thought: "Đang cào dữ liệu xu hướng AI 2026...",
    gridX: -3.5,
    gridY: 3,
  },
  {
    id: "trend-watcher",
    name: "TrendWatcher",
    displayName: "Bùi Bắt Trend",
    role: "Săn lùng xu hướng TikTok & YouTube",
    department: "Nghiên cứu & Phát triển",
    color: "#10b981", // Green
    status: "idle",
    thought: "Radar phát hiện 3 hashtag viral",
    gridX: -2.5,
    gridY: 4.5,
  },
  {
    id: "data-analyst",
    name: "DataAnalyst",
    displayName: "Đỗ Thống Kê",
    role: "Phân tích số liệu & Báo cáo",
    department: "Nghiên cứu & Phát triển",
    color: "#2dd4bf", // Teal
    status: "idle",
    thought: "Báo cáo phân rã hoàn tất 100%",
    gridX: -4.5,
    gridY: 4.5,
  },

  // Thương mại điện tử (Pod 4 - bottom-right)
  {
    id: "customer-success",
    name: "CustomerSuccess",
    displayName: "Mai Chăm Khách",
    role: "Chăm sóc khách hàng & CSKH tự động",
    department: "Thương mại điện tử",
    color: "#f59e0b", // Amber
    status: "working",
    thought: "Đang phản hồi tin nhắn Telegram...",
    gridX: 3.5,
    gridY: 3,
  },
  {
    id: "qa-validator",
    name: "QAValidator",
    displayName: "Đinh Kiểm Định",
    role: "Kiểm tra chất lượng & Tiêu chuẩn",
    department: "Thương mại điện tử",
    color: "#fbbf24", // Yellow
    status: "idle",
    thought: "Kiểm duyệt link & chính tả OK",
    gridX: 2.5,
    gridY: 4.5,
  },
  {
    id: "master-commander",
    name: "MasterCommander",
    displayName: "Tổng Chỉ Huy",
    role: "Điều phối trung tâm đa tác tử",
    department: "Chỉ Huy Trung Tâm",
    color: "#ec4899", // Pink
    status: "working",
    thought: "Đang điều phối LangGraph DAG...",
    gridX: 0,
    gridY: 0,
  },
];

export interface Office3DCanvasProps {
  onSelectAgent?: (agent: AgentVisual) => void;
  className?: string;
}

export function Office3DCanvas({ onSelectAgent, className = "" }: Office3DCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);

  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });
  const [selectedAgent, setSelectedAgent] = useState<AgentVisual | null>(null);
  const [hoveredAgent, setHoveredAgent] = useState<AgentVisual | null>(null);
  const [activeFilter, setActiveFilter] = useState<string>("all");

  const agents = DEFAULT_AGENTS;

  // Isometric projection constants
  const ISO_ANGLE = Math.PI / 6; // 30 degrees
  const TILE_WIDTH = 64;
  const TILE_HEIGHT = 32;

  // Convert grid (x, y) to screen coordinates
  const toScreen = useCallback(
    (gridX: number, gridY: number, originX: number, originY: number, currentZoom: number, currentPan: { x: number; y: number }) => {
      const screenX = originX + (gridX - gridY) * (TILE_WIDTH / 2) * currentZoom + currentPan.x;
      const screenY = originY + (gridX + gridY) * (TILE_HEIGHT / 2) * currentZoom + currentPan.y;
      return { x: screenX, y: screenY };
    },
    [TILE_WIDTH, TILE_HEIGHT]
  );

  // Render loop
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let animationFrameId: number;
    let tick = 0;

    const resizeCanvas = () => {
      const rect = containerRef.current?.getBoundingClientRect();
      if (!rect) return;
      const dpr = window.devicePixelRatio || 1;
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      canvas.style.width = `${rect.width}px`;
      canvas.style.height = `${rect.height}px`;
      ctx.scale(dpr, dpr);
    };

    resizeCanvas();
    window.addEventListener("resize", resizeCanvas);

    const render = () => {
      tick += 1;
      const rect = containerRef.current?.getBoundingClientRect();
      const width = rect ? rect.width : canvas.width;
      const height = rect ? rect.height : canvas.height;

      const originX = width / 2;
      const originY = height / 2 - 20;

      // Clear with dark ambient gradient
      const bgGrad = ctx.createRadialGradient(originX, originY, 50, originX, originY, Math.max(width, height));
      bgGrad.addColorStop(0, "#0a0f1d");
      bgGrad.addColorStop(1, "#030712");
      ctx.fillStyle = bgGrad;
      ctx.fillRect(0, 0, width, height);

      // Draw isometric grid lines
      ctx.save();
      ctx.lineWidth = 1;

      const GRID_RADIUS = 7;
      for (let i = -GRID_RADIUS; i <= GRID_RADIUS; i++) {
        for (let j = -GRID_RADIUS; j <= GRID_RADIUS; j++) {
          const pt = toScreen(i, j, originX, originY, zoom, pan);

          // Subtle floor tile outline
          ctx.beginPath();
          ctx.moveTo(pt.x, pt.y - (TILE_HEIGHT / 2) * zoom);
          ctx.lineTo(pt.x + (TILE_WIDTH / 2) * zoom, pt.y);
          ctx.lineTo(pt.x, pt.y + (TILE_HEIGHT / 2) * zoom);
          ctx.lineTo(pt.x - (TILE_WIDTH / 2) * zoom, pt.y);
          ctx.closePath();

          // Department colored area highlight
          let tileColor = "rgba(255, 255, 255, 0.015)";
          if (i < 0 && j < 0) tileColor = "rgba(56, 189, 248, 0.03)"; // Content zone
          else if (i > 0 && j < 0) tileColor = "rgba(168, 85, 247, 0.03)"; // Funnel zone
          else if (i < 0 && j > 0) tileColor = "rgba(52, 211, 153, 0.03)"; // R&D zone
          else if (i > 0 && j > 0) tileColor = "rgba(245, 158, 11, 0.03)"; // E-com zone
          else if (i === 0 && j === 0) tileColor = "rgba(236, 72, 153, 0.06)"; // Master zone

          ctx.fillStyle = tileColor;
          ctx.fill();
          ctx.strokeStyle = "rgba(255, 255, 255, 0.04)";
          ctx.stroke();
        }
      }

      // Draw 4 Department Zone Boundary Rings
      const drawZone = (gx: number, gy: number, label: string, color: string) => {
        const center = toScreen(gx, gy, originX, originY, zoom, pan);
        ctx.save();
        ctx.beginPath();
        ctx.ellipse(center.x, center.y, 130 * zoom, 65 * zoom, 0, 0, Math.PI * 2);
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.5;
        ctx.setLineDash([4, 6]);
        ctx.stroke();
        ctx.setLineDash([]);

        // Zone label
        ctx.fillStyle = color;
        ctx.font = `600 ${Math.max(10, Math.round(11 * zoom))}px sans-serif`;
        ctx.textAlign = "center";
        ctx.fillText(label, center.x, center.y - 45 * zoom);
        ctx.restore();
      };

      drawZone(-3.5, -3.5, "ĐỘI CONTENT (NỘI DUNG)", "rgba(56, 189, 248, 0.35)");
      drawZone(3.5, -3.5, "ĐỘI FUNNELS (BÁN HÀNG)", "rgba(168, 85, 247, 0.35)");
      drawZone(-3.5, 3.5, "NGHIÊN CỨU & R&D", "rgba(52, 211, 153, 0.35)");
      drawZone(3.5, 3.5, "THƯƠNG MẠI & VẬN HÀNH", "rgba(245, 158, 11, 0.35)");
      drawZone(0, 0, "TỔNG CHỈ HUY", "rgba(236, 72, 153, 0.45)");

      // Sort agents from back to front for proper isometric depth occlusion
      const sortedAgents = [...agents].sort((a, b) => a.gridX + a.gridY - (b.gridX + b.gridY));

      // Draw Desks & Animated Chibi Agents
      sortedAgents.forEach((agent) => {
        // Filter check
        if (activeFilter !== "all" && agent.department !== activeFilter) return;

        const pos = toScreen(agent.gridX, agent.gridY, originX, originY, zoom, pan);
        const isHovered = hoveredAgent?.id === agent.id;
        const isSelected = selectedAgent?.id === agent.id;
        const bobbing = Math.sin(tick * 0.05 + agent.gridX * 10) * 3 * zoom;

        // 1. Draw Desk
        ctx.save();
        const dw = 38 * zoom;
        const dh = 20 * zoom;

        // Desk Shadow
        ctx.beginPath();
        ctx.ellipse(pos.x, pos.y + 6 * zoom, dw * 0.9, dh * 0.6, 0, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(0, 0, 0, 0.45)";
        ctx.fill();

        // Desk Surface
        ctx.beginPath();
        ctx.moveTo(pos.x, pos.y - dh / 2);
        ctx.lineTo(pos.x + dw / 2, pos.y);
        ctx.lineTo(pos.x, pos.y + dh / 2);
        ctx.lineTo(pos.x - dw / 2, pos.y);
        ctx.closePath();
        ctx.fillStyle = "#1e293b";
        ctx.fill();
        ctx.strokeStyle = "#334155";
        ctx.lineWidth = 1;
        ctx.stroke();

        // Laptop / Monitor screen glow
        const monitorX = pos.x;
        const monitorY = pos.y - 6 * zoom;
        ctx.fillStyle = "#0f172a";
        ctx.fillRect(monitorX - 8 * zoom, monitorY - 10 * zoom, 16 * zoom, 10 * zoom);
        ctx.strokeStyle = agent.color;
        ctx.lineWidth = 1;
        ctx.strokeRect(monitorX - 8 * zoom, monitorY - 10 * zoom, 16 * zoom, 10 * zoom);

        // Screen glow flicker
        ctx.fillStyle = agent.color;
        ctx.globalAlpha = 0.6 + Math.sin(tick * 0.1) * 0.2;
        ctx.fillRect(monitorX - 6 * zoom, monitorY - 8 * zoom, 12 * zoom, 6 * zoom);
        ctx.globalAlpha = 1.0;

        // 2. Draw Agent Character (Chibi Avatar behind desk)
        const charX = pos.x;
        const charY = pos.y - 18 * zoom + bobbing;

        // Status Aura Ring if working
        if (agent.status === "working") {
          ctx.beginPath();
          ctx.arc(charX, charY - 8 * zoom, 18 * zoom, 0, Math.PI * 2);
          ctx.strokeStyle = agent.color;
          ctx.lineWidth = 1.5;
          ctx.globalAlpha = 0.4 + Math.sin(tick * 0.08) * 0.3;
          ctx.stroke();
          ctx.globalAlpha = 1.0;
        }

        // Selection / Hover Highlight Ring
        if (isSelected || isHovered) {
          ctx.beginPath();
          ctx.arc(charX, charY - 8 * zoom, 22 * zoom, 0, Math.PI * 2);
          ctx.strokeStyle = "#ffffff";
          ctx.lineWidth = 2;
          ctx.setLineDash([3, 3]);
          ctx.stroke();
          ctx.setLineDash([]);
        }

        // Body / Torso
        ctx.beginPath();
        ctx.arc(charX, charY, 9 * zoom, 0, Math.PI * 2);
        ctx.fillStyle = agent.color;
        ctx.fill();
        ctx.strokeStyle = "#0f172a";
        ctx.lineWidth = 1.5;
        ctx.stroke();

        // Head
        ctx.beginPath();
        ctx.arc(charX, charY - 12 * zoom, 8 * zoom, 0, Math.PI * 2);
        ctx.fillStyle = "#fed7aa"; // Skin tone
        ctx.fill();
        ctx.strokeStyle = "#0f172a";
        ctx.lineWidth = 1.5;
        ctx.stroke();

        // Hair / Cap
        ctx.beginPath();
        ctx.arc(charX, charY - 14 * zoom, 8 * zoom, Math.PI, Math.PI * 2);
        ctx.fillStyle = agent.color;
        ctx.fill();

        // Eyes (blinking)
        const isBlinking = tick % 120 > 115;
        if (!isBlinking) {
          ctx.fillStyle = "#0f172a";
          ctx.fillRect(charX - 3 * zoom, charY - 13 * zoom, 1.5 * zoom, 2 * zoom);
          ctx.fillRect(charX + 1.5 * zoom, charY - 13 * zoom, 1.5 * zoom, 2 * zoom);
        }

        // 3. Nameplate Badge
        ctx.font = `600 ${Math.max(9, Math.round(10 * zoom))}px sans-serif`;
        ctx.textAlign = "center";
        const nameText = `@${agent.name}`;
        const nameMetrics = ctx.measureText(nameText);
        const nameW = nameMetrics.width + 12 * zoom;
        const nameH = 16 * zoom;

        ctx.fillStyle = "rgba(15, 23, 42, 0.85)";
        ctx.strokeStyle = isSelected ? "#38bdf8" : "rgba(255, 255, 255, 0.15)";
        ctx.lineWidth = 1;
        ctx.roundRect(charX - nameW / 2, charY + 12 * zoom, nameW, nameH, 4 * zoom);
        ctx.fill();
        ctx.stroke();

        // Status indicator dot inside badge
        ctx.beginPath();
        ctx.arc(charX - nameW / 2 + 6 * zoom, charY + 20 * zoom, 2.5 * zoom, 0, Math.PI * 2);
        ctx.fillStyle = agent.status === "working" ? "#38bdf8" : "#10b981";
        ctx.fill();

        // Text inside badge
        ctx.fillStyle = "#f8fafc";
        ctx.fillText(nameText, charX + 3 * zoom, charY + 24 * zoom);

        // 4. Speech bubble thought if working or hovered
        if (agent.status === "working" || isHovered) {
          const thoughtText = isHovered ? agent.displayName : agent.thought;
          ctx.font = `400 ${Math.max(9, Math.round(9.5 * zoom))}px sans-serif`;
          const thoughtMetrics = ctx.measureText(thoughtText);
          const tWidth = thoughtMetrics.width + 14 * zoom;
          const tHeight = 18 * zoom;
          const tX = charX;
          const tY = charY - 28 * zoom;

          // Bubble background
          ctx.fillStyle = "rgba(15, 23, 42, 0.95)";
          ctx.strokeStyle = agent.color;
          ctx.lineWidth = 1;
          ctx.roundRect(tX - tWidth / 2, tY - tHeight / 2, tWidth, tHeight, 6 * zoom);
          ctx.fill();
          ctx.stroke();

          // Bubble tail
          ctx.beginPath();
          ctx.moveTo(tX - 4 * zoom, tY + tHeight / 2);
          ctx.lineTo(tX, tY + tHeight / 2 + 5 * zoom);
          ctx.lineTo(tX + 4 * zoom, tY + tHeight / 2);
          ctx.fillStyle = "rgba(15, 23, 42, 0.95)";
          ctx.fill();

          // Bubble text
          ctx.fillStyle = "#e2e8f0";
          ctx.fillText(thoughtText, tX, tY + 3.5 * zoom);
        }

        ctx.restore();
      });

      animationFrameId = requestAnimationFrame(render);
    };

    render();

    return () => {
      cancelAnimationFrame(animationFrameId);
      window.removeEventListener("resize", resizeCanvas);
    };
  }, [zoom, pan, activeFilter, hoveredAgent, selectedAgent, toScreen]);

  // Handle Mouse Interactions (Pan & Click Hit-test)
  const handleMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    setIsDragging(true);
    setDragStart({ x: e.clientX - pan.x, y: e.clientY - pan.y });
  };

  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (isDragging) {
      setPan({
        x: e.clientX - dragStart.x,
        y: e.clientY - dragStart.y,
      });
      return;
    }

    // Hit-testing for hovered agent
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    const originX = rect.width / 2;
    const originY = rect.height / 2 - 20;

    let found: AgentVisual | null = null;
    for (const agent of agents) {
      if (activeFilter !== "all" && agent.department !== activeFilter) continue;
      const pos = toScreen(agent.gridX, agent.gridY, originX, originY, zoom, pan);
      const dx = mouseX - pos.x;
      const dy = mouseY - (pos.y - 12 * zoom);
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < 26 * zoom) {
        found = agent;
        break;
      }
    }
    setHoveredAgent(found);
    canvas.style.cursor = found ? "pointer" : isDragging ? "grabbing" : "grab";
  };

  const handleMouseUp = () => {
    setIsDragging(false);
  };

  const handleClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (hoveredAgent) {
      setSelectedAgent(hoveredAgent);
      if (onSelectAgent) onSelectAgent(hoveredAgent);
    }
  };

  const handleZoom = (delta: number) => {
    setZoom((prev) => Math.max(0.6, Math.min(2.0, prev + delta)));
  };

  const handleReset = () => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
    setSelectedAgent(null);
    setActiveFilter("all");
  };

  return (
    <div
      ref={containerRef}
      className={`relative w-full h-[520px] rounded-2xl bg-gray-950 border border-gray-800 overflow-hidden shadow-2xl flex flex-col ${className}`}
    >
      {/* Top Floating Control Bar */}
      <div className="absolute top-4 left-4 right-4 z-10 flex flex-wrap items-center justify-between pointer-events-none gap-2">
        {/* Department Filters */}
        <div className="flex items-center gap-1.5 p-1 rounded-xl bg-gray-900/80 backdrop-blur-md border border-gray-800 pointer-events-auto">
          {[
            { id: "all", label: "Tất cả", icon: Users },
            { id: "Đội Content", label: "Content", icon: PenTool },
            { id: "Đội Funnels", label: "Funnels", icon: GitMerge },
            { id: "Nghiên cứu & Phát triển", label: "R&D", icon: Compass },
            { id: "Thương mại điện tử", label: "E-Com", icon: ShoppingCart },
          ].map((f) => {
            const Icon = f.icon;
            const isActive = activeFilter === f.id;
            return (
              <button
                key={f.id}
                type="button"
                onClick={() => setActiveFilter(f.id)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                  isActive
                    ? "bg-sky-500 text-white shadow-sm"
                    : "text-gray-400 hover:text-gray-200 hover:bg-gray-800/60"
                }`}
              >
                <Icon className="w-3.5 h-3.5" />
                <span>{f.label}</span>
              </button>
            );
          })}
        </div>

        {/* Camera & Zoom Controls */}
        <div className="flex items-center gap-1 p-1 rounded-xl bg-gray-900/80 backdrop-blur-md border border-gray-800 pointer-events-auto text-gray-400">
          <button
            type="button"
            onClick={() => handleZoom(0.15)}
            className="p-1.5 hover:text-white hover:bg-gray-800 rounded-lg transition-colors"
            title="Phóng to"
          >
            <ZoomIn className="w-4 h-4" />
          </button>
          <button
            type="button"
            onClick={() => handleZoom(-0.15)}
            className="p-1.5 hover:text-white hover:bg-gray-800 rounded-lg transition-colors"
            title="Thu nhỏ"
          >
            <ZoomOut className="w-4 h-4" />
          </button>
          <button
            type="button"
            onClick={handleReset}
            className="p-1.5 hover:text-white hover:bg-gray-800 rounded-lg transition-colors"
            title="Đặt lại góc nhìn"
          >
            <RotateCcw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Main Interactive Canvas */}
      <canvas
        ref={canvasRef}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        onClick={handleClick}
        className="w-full h-full block touch-none"
      />

      {/* Selected Agent Quick Inspector Popup */}
      {selectedAgent && (
        <div className="absolute bottom-4 left-4 right-4 md:right-auto md:w-96 z-10 p-4 rounded-xl bg-gray-900/90 backdrop-blur-md border border-sky-500/50 shadow-2xl space-y-3">
          <div className="flex items-center justify-between border-b border-gray-800 pb-2">
            <div className="flex items-center gap-2">
              <div
                className="w-3.5 h-3.5 rounded-full animate-pulse"
                style={{ backgroundColor: selectedAgent.color }}
              />
              <span className="font-semibold text-sm text-white">
                @{selectedAgent.name} ({selectedAgent.displayName})
              </span>
            </div>
            <button
              type="button"
              onClick={() => setSelectedAgent(null)}
              className="text-gray-400 hover:text-white text-xs px-1.5 py-0.5 rounded bg-gray-800"
            >
              ✕
            </button>
          </div>

          <div className="text-xs space-y-1.5 text-gray-300">
            <div className="flex justify-between">
              <span className="text-gray-500">Phòng ban:</span>
              <span className="font-medium text-sky-400">{selectedAgent.department}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Vai trò chính:</span>
              <span>{selectedAgent.role}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Trạng thái:</span>
              <span className="text-emerald-400 font-medium">
                {selectedAgent.status === "working" ? "⚡ Đang xử lý task" : "✓ Rảnh rỗi"}
              </span>
            </div>
            <div className="mt-2 p-2 rounded-lg bg-gray-950 border border-gray-800 text-[11px] font-mono text-gray-300">
              💬 &quot;{selectedAgent.thought}&quot;
            </div>
          </div>
        </div>
      )}

      {/* Bottom Hint */}
      <div className="absolute bottom-3 right-4 text-[11px] text-gray-500 pointer-events-none flex items-center gap-1.5">
        <Sparkles className="w-3.5 h-3.5 text-sky-400" />
        <span>Kéo để xoay &amp; di chuyển • Nhấp vào Agent để xem trạng thái</span>
      </div>
    </div>
  );
}
