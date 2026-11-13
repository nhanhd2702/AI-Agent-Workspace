#!/usr/bin/env bash
# ==============================================================================
# AI Agent Workspace (Văn Phòng AI) - VPS Automated Deployment Script
# Target OS: Ubuntu 22.04 / 24.04 LTS, Debian 12
# Author: nhanhd2702
# ==============================================================================

set -euo pipefail

# Text formatting
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${CYAN}================================================================${NC}"
echo -e "${CYAN}   🚀 AI AGENT WORKSPACE - TỰ ĐỘNG CÀI ĐẶT & CHẠY TRÊN VPS      ${NC}"
echo -e "${CYAN}================================================================${NC}"

# 1. Kiểm tra quyền root / sudo
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}❌ Vui lòng chạy script với quyền root hoặc sudo: sudo bash $0${NC}"
  exit 1
fi

APP_DIR="${APP_DIR:-/opt/ai-agent-workspace}"
REPO_URL="${REPO_URL:-https://github.com/nhanhd2702/AI-Agent-Workspace.git}"
BRANCH="${BRANCH:-main}"
LOCAL_AUTH_TOKEN="${LOCAL_AUTH_TOKEN:-$(openssl rand -hex 32 2>/dev/null || echo 'dev-local-token')}"
BACKEND_PORT=8765
FRONTEND_PORT=3000

echo -e "\n${BLUE}[1/8] Cập nhật hệ thống & cài đặt các gói cơ sở...${NC}"
apt-get update -y
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  curl \
  wget \
  git \
  build-essential \
  software-properties-common \
  ffmpeg \
  ufw \
  nginx \
  ca-certificates \
  gnupg

# 2. Cài đặt Python 3.12 nếu chưa có
echo -e "\n${BLUE}[2/8] Kiểm tra & Cài đặt Python 3.12...${NC}"
if ! command -v python3.12 &>/dev/null; then
  echo -e "${YELLOW}Cài đặt Python 3.12 từ deadsnakes PPA...${NC}"
  add-apt-repository -y ppa:deadsnakes/ppa || true
  apt-get update -y
  apt-get install -y python3.12 python3.12-venv python3.12-dev python3-pip
else
  echo -e "${GREEN}✓ Python 3.12 đã sẵn sàng: $(python3.12 --version)${NC}"
fi

# 3. Cài đặt Node.js 20.x & pnpm
echo -e "\n${BLUE}[3/8] Kiểm tra & Cài đặt Node.js 20.x & pnpm...${NC}"
if ! command -v node &>/dev/null || [ "$(node -v | cut -d'.' -f1 | tr -d 'v')" -lt 20 ]; then
  echo -e "${YELLOW}Cài đặt Node.js 20.x từ NodeSource...${NC}"
  mkdir -p /etc/apt/keyrings
  curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg --yes
  echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list
  apt-get update -y
  apt-get install -y nodejs
fi
echo -e "${GREEN}✓ Node.js: $(node -v)${NC}"

if ! command -v pnpm &>/dev/null; then
  echo -e "${YELLOW}Cài đặt pnpm qua npm...${NC}"
  npm install -g pnpm
fi
echo -e "${GREEN}✓ pnpm: $(pnpm -v)${NC}"

# 4. Clone hoặc cập nhật mã nguồn dự án
echo -e "\n${BLUE}[4/8] Thiết lập mã nguồn dự án tại ${APP_DIR}...${NC}"
if [ -d "$APP_DIR/.git" ]; then
  echo -e "${YELLOW}Thư mục đã tồn tại, tiến hành pull code mới nhất từ nhánh ${BRANCH}...${NC}"
  cd "$APP_DIR"
  git fetch origin "$BRANCH"
  git checkout "$BRANCH"
  git pull origin "$BRANCH"
else
  echo -e "${YELLOW}Cloning repository từ ${REPO_URL}...${NC}"
  mkdir -p "$(dirname "$APP_DIR")"
  git clone -b "$BRANCH" "$REPO_URL" "$APP_DIR"
  cd "$APP_DIR"
fi

# 5. Cấu hình Backend (Python Virtualenv & Dependencies)
echo -e "\n${BLUE}[5/8] Thiết lập môi trường Backend (FastAPI & LangGraph)...${NC}"
cd "$APP_DIR/apps/backend"
if [ ! -d ".venv" ]; then
  python3.12 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -e ".[dev]"

# Tạo file .env backend nếu chưa có
if [ ! -f ".env" ]; then
  FERNET_KEY=$(python3.12 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
  cat <<EOF > .env
WORKSPACE_DIR=$APP_DIR/apps/backend/workspace
BACKEND_PORT=$BACKEND_PORT
LOCAL_AUTH_TOKEN=$LOCAL_AUTH_TOKEN
ENCRYPTION_KEY=$FERNET_KEY
MAX_WORKSPACE_BYTES=5368709120
EOF
  echo -e "${GREEN}✓ Đã tạo file .env cho Backend với Fernet encryption key an toàn.${NC}"
fi
mkdir -p "$APP_DIR/apps/backend/workspace"

# 6. Cấu hình Frontend (Build Next.js Static Export)
echo -e "\n${BLUE}[6/8] Cài đặt dependencies và Build Frontend...${NC}"
cd "$APP_DIR"
pnpm install --frozen-lockfile=false

cd "$APP_DIR/apps/desktop"
# Tạo .env.local cho desktop
cat <<EOF > .env.local
NEXT_PUBLIC_LOCAL_AUTH_TOKEN=$LOCAL_AUTH_TOKEN
EOF

pnpm build
echo -e "${GREEN}✓ Đã build tĩnh Frontend thành công vào thư mục out/.${NC}"

# 7. Thiết lập Systemd Services tự khởi động cùng OS
echo -e "\n${BLUE}[7/8] Thiết lập Systemd Daemon Services...${NC}"

# Service Backend
cat <<EOF > /etc/systemd/system/ai-agent-backend.service
[Unit]
Description=AI Agent Workspace Backend Daemon
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$APP_DIR/apps/backend
ExecStart=$APP_DIR/apps/backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port $BACKEND_PORT
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

# Service Frontend (Static HTTP Server qua Python hoặc serve)
cat <<EOF > /etc/systemd/system/ai-agent-frontend.service
[Unit]
Description=AI Agent Workspace Frontend Web
After=network.target ai-agent-backend.service

[Service]
Type=simple
User=root
WorkingDirectory=$APP_DIR/apps/desktop/out
ExecStart=/usr/bin/python3.12 -m http.server $FRONTEND_PORT --bind 0.0.0.0
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable ai-agent-backend.service
systemctl restart ai-agent-backend.service
systemctl enable ai-agent-frontend.service
systemctl restart ai-agent-frontend.service

# 8. Mở tường lửa (UFW Firewall)
echo -e "\n${BLUE}[8/8] Mở cổng tường lửa UFW ($FRONTEND_PORT, $BACKEND_PORT)...${NC}"
if command -v ufw &>/dev/null; then
  ufw allow $FRONTEND_PORT/tcp comment "AI Agent Frontend" || true
  ufw allow $BACKEND_PORT/tcp comment "AI Agent Backend" || true
  ufw reload || true
fi

# Chờ dịch vụ khởi động và kiểm tra Healthcheck
echo -e "\n${YELLOW}Đang kiểm tra kết nối dịch vụ...${NC}"
sleep 3
HEALTH_STATUS=$(curl -s "http://127.0.0.1:$BACKEND_PORT/api/v1/health" || echo "FAILED")

# Lấy địa chỉ IP công khai của VPS
PUBLIC_IP=$(curl -s --max-time 3 https://ifconfig.me || curl -s --max-time 3 https://api.ipify.org || echo "YOUR_VPS_IP")

echo -e "\n${GREEN}================================================================${NC}"
echo -e "${GREEN}   🎉 CÀI ĐẶT & KHỞI CHẠY THÀNH CÔNG AI AGENT WORKSPACE!        ${NC}"
echo -e "${GREEN}================================================================${NC}"
echo -e "🌐 **Giao diện Web:**       ${CYAN}http://${PUBLIC_IP}:${FRONTEND_PORT}${NC}"
echo -e "🔌 **API Swagger Docs:**   ${CYAN}http://${PUBLIC_IP}:${BACKEND_PORT}/docs${NC}"
echo -e "🩺 **Healthcheck:**        ${GREEN}${HEALTH_STATUS}${NC}"
echo -e "🔑 **Local Auth Token:**   ${YELLOW}${LOCAL_AUTH_TOKEN}${NC}"
echo -e "📁 **Thư mục cài đặt:**    ${APP_DIR}"
echo -e "\n${BLUE}Lệnh quản lý dịch vụ:${NC}"
echo -e "  - Xem log Backend:  ${YELLOW}journalctl -u ai-agent-backend -f${NC}"
echo -e "  - Xem log Frontend: ${YELLOW}journalctl -u ai-agent-frontend -f${NC}"
echo -e "  - Khởi động lại:    ${YELLOW}systemctl restart ai-agent-backend ai-agent-frontend${NC}"
echo -e "${GREEN}================================================================${NC}"
