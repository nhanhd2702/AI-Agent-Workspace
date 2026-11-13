# 🌐 Hướng Dẫn Cài Đặt & Chạy AI Agent Workspace Trên VPS

Tài liệu này cung cấp hướng dẫn đầy đủ từ A-Z để triển khai và vận hành hệ thống **AI Agent Workspace (Văn Phòng AI)** trên máy chủ ảo (VPS) hoặc Dedicated Server chạy hệ điều hành Linux (Ubuntu 22.04 / 24.04 LTS hoặc Debian 12).

---

## 🏗️ 1. Kiến Trúc Hệ Thống Trên VPS

```
Người dùng (Trình duyệt máy tính / điện thoại)
             │
             ├──► Cổng 3000: Next.js Frontend (Giao diện Web / Dashboard)
             │
             └──► Cổng 8765: FastAPI Backend Daemon (LangGraph + ChromaDB + SQLite)
                               │
                               ├── SQLite & Checkpoints DB (/opt/ai-agent-workspace/apps/backend/workspace/app.db)
                               ├── ChromaDB Vector Store (/opt/ai-agent-workspace/apps/backend/workspace/chroma)
                               └── File Library & Artifacts Storage
```

- **Frontend:** Next.js 15 App Router biên dịch tĩnh (`output: export`), phục vụ qua Nginx hoặc HTTP server trên cổng `3000`. Tự động nhận diện hostname/IP của VPS để gọi API tới cổng `8765`.
- **Backend:** FastAPI Sidecar chạy ngầm qua Uvicorn trên cổng `8765`, bảo vệ bằng xác thực `X-Local-Auth-Token` và mã hóa dữ liệu nhạy cảm bằng Fernet symmetric key.

---

## ⚡ 2. Cách 1: Cài Đặt Tự Động 1 Dòng Lệnh (Khuyên Dùng)

Script `scripts/deploy_vps.sh` sẽ tự động cập nhật hệ thống, cài đặt Python 3.12, Node.js 20, pnpm, build mã nguồn, cấu hình systemd daemon tự chạy khi khởi động VPS và mở tường lửa.

### Bước 1: SSH vào VPS của bạn
```bash
# Đăng nhập vào VPS với quyền root (hoặc user có sudo)
# Thay 125.253.125.12 bằng IP VPS của bạn; thay cổng nếu dùng cổng SSH tuỳ chỉnh
ssh root@125.253.125.12
# hoặc:
# ssh -p 63379 nhanhd@125.253.125.12
```

### Bước 2: Chạy lệnh cài đặt tự động
```bash
curl -sSL https://raw.githubusercontent.com/nhanhd2702/AI-Agent-Workspace/main/scripts/deploy_vps.sh | sudo bash
```

Hoặc clone repo về và chạy trực tiếp:
```bash
git clone https://github.com/nhanhd2702/AI-Agent-Workspace.git /opt/ai-agent-workspace
cd /opt/ai-agent-workspace
chmod +x scripts/deploy_vps.sh
sudo bash scripts/deploy_vps.sh
```

---

## 🐳 3. Cách 2: Triển Khai Bằng Docker Compose (Nhanh & Cô Lập 100%)

Nếu VPS của bạn đã cài đặt Docker và Docker Compose:

### Bước 1: Clone mã nguồn
```bash
git clone https://github.com/nhanhd2702/AI-Agent-Workspace.git /opt/ai-agent-workspace
cd /opt/ai-agent-workspace
```

### Bước 2: Khởi chạy container
```bash
# Khởi động Backend và Frontend dưới dạng background containers
docker compose up -d --build
```

### Bước 3: Kiểm tra trạng thái
```bash
docker compose ps
docker compose logs -f
```

---

## 🛠️ 4. Cách 3: Cài Đặt Thủ Công Từng Bước

Nếu bạn muốn tự kiểm soát cấu hình từng thành phần:

### Bước 1: Cài đặt các gói phụ thuộc
```bash
sudo apt-get update -y
sudo apt-get install -y git curl wget build-essential python3.12 python3.12-venv python3.12-dev python3-pip ffmpeg ufw
```

Cài đặt Node.js 20 & pnpm:
```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs
sudo npm install -g pnpm
```

### Bước 2: Tải mã nguồn dự án
```bash
sudo git clone https://github.com/nhanhd2702/AI-Agent-Workspace.git /opt/ai-agent-workspace
cd /opt/ai-agent-workspace
```

### Bước 3: Cài đặt và cấu hình Backend
```bash
cd /opt/ai-agent-workspace/apps/backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -e ".[dev]"

# Tạo file .env cho backend
cat <<EOF > .env
WORKSPACE_DIR=/opt/ai-agent-workspace/apps/backend/workspace
BACKEND_PORT=8765
LOCAL_AUTH_TOKEN=dev-local-token
ENCRYPTION_KEY=$(python3.12 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
MAX_WORKSPACE_BYTES=5368709120
EOF
mkdir -p /opt/ai-agent-workspace/apps/backend/workspace
```

### Bước 4: Cài đặt và Build Frontend
```bash
cd /opt/ai-agent-workspace
pnpm install
cd /opt/ai-agent-workspace/apps/desktop
pnpm build
```

### Bước 5: Cấu hình Systemd Services
Tạo service Backend: `/etc/systemd/system/ai-agent-backend.service`:
```ini
[Unit]
Description=AI Agent Workspace Backend
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/ai-agent-workspace/apps/backend
ExecStart=/opt/ai-agent-workspace/apps/backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8765
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

Tạo service Frontend: `/etc/systemd/system/ai-agent-frontend.service`:
```ini
[Unit]
Description=AI Agent Workspace Frontend Web
After=network.target ai-agent-backend.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/ai-agent-workspace/apps/desktop/out
ExecStart=/usr/bin/python3.12 -m http.server 3000 --bind 0.0.0.0
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Kích hoạt và chạy các service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ai-agent-backend.service
sudo systemctl enable --now ai-agent-frontend.service
```

---

## 🛡️ 5. Mở Tường Lửa (UFW Firewall)

Đảm bảo VPS của bạn cho phép truy cập qua các cổng cần thiết:
```bash
sudo ufw allow 3000/tcp comment "AI Agent Web UI"
sudo ufw allow 8765/tcp comment "AI Agent Backend API"
sudo ufw allow 80/tcp comment "HTTP Web"
sudo ufw allow 443/tcp comment "HTTPS Web"
sudo ufw status
```
*(Lưu ý: Nếu nhà cung cấp VPS có Cloud Firewall / Security Group như Viettel IDC, VNPT, AWS, Linode, hãy mở cổng 3000 và 8765 trên Web Console của nhà cung cấp).*

---

## 📊 6. Quản Lý Dịch Vụ & Giám Sát

| Hành động | Lệnh thực thi |
| :--- | :--- |
| **Xem log Backend** | `sudo journalctl -u ai-agent-backend -f` |
| **Xem log Frontend** | `sudo journalctl -u ai-agent-frontend -f` |
| **Khởi động lại toàn bộ** | `sudo systemctl restart ai-agent-backend ai-agent-frontend` |
| **Dừng hệ thống** | `sudo systemctl stop ai-agent-backend ai-agent-frontend` |
| **Kiểm tra trạng thái** | `sudo systemctl status ai-agent-backend ai-agent-frontend` |
| **Kiểm tra Healthcheck API** | `curl http://127.0.0.1:8765/api/v1/health` |

---

## 🔧 7. Xử Lý Sự Cố Thường Gặp (Troubleshooting)

### 1. Trình duyệt không gọi được API từ giao diện Web
- **Nguyên nhân:** Tường lửa chưa mở cổng `8765`, hoặc trình duyệt chặn kết nối `http` không an toàn.
- **Khắc phục:**
  - Kiểm tra `curl http://<IP_VPS>:8765/api/v1/health`. Nếu nhận được JSON `{"status": "ok"}`, kết nối mạng bình thường.
  - Kiểm tra cài đặt CORS trong backend: mã nguồn đã tích hợp sẵn `allow_origin_regex=r"^https?://.*$"` cho phép mọi IP và domain kết nối.

### 2. VPS bị thiếu RAM khi build Next.js (Dưới 2GB RAM)
- Nếu VPS có RAM 1GB hoặc 2GB, quá trình build `pnpm build` có thể bị killed do Out Of Memory (OOM).
- **Khắc phục:** Tạo thêm 2GB - 4GB Swap Memory:
  ```bash
  sudo fallocate -l 4G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
  ```

### 3. Tùy chỉnh Tên miền (Domain) và SSL HTTPS (Let's Encrypt)
Để truy cập qua domain đẹp như `https://ai.yourdomain.com`:
```nginx
# /etc/nginx/sites-available/ai-workspace
server {
    server_name ai.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
```
Kích hoạt SSL miễn phí:
```bash
sudo certbot --nginx -d ai.yourdomain.com
```
