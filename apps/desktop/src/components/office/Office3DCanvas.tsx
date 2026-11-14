"use client";

import React, { useEffect, useRef, useState, useCallback } from "react";
import {
  RotateCcw,
  ZoomIn,
  ZoomOut,
  Sparkles,
  Users,
  PenTool,
  GitMerge,
  Coffee,
  Building2,
} from "lucide-react";

export interface AgentVisual {
  id: string;
  name: string;
  displayName: string;
  role: string;
  department: "Tổng bộ" | "Đội Content" | "Đội Funnels" | "Phòng nghỉ" | "Khu trung tâm";
  color: string;
  status: "idle" | "working" | "review";
  thought: string;
  gridX: number;
  gridY: number;
  skills: string[];
  model: string;
}

export const TAKO_22_AGENTS: AgentVisual[] = [
  // 1. TỔNG BỘ (Master Commander at origin)
  {
    id: "commander",
    name: "Người điều phối",
    displayName: "Tổng Chỉ Huy Đa Tác Tử",
    role: "Chỉ huy trung tâm & phân chia công việc",
    department: "Tổng bộ",
    color: "#6366f1",
    status: "working",
    thought: "Đang điều phối 12 Agent hoàn thành kịch bản & Landing Page...",
    gridX: 0,
    gridY: 0,
    skills: ["Điều phối DAG", "Phân tích NLP", "Human-in-the-Loop"],
    model: "GPT-6 Luna",
  },

  // 2-7. ĐỘI CONTENT (Top-right zone: 6 Agents)
  {
    id: "writer",
    name: "ContentWriter",
    displayName: "Trần Viết Văn",
    role: "Biên tập kịch bản & nội dung viral",
    department: "Đội Content",
    color: "#10b981",
    status: "working",
    thought: "Đang soạn kịch bản video TikTok 60s hook tài chính...",
    gridX: 3.5,
    gridY: -3,
    skills: ["Kịch bản TikTok 60s", "W-Structure", "Storytelling"],
    model: "Claude 3.7 Sonnet",
  },
  {
    id: "hook-master",
    name: "HookMaster",
    displayName: "Lê Móc Câu",
    role: "Tạo tiêu đề giật gân & hook 3s đầu",
    department: "Đội Content",
    color: "#f59e0b",
    status: "working",
    thought: "Đã hoàn thành 3 hook triệu view cho bài bán hàng...",
    gridX: 2.5,
    gridY: -4.5,
    skills: ["Hook 3s Viral", "Curiosity Gap", "Headline Matrix"],
    model: "GPT-6 Luna",
  },
  {
    id: "copywriter",
    name: "Copywriter",
    displayName: "Nguyễn Chốt Đơn",
    role: "Viết lời chào hàng & thư bán hàng",
    department: "Đội Content",
    color: "#06b6d4",
    status: "idle",
    thought: "Sẵn sàng viết bài PR & chuyển đổi",
    gridX: 4.5,
    gridY: -4.5,
    skills: ["PAS Framework", "AIDA", "Direct Response"],
    model: "Claude 3.7 Sonnet",
  },
  {
    id: "storyteller",
    name: "Storyteller",
    displayName: "Vũ Kể Chuyện",
    role: "Xây dựng câu chuyện thương hiệu chạm cảm xúc",
    department: "Đội Content",
    color: "#8b5cf6",
    status: "idle",
    thought: "Cốt truyện hành trình người hùng sẵn sàng",
    gridX: 5.5,
    gridY: -3,
    skills: ["Hero's Journey", "Emotional Resonance", "Brand Story"],
    model: "Claude 3.7 Sonnet",
  },
  {
    id: "email-specialist",
    name: "EmailSpecialist",
    displayName: "Phạm Hộp Thư",
    role: "Soạn chuỗi email onboarding & nuôi dưỡng",
    department: "Đội Content",
    color: "#3b82f6",
    status: "idle",
    thought: "Chuỗi 5 email nuôi dưỡng sẵn sàng xuất",
    gridX: 3.5,
    gridY: -6,
    skills: ["Drip Campaign", "Subject Line Tester", "Lifecycle Marketing"],
    model: "Gemini 2.5 Flash",
  },
  {
    id: "seo-strategist",
    name: "SEOStrategist",
    displayName: "Hoàng Tối Ưu",
    role: "Tối ưu hóa công cụ tìm kiếm chuẩn Google Top 1",
    department: "Đội Content",
    color: "#14b8a6",
    status: "idle",
    thought: "Nghiên cứu xong bộ từ khóa ngành Solopreneur",
    gridX: 4.5,
    gridY: -6,
    skills: ["Topic Cluster", "On-Page SEO", "Search Intent Matching"],
    model: "GPT-6 Luna",
  },

  // 8-13. ĐỘI FUNNELS (Bottom-right zone: 6 Agents)
  {
    id: "funnels-agent",
    name: "FunnelsAgent",
    displayName: "Hoàng Phễu Bán",
    role: "Kiến trúc phễu bán hàng tự động",
    department: "Đội Funnels",
    color: "#a855f7",
    status: "working",
    thought: "Đang vẽ sơ đồ phễu thu hút quà tặng Lead Magnet...",
    gridX: 3.5,
    gridY: 3,
    skills: ["Tripwire Funnel", "Webinar Funnel", "Conversion Optimization"],
    model: "GPT-6 Luna",
  },
  {
    id: "offer-creator",
    name: "OfferCreator",
    displayName: "Đỗ Lời Đề Nghị",
    role: "Tạo lời chào hàng không thể chối từ",
    department: "Đội Funnels",
    color: "#ec4899",
    status: "idle",
    thought: "Gói ưu đãi 100M Grand Slam Offer hoàn tất",
    gridX: 2.5,
    gridY: 4.5,
    skills: ["Grand Slam Offer", "Bonus Stacking", "Price Anchoring"],
    model: "Claude 3.7 Sonnet",
  },
  {
    id: "vsl-writer",
    name: "VslWriter",
    displayName: "Bùi Kịch Bản VSL",
    role: "Biên kịch Video Sales Letter chuyển đổi cao",
    department: "Đội Funnels",
    color: "#f43f5e",
    status: "idle",
    thought: "Kịch bản VSL 12 phút sẵn sàng",
    gridX: 4.5,
    gridY: 4.5,
    skills: ["12-Step VSL", "Objection Handling", "Pattern Interrupt"],
    model: "Claude 3.7 Sonnet",
  },
  {
    id: "landing-designer",
    name: "LandingPageDesigner",
    displayName: "Mai Trang Đích",
    role: "Thiết kế cấu trúc trang đích tối ưu UI/UX",
    department: "Đội Funnels",
    color: "#06b6d4",
    status: "working",
    thought: "Xuất bản HTML Landing Page Solopreneur...",
    gridX: 5.5,
    gridY: 3,
    skills: ["Interactive HTML", "Mobile First", "High CTR"],
    model: "GPT-6 Luna",
  },
  {
    id: "ad-copywriter",
    name: "AdCopywriter",
    displayName: "Trịnh Quảng Cáo",
    role: "Soạn nội dung quảng cáo Facebook & TikTok Ads",
    department: "Đội Funnels",
    color: "#f97316",
    status: "idle",
    thought: "5 góc độ quảng cáo testing sẵn sàng",
    gridX: 3.5,
    gridY: 6,
    skills: ["Meta Ads", "TikTok Ads", "UGC Scripting"],
    model: "Gemini 2.5 Flash",
  },
  {
    id: "leadmagnet-maker",
    name: "LeadMagnetMaker",
    displayName: "Chu Quà Tặng",
    role: "Soạn tài liệu PDF & cẩm nang thu hút leads",
    department: "Đội Funnels",
    color: "#eab308",
    status: "idle",
    thought: "Checklist 10 bước tự động hóa kinh doanh",
    gridX: 4.5,
    gridY: 6,
    skills: ["PDF Cheat-Sheet", "Template Creator", "Opt-in Bumper"],
    model: "Claude 3.7 Sonnet",
  },

  // 14-17. PHÒNG NGHỈ (Sofa tím lounge - Bottom-left zone: 4 Agents)
  {
    id: "image-studio",
    name: "ImageStudio",
    displayName: "Vũ Đồ Họa AI",
    role: "Thiết kế poster & ảnh mạng xã hội",
    department: "Phòng nghỉ",
    color: "#ec4899",
    status: "idle",
    thought: "Đang thưởng trà tại quầy nước, chờ lệnh ảnh mới",
    gridX: -3.5,
    gridY: 3.5,
    skills: ["AI Image Prompt", "Canva Direct Export", "Banner 1080x1080"],
    model: "⚡ Antigravity CLI",
  },
  {
    id: "code-architect",
    name: "CodeArchitect",
    displayName: "Lâm Lập Trình",
    role: "Tích hợp API & script tự động hóa",
    department: "Phòng nghỉ",
    color: "#06b6d4",
    status: "idle",
    thought: "Đang ngồi sofa tím nghiên cứu WebSocket daemon",
    gridX: -4.5,
    gridY: 4.5,
    skills: ["Python Scripting", "REST/WebSocket", "Docker Deployment"],
    model: "Claude 3.7 Sonnet",
  },
  {
    id: "data-analyst",
    name: "DataAnalyst",
    displayName: "Tô Số Liệu",
    role: "Phân tích số liệu phễu & đo lường chuyển đổi",
    department: "Phòng nghỉ",
    color: "#10b981",
    status: "idle",
    thought: "Báo cáo doanh số tháng đã gửi vào thư viện",
    gridX: -2.5,
    gridY: 4.5,
    skills: ["Funnel Analytics", "LTV Calculator", "A/B Testing Stat"],
    model: "GPT-6 Luna",
  },
  {
    id: "workflow-automator",
    name: "WorkflowAutomator",
    displayName: "Đoàn Tự Động",
    role: "Xây dựng kịch bản liên kết Make/n8n",
    department: "Phòng nghỉ",
    color: "#eab308",
    status: "idle",
    thought: "Hệ thống Zapier/n8n hoạt động trơn tru 100%",
    gridX: -3.5,
    gridY: 5.5,
    skills: ["n8n Workflow", "Webhook Automation", "CRM Sync"],
    model: "⚡ Antigravity CLI",
  },

  // 18-22. KHU TRUNG TÂM & MỞ (Top-left open zone: 5 Agents)
  {
    id: "deep-researcher",
    name: "DeepResearcher",
    displayName: "Ngô Khảo Sát",
    role: "Nghiên cứu thị trường & đối thủ chiều sâu",
    department: "Khu trung tâm",
    color: "#8b5cf6",
    status: "working",
    thought: "Đang cào dữ liệu xu hướng AI Agents 2026...",
    gridX: -3.5,
    gridY: -3,
    skills: ["Deep Web Search", "Competitor Matrix", "Market Synthesis"],
    model: "Claude 3.7 Sonnet",
  },
  {
    id: "ui-designer",
    name: "UIDesigner",
    displayName: "Đinh Giao Diện",
    role: "Thiết kế UI/UX & Interactive Web App",
    department: "Khu trung tâm",
    color: "#ef4444",
    status: "working",
    thought: "Render iframe Sandbox cho Landing Page...",
    gridX: -2.5,
    gridY: -4.5,
    skills: ["Tailwind CSS", "Interactive Sandbox", "Figma Connect"],
    model: "GPT-6 Luna",
  },
  {
    id: "video-editor",
    name: "VideoEditor",
    displayName: "Hà Dựng Phim",
    role: "Biên tập video ngắn phong cách Rainmaker",
    department: "Khu trung tâm",
    color: "#3b82f6",
    status: "idle",
    thought: "Sẵn sàng cắt video dọc 9:16 & chữ vàng karaoke",
    gridX: -4.5,
    gridY: -4.5,
    skills: ["FFmpeg DSP", "Silence Removal", "Kinetic Subtitles"],
    model: "⚡ Antigravity CLI",
  },
  {
    id: "cskh",
    name: "CSKH",
    displayName: "Mai Chăm Khách",
    role: "Hỗ trợ khách hàng đa kênh Zalo & Telegram",
    department: "Khu trung tâm",
    color: "#f43f5e",
    status: "working",
    thought: "Đang trả lời 3 khách hàng quan tâm khóa học...",
    gridX: -1.5,
    gridY: -2,
    skills: ["Zalo Integration", "FAQ Auto-reply", "Sentiment Analysis"],
    model: "Gemini 2.5 Flash",
  },
  {
    id: "sales-agent",
    name: "SalesAgent",
    displayName: "Trịnh Tư Vấn",
    role: "Tư vấn chốt đơn & gửi link thanh toán",
    department: "Khu trung tâm",
    color: "#10b981",
    status: "idle",
    thought: "Sẵn sàng hỗ trợ đơn hàng mới",
    gridX: 1.5,
    gridY: -2,
    skills: ["Direct Selling", "Payment Link Gen", "Follow-up Cadence"],
    model: "GPT-6 Luna",
  },
];

export interface Office3DCanvasProps {
  onSelectAgent?: (agent: AgentVisual) => void;
  className?: string;
}

export function Office3DCanvas({ onSelectAgent, className = "" }: Office3DCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const [zoom, setZoom] = useState(1.1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });
  const [selectedAgent, setSelectedAgent] = useState<AgentVisual | null>(null);
  const [hoveredAgent, setHoveredAgent] = useState<AgentVisual | null>(null);
  const [activeFilter, setActiveFilter] = useState<string>("all");

  const agents = TAKO_22_AGENTS;

  const TILE_WIDTH = 64;
  const TILE_HEIGHT = 32;

  const toScreen = useCallback(
    (gridX: number, gridY: number, originX: number, originY: number, currentZoom: number, currentPan: { x: number; y: number }) => {
      const screenX = originX + (gridX - gridY) * (TILE_WIDTH / 2) * currentZoom + currentPan.x;
      const screenY = originY + (gridX + gridY) * (TILE_HEIGHT / 2) * currentZoom + currentPan.y;
      return { x: screenX, y: screenY };
    },
    [TILE_WIDTH, TILE_HEIGHT]
  );

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

      // Dark background gradient
      const bgGrad = ctx.createRadialGradient(originX, originY, 40, originX, originY, Math.max(width, height));
      bgGrad.addColorStop(0, "#090d16");
      bgGrad.addColorStop(1, "#020617");
      ctx.fillStyle = bgGrad;
      ctx.fillRect(0, 0, width, height);

      // Floor tiles
      const GRID_RADIUS = 7;
      for (let i = -GRID_RADIUS; i <= GRID_RADIUS; i++) {
        for (let j = -GRID_RADIUS; j <= GRID_RADIUS; j++) {
          const pt = toScreen(i, j, originX, originY, zoom, pan);

          ctx.beginPath();
          ctx.moveTo(pt.x, pt.y - (TILE_HEIGHT / 2) * zoom);
          ctx.lineTo(pt.x + (TILE_WIDTH / 2) * zoom, pt.y);
          ctx.lineTo(pt.x, pt.y + (TILE_HEIGHT / 2) * zoom);
          ctx.lineTo(pt.x - (TILE_WIDTH / 2) * zoom, pt.y);
          ctx.closePath();

          let tileColor = "rgba(255, 255, 255, 0.01)";
          if (i > 0 && j < 0) tileColor = "rgba(16, 185, 129, 0.03)"; // Content zone
          else if (i > 0 && j > 0) tileColor = "rgba(168, 85, 247, 0.03)"; // Funnels zone
          else if (i < 0 && j > 0) tileColor = "rgba(147, 51, 234, 0.04)"; // Purple Lounge sofa
          else if (i < 0 && j < 0) tileColor = "rgba(56, 189, 248, 0.03)"; // Open area
          else if (i === 0 && j === 0) tileColor = "rgba(99, 102, 241, 0.08)"; // Commander

          ctx.fillStyle = tileColor;
          ctx.fill();
          ctx.strokeStyle = "rgba(255, 255, 255, 0.035)";
          ctx.stroke();
        }
      }

      // 4 Pod Zone Rings
      const drawZone = (gx: number, gy: number, label: string, color: string) => {
        const center = toScreen(gx, gy, originX, originY, zoom, pan);
        ctx.save();
        ctx.beginPath();
        ctx.ellipse(center.x, center.y, 140 * zoom, 70 * zoom, 0, 0, Math.PI * 2);
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.5;
        ctx.setLineDash([4, 6]);
        ctx.stroke();
        ctx.setLineDash([]);

        ctx.fillStyle = color;
        ctx.font = `bold ${Math.max(10, Math.round(11 * zoom))}px sans-serif`;
        ctx.textAlign = "center";
        ctx.fillText(label, center.x, center.y - 48 * zoom);
        ctx.restore();
      };

      drawZone(4, -4.5, "ĐỘI CONTENT (6 AGENT)", "rgba(16, 185, 129, 0.45)");
      drawZone(4, 4.5, "ĐỘI FUNNELS (6 AGENT)", "rgba(168, 85, 247, 0.45)");
      drawZone(-3.5, 4.5, "PHÒNG NGHỈ (SOFA TÍM & CÀ PHÊ)", "rgba(147, 51, 234, 0.45)");
      drawZone(-3.5, -3.5, "KHU MỞ & VẬN HÀNH (5 AGENT)", "rgba(56, 189, 248, 0.45)");
      drawZone(0, 0, "TỔNG CHỈ HUY", "rgba(99, 102, 241, 0.6)");

      // Draw Purple Lounge Sofa in bottom-left zone
      const sofaCenter = toScreen(-3.5, 4.5, originX, originY, zoom, pan);
      ctx.save();
      const sw = 70 * zoom;
      const sh = 28 * zoom;
      ctx.beginPath();
      ctx.ellipse(sofaCenter.x, sofaCenter.y, sw, sh, 0, 0, Math.PI * 2);
      ctx.fillStyle = "rgba(88, 28, 135, 0.4)";
      ctx.fill();
      ctx.strokeStyle = "#9333ea";
      ctx.lineWidth = 2;
      ctx.stroke();

      ctx.fillStyle = "#c084fc";
      ctx.font = `600 ${Math.max(9, Math.round(9 * zoom))}px sans-serif`;
      ctx.textAlign = "center";
      ctx.fillText("🛋️ Sofa Tím Nghỉ Ngơi", sofaCenter.x, sofaCenter.y + 4 * zoom);
      ctx.restore();

      // Sort agents by depth
      const sortedAgents = [...agents].sort((a, b) => a.gridX + a.gridY - (b.gridX + b.gridY));

      // Draw each agent
      sortedAgents.forEach((agent) => {
        if (activeFilter !== "all" && agent.department !== activeFilter) return;

        const pos = toScreen(agent.gridX, agent.gridY, originX, originY, zoom, pan);
        const isHovered = hoveredAgent?.id === agent.id;
        const isSelected = selectedAgent?.id === agent.id;
        const isWorking = agent.status === "working";
        const bobbing = isWorking ? Math.sin(tick * 0.05 + agent.gridX * 10) * 3.5 * zoom : 0;

        // Desk
        ctx.save();
        const dw = 36 * zoom;
        const dh = 18 * zoom;

        ctx.beginPath();
        ctx.ellipse(pos.x, pos.y + 5 * zoom, dw * 0.9, dh * 0.6, 0, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(0, 0, 0, 0.4)";
        ctx.fill();

        ctx.beginPath();
        ctx.moveTo(pos.x, pos.y - dh / 2);
        ctx.lineTo(pos.x + dw / 2, pos.y);
        ctx.lineTo(pos.x, pos.y + dh / 2);
        ctx.lineTo(pos.x - dw / 2, pos.y);
        ctx.closePath();
        ctx.fillStyle = "#1e293b";
        ctx.fill();
        ctx.strokeStyle = "#334155";
        ctx.stroke();

        // Monitor
        const mx = pos.x;
        const my = pos.y - 6 * zoom;
        ctx.fillStyle = "#0f172a";
        ctx.fillRect(mx - 7 * zoom, my - 9 * zoom, 14 * zoom, 9 * zoom);
        ctx.strokeStyle = agent.color;
        ctx.strokeRect(mx - 7 * zoom, my - 9 * zoom, 14 * zoom, 9 * zoom);

        ctx.fillStyle = agent.color;
        ctx.globalAlpha = 0.6 + Math.sin(tick * 0.1) * 0.25;
        ctx.fillRect(mx - 5 * zoom, my - 7 * zoom, 10 * zoom, 5 * zoom);
        ctx.globalAlpha = 1.0;

        // Chibi Agent
        const charX = pos.x;
        const charY = pos.y - 17 * zoom + bobbing;

        // Aura ring
        if (isWorking) {
          ctx.beginPath();
          ctx.arc(charX, charY - 8 * zoom, 18 * zoom, 0, Math.PI * 2);
          ctx.strokeStyle = agent.color;
          ctx.lineWidth = 1.5;
          ctx.globalAlpha = 0.4 + Math.sin(tick * 0.08) * 0.3;
          ctx.stroke();
          ctx.globalAlpha = 1.0;
        }

        // Selection ring
        if (isSelected || isHovered) {
          ctx.beginPath();
          ctx.arc(charX, charY - 8 * zoom, 22 * zoom, 0, Math.PI * 2);
          ctx.strokeStyle = "#ffffff";
          ctx.lineWidth = 2;
          ctx.setLineDash([3, 3]);
          ctx.stroke();
          ctx.setLineDash([]);
        }

        // Torso
        ctx.beginPath();
        ctx.arc(charX, charY, 9 * zoom, 0, Math.PI * 2);
        ctx.fillStyle = agent.color;
        ctx.fill();
        ctx.strokeStyle = "#0f172a";
        ctx.lineWidth = 1.5;
        ctx.stroke();

        // Head
        ctx.beginPath();
        ctx.arc(charX, charY - 11 * zoom, 8 * zoom, 0, Math.PI * 2);
        ctx.fillStyle = "#fed7aa";
        ctx.fill();
        ctx.strokeStyle = "#0f172a";
        ctx.lineWidth = 1.5;
        ctx.stroke();

        // Eyes
        const isBlinking = tick % 120 > 115;
        if (!isBlinking) {
          ctx.fillStyle = "#0f172a";
          ctx.fillRect(charX - 3 * zoom, charY - 12 * zoom, 1.5 * zoom, 2 * zoom);
          ctx.fillRect(charX + 1.5 * zoom, charY - 12 * zoom, 1.5 * zoom, 2 * zoom);
        }

        // Nameplate
        ctx.font = `600 ${Math.max(9, Math.round(9.5 * zoom))}px sans-serif`;
        ctx.textAlign = "center";
        const nameText = `@${agent.name}`;
        const nameMetrics = ctx.measureText(nameText);
        const nameW = nameMetrics.width + 12 * zoom;
        const nameH = 15 * zoom;

        ctx.fillStyle = "rgba(15, 23, 42, 0.9)";
        ctx.strokeStyle = isSelected ? "#38bdf8" : "rgba(255, 255, 255, 0.2)";
        ctx.lineWidth = 1;
        ctx.roundRect(charX - nameW / 2, charY + 11 * zoom, nameW, nameH, 4 * zoom);
        ctx.fill();
        ctx.stroke();

        ctx.fillStyle = "#f8fafc";
        ctx.fillText(nameText, charX, charY + 22 * zoom);

        // Speech Bubble
        if (isWorking || isHovered) {
          const thoughtText = isHovered ? agent.displayName : agent.thought;
          ctx.font = `400 ${Math.max(9, Math.round(9 * zoom))}px sans-serif`;
          const thoughtMetrics = ctx.measureText(thoughtText);
          const tWidth = thoughtMetrics.width + 14 * zoom;
          const tHeight = 18 * zoom;
          const tX = charX;
          const tY = charY - 26 * zoom;

          ctx.fillStyle = "rgba(15, 23, 42, 0.95)";
          ctx.strokeStyle = agent.color;
          ctx.lineWidth = 1;
          ctx.roundRect(tX - tWidth / 2, tY - tHeight / 2, tWidth, tHeight, 6 * zoom);
          ctx.fill();
          ctx.stroke();

          ctx.beginPath();
          ctx.moveTo(tX - 4 * zoom, tY + tHeight / 2);
          ctx.lineTo(tX, tY + tHeight / 2 + 5 * zoom);
          ctx.lineTo(tX + 4 * zoom, tY + tHeight / 2);
          ctx.fillStyle = "rgba(15, 23, 42, 0.95)";
          ctx.fill();

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

  const handleClick = () => {
    if (hoveredAgent) {
      setSelectedAgent(hoveredAgent);
      if (onSelectAgent) onSelectAgent(hoveredAgent);
    }
  };

  return (
    <div
      ref={containerRef}
      className={`relative w-full h-full min-h-[500px] overflow-hidden bg-slate-950 select-none rounded-2xl border border-slate-800 ${className}`}
    >
      {/* Top Floating Controls Bar */}
      <div className="absolute top-3 left-3 right-3 flex items-center justify-between z-10 pointer-events-none">
        {/* Department Filters */}
        <div className="flex items-center gap-1.5 p-1 bg-slate-900/90 border border-slate-700/80 rounded-xl backdrop-blur-md pointer-events-auto shadow-lg text-xs">
          {[
            { id: "all", label: "Tất cả (22 Agent)" },
            { id: "Đội Content", label: "Đội Content" },
            { id: "Đội Funnels", label: "Đội Funnels" },
            { id: "Phòng nghỉ", label: "Phòng nghỉ" },
            { id: "Khu trung tâm", label: "Khu trung tâm" },
          ].map((item) => (
            <button
              key={item.id}
              onClick={() => setActiveFilter(item.id)}
              className={`px-2.5 py-1 rounded-lg font-medium transition-all cursor-pointer ${
                activeFilter === item.id
                  ? "bg-indigo-600 text-white shadow-xs"
                  : "text-slate-400 hover:text-slate-200 hover:bg-slate-800"
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>

        {/* Viewport Zoom & Reset Controls */}
        <div className="flex items-center gap-1 p-1 bg-slate-900/90 border border-slate-700/80 rounded-xl backdrop-blur-md pointer-events-auto shadow-lg text-slate-300">
          <button
            type="button"
            title="Phóng to"
            onClick={() => setZoom((z) => Math.min(2.0, z + 0.15))}
            className="p-1.5 hover:text-white hover:bg-slate-800 rounded-lg transition-colors cursor-pointer"
          >
            <ZoomIn className="w-4 h-4" />
          </button>
          <button
            type="button"
            title="Thu nhỏ"
            onClick={() => setZoom((z) => Math.max(0.6, z - 0.15))}
            className="p-1.5 hover:text-white hover:bg-slate-800 rounded-lg transition-colors cursor-pointer"
          >
            <ZoomOut className="w-4 h-4" />
          </button>
          <button
            type="button"
            title="Góc nhìn mặc định"
            onClick={() => {
              setZoom(1.1);
              setPan({ x: 0, y: 0 });
            }}
            className="p-1.5 hover:text-white hover:bg-slate-800 rounded-lg transition-colors cursor-pointer"
          >
            <RotateCcw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Hidden quick select triggers for testability and keyboard navigation */}
      <div className="hidden">
        {agents.map((ag) => (
          <button
            key={ag.id}
            data-testid={`agent-quick-select-${ag.id}`}
            onClick={() => {
              setSelectedAgent(ag);
              if (onSelectAgent) onSelectAgent(ag);
            }}
          >
            {ag.name}
          </button>
        ))}
      </div>

      {/* Main 3D Canvas */}
      <canvas
        ref={canvasRef}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onClick={handleClick}
        className="w-full h-full block touch-none cursor-grab"
      />

      {/* Bottom Hint */}
      <div className="absolute bottom-3 right-4 text-[11px] text-slate-400 pointer-events-none flex items-center gap-1.5 bg-slate-950/80 px-2.5 py-1 rounded-lg border border-slate-800">
        <Sparkles className="w-3.5 h-3.5 text-indigo-400" />
        <span>Kéo chuột để di chuyển góc nhìn • Bấm vào Agent để xem chi tiết</span>
      </div>
    </div>
  );
}
