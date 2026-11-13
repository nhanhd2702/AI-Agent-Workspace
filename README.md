# AI Agent Workspace (Văn Phòng AI) 🏢🤖

Hệ thống ứng dụng Desktop và Sidecar điều phối Đa tác tử tự hành (Autonomous Multi-Agent Workspace) cho doanh nghiệp, nội dung số, kinh doanh và tự động hóa quy trình.

[![Tests](https://img.shields.io/badge/tests-664%20passed-brightgreen.svg)]()
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg?logo=fastapi&logoColor=white)]()
[![Next.js](https://img.shields.io/badge/Next.js-15.1-black.svg?logo=next.js&logoColor=white)]()
[![Tauri](https://img.shields.io/badge/Tauri-v2-FFC131.svg?logo=tauri&logoColor=white)]()
[![License](https://img.shields.io/badge/license-MIT-blue.svg)]()

---

## 🌟 Tính Năng Nổi Bật

1. **Tổng hành dinh tác tử (Master Commander & NLP Intent Parser):**
   - Phân tích yêu cầu ngôn ngữ tự nhiên thành đồ thị công việc (DAG) thông qua LangGraph FSM.
   - Hỗ trợ `@mention` tác tử cụ thể hoặc tự động định tuyến (LLM Router).
2. **Đội ngũ Tác tử chuyên môn hóa (Autonomous Agents):**
   - **Nội dung & Nghiên cứu:** `DeepResearcher`, `ContentWriter`, `ImageStudio`, `VideoEditor` (kèm Pacing Linter).
   - **Kinh doanh & Tăng trưởng:** `FunnelsAgent`, `GrowthAdvisor`, `UIDesigner` (sinh Landing Page HTML offline không CDN).
   - **Bán hàng & Chăm sóc khách hàng:** `SalesAgent`, `SupportAgent` được neo dữ liệu RAG (ChromaDB) từ tài liệu doanh nghiệp.
3. **Cơ chế HIL (Human-in-the-Loop) Review Gates:**
   - Trọng tài con người phê duyệt, từ chối hoặc góp ý chỉnh sửa cho các sản phẩm quan trọng trước khi hoàn thành.
4. **Hộp thư hợp nhất đa kênh ("Tôi Trả Lời" Inbox):**
   - Tích hợp Zalo/Telegram Bridge, cơ chế chuyển giao tức thì giữa AI và người thật (Takeover).
5. **Kho tri thức & Sản phẩm (Brain Module):**
   - Nạp tài liệu PDF, DOCX, TXT, Web URL; nhúng ngữ nghĩa qua ChromaDB.
   - Quản lý Brand Profile và Catalog sản phẩm có chống injection CSV và lịch sử biến động giá.
6. **Bảo mật & Giám sát chi phí:**
   - Mã hóa đối xứng Fernet cho toàn bộ API Keys tại local (`AES-128-CBC`).
   - Dashboard đo lường Tokens, chi phí ước tính, xuất báo cáo chuẩn RFC 4180 CSV.
7. **Kiến trúc Desktop Native & Sidecar:**
   - Giao diện Next.js 15 App Router + React 19 + Tailwind CSS nhúng trong Tauri v2.
   - Backend FastAPI đóng vai trò sidecar daemon chạy ngầm an toàn qua token xác thực loopback nội bộ.

---

## 🛠️ Yêu Cầu Môi Trường (Prerequisites)

- **Node.js:** `>= 20.x`
- **pnpm:** `>= 9.x`
- **Python:** `>= 3.12`
- **Rust / Cargo:** (Tuỳ chọn: chỉ cần khi build Native Tauri Desktop App)

---

## 🚀 Cài Đặt & Chạy Thử Trên Local

### 1. Khởi động Backend (FastAPI Sidecar)

Mở một cửa sổ Terminal:
```bash
# Di chuyển vào thư mục backend
cd apps/backend

# Tạo và kích hoạt môi trường ảo Python
python -m venv .venv

# Trên Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
# Trên macOS / Linux:
# source .venv/bin/activate

# Cài đặt thư viện dependencies (bao gồm test suite)
pip install -e ".[dev]"

# Khởi chạy server API Backend
uvicorn app.main:app --host 127.0.0.1 --port 8765 --reload
```
- **API Docs (Swagger UI):** [http://127.0.0.1:8765/docs](http://127.0.0.1:8765/docs)
- **Health Check:** [http://127.0.0.1:8765/health](http://127.0.0.1:8765/health)

---

### 2. Khởi động Frontend (Next.js Web / Desktop UI)

Mở một cửa sổ Terminal thứ hai tại thư mục gốc của dự án:
```bash
# Cài đặt dependencies cho monorepo
pnpm install

# Khởi chạy giao diện Next.js Web
pnpm --filter desktop dev
```
- Mở trình duyệt và truy cập: [http://localhost:3000](http://localhost:3000)
- Mặc định giao diện sẽ tự động kết nối với Backend daemon tại `http://127.0.0.1:8765` với token xác thực nội bộ `dev-local-token`.

---

### 3. Chạy Toàn Bộ Ứng Dụng Dạng Desktop App (Tauri v2)

Nếu máy tính của bạn đã cài đặt Rust và các công cụ build:
```bash
# Khởi chạy ứng dụng Desktop trực tiếp với Tauri
pnpm --filter desktop tauri dev
```

---

### 4. Triển Khai Trên Máy Chủ VPS / Linux Cloud Server ☁️

Hệ thống hỗ trợ triển khai nhanh chóng lên VPS Ubuntu/Debian với **1 dòng lệnh duy nhất**:

```bash
# Đăng nhập vào VPS và chạy script cài đặt tự động:
curl -sSL https://raw.githubusercontent.com/nhanhd2702/AI-Agent-Workspace/main/scripts/deploy_vps.sh | sudo bash
```

Hoặc triển khai cô lập qua Docker Compose:
```bash
docker compose up -d --build
```
> 📖 Xem hướng dẫn chi tiết toàn tập tại: [docs/VPS_DEPLOYMENT_GUIDE.md](docs/VPS_DEPLOYMENT_GUIDE.md).

---

## 🧪 Chạy Kiểm Thử (Run Tests)

Dự án sở hữu độ bao phủ kiểm thử toàn diện với **664 bài test tự động (100% Green)**.

### Kiểm thử Backend (Pytest):
```bash
# Kích hoạt venv tại apps/backend và chạy:
pytest tests -v

# Hoặc chạy kiểm thử kịch bản tích hợp End-to-End:
pytest tests/test_e2e_workflows.py -v
```
*(Kết quả: 585 tests passed)*

### Kiểm thử Frontend (Vitest & TypeScript):
```bash
# Chạy toàn bộ 17 test suites giao diện:
pnpm --filter desktop test

# Kiểm tra type TypeScript:
pnpm --filter desktop exec tsc --noEmit

# Kiểm tra build sản phẩm:
pnpm --filter desktop build
```
*(Kết quả: 79 tests passed, 0 type errors, 10 static pages compiled clean)*

---

## 📖 Hướng Dẫn Sử Dụng Các Tính Năng

| Đường dẫn trang | Chức năng chính |
| :--- | :--- |
| **`/settings`** | Nhập API Key (OpenAI, Gemini, Anthropic, Ollama); kiểm tra sức khỏe các bộ kết nối (YouTube, Notion, Google Sheets). Toàn bộ key được mã hóa Fernet trên ổ cứng. |
| **`/`** *(Chat)* | Giao diện trò chuyện tổng chỉ huy. Nhập đề bài, xem các Agent trao đổi (handoff), theo dõi stream nhật ký và duyệt các cổng Human-in-the-Loop (HIL). |
| **`/office`** | Sơ đồ văn phòng trực quan xem trạng thái hoạt động theo thời gian thực của từng Agent (IDLE, WORKING, WAITING_APPROVAL, ERROR). |
| **`/board`** | Bảng Kanban phân loại Task theo cột; nhấp vào task để mở Turn Timeline theo dõi từng bước phân tích và tạo artifacts. |
| **`/brain`** | Upload tài liệu doanh nghiệp nạp vào Vector RAG; cấu hình Brand Profile và Bảng giá Catalog sản phẩm. |
| **`/inbox`** | Hộp thư tiếp nhận tin nhắn từ Zalo/Telegram; AI tự trả lời dựa trên RAG hoặc người dùng nhấn nút *"Tôi Trả Lời"* để can thiệp. |
| **`/library`** | Quản lý kho tài nguyên đầu ra (HTML, PNG, kịch bản, báo cáo); xuất trọn gói file `.zip`. Hỗ trợ cảnh báo dung lượng 5GB. |

---

## 📂 Cấu Trúc Dự Án

```
ai-agent-workspace/
├── apps/
│   ├── backend/                 # FastAPI Daemon & LangGraph Orchestrator
│   │   ├── app/
│   │   │   ├── agents/          # Định nghĩa các Agents (Researcher, Writer, Sales, v.v.)
│   │   │   ├── api/             # REST & WebSocket Routers
│   │   │   ├── core/            # FSM, DAG Planner, Dispatcher, Router, HIL Engine
│   │   │   ├── rag/             # ChromaDB vector store & Document Ingestion
│   │   │   ├── services/        # Quản lý file, Catalog, Brand, Monitoring, Connectors
│   │   │   └── models.py        # SQLite Database ORM Models
│   │   └── tests/               # 585 unit, integration & e2e test cases
│   └── desktop/                 # Next.js 15 + React 19 + Tauri v2 Monorepo App
│       ├── src/
│       │   ├── app/             # App Router pages (/, /board, /office, /brain, /inbox, /library, /settings)
│       │   ├── components/      # UI components (Kanban, Sandbox, Chat, Forms, Dashboards)
│       │   └── lib/             # API client, WebSocket sync & Types
│       └── src-tauri/           # Tauri v2 Rust desktop runner & Sidecar Manager
├── scripts/
│   └── build_sidecar.py         # Script đóng gói Backend thành binary standalone
├── package.json
└── pnpm-workspace.yaml
```

---

## 📄 Bản Quyền
Dự án được phát hành dưới giấy phép mã nguồn mở **MIT License**.
