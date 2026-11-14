# Phase 2: Mô Hình Văn Phòng Ảo 3D Isometric (/office) — Implementation Plan

> **Mục tiêu:** Xây dựng hoàn chỉnh trang Văn phòng AI ảo 3D Isometric (`/office`) với 22 Chibi AI Agents, 4 Pods (`Đội Content`, `Đội Funnels`, `Phòng nghỉ sofa tím`, `Khu trung tâm`), Dải KPI Ribbon trên cùng, Bảng sự kiện `Vừa làm gì` (Activity Feed), và Modal tương tác chi tiết Agent (`[Dùng]` & `[Cấu hình]`).

---

## Danh Sách Tasks Chi Tiết

### Task 2.1: Bổ Sung Đủ 22 Chibi Agents & 4 Pods Chuẩn TAKO (`Office3DCanvas.tsx`)
- Cấu hình 22 Agent Visuals với tọa độ grid isometric chính xác:
  - **Trung tâm (Tổng bộ):** `Người điều phối` (Headphones xanh dương).
  - **Pod 1 (Đội Content - góc trên phải):** `ContentWriter`, `HookMaster`, `Copywriter`, `Storyteller`, `BlogExpert`, `EmailSpecialist`, `SEOStrategist`.
  - **Pod 2 (Đội Funnels - góc dưới phải):** `FunnelsAgent`, `OfferCreator`, `VslWriter`, `LandingPageDesigner`, `AdCopywriter`, `LeadMagnetMaker`.
  - **Pod 3 (Phòng nghỉ Sofa tím - góc dưới trái):** Sofa tím dài, cây xanh, khu thư giãn cho Agent nghỉ (`WorkflowAutomator`, `DataAnalyst`, `CodeArchitect`, `ImageStudio`).
  - **Pod 4 (Khu mở trung tâm):** `DeepResearcher`, `UIDesigner`, `VideoEditor`, `CSKH`, `SalesAgent`, `ReportAgent`.
- Vẽ đồ họa Sofa tím (`Purple Lounge Sofa`), bàn làm việc, màn hình phát sáng neon, bong bóng thoại task.
- Viết test `tests/Office3DCanvasTako.test.tsx`:
  - Test render 22 agents visual data.
  - Test chọn agent mở modal callback `onSelectAgent`.
  - Test các nút điều khiển zoom, pan, reset góc nhìn `↻`.

### Task 2.2: Modal Chi Tiết Tác Tử (`AgentDetailModal.tsx`)
- Hiển thị khi click vào bất kỳ Agent nào trong 3D hoặc 2D view.
- Hiển thị:
  - Avatar Chibi đặc trưng theo phụ kiện.
  - Tên định danh (`@ContentWriter`), Tên hiển thị (`Trần Viết Văn`), Vai trò chuyên môn.
  - Danh sách Kỹ năng (`Skills`).
  - Model đang dùng (`GPT-6 Luna`, `Claude 3.7 Sonnet`, `⚡ Antigravity CLI`).
  - Nút `Dùng agent này` (chuyển sang `/` với agent được chọn trong Omnibar).
  - Nút `Cấu hình agent`.
- Viết test `tests/AgentDetailModal.test.tsx`.

### Task 2.3: Dải KPI Ribbon & Bảng Hoạt Động "Vừa Làm Gì" (`OfficeActivityFeed.tsx`, `OfficeKpiRibbon.tsx`)
- `OfficeKpiRibbon.tsx`:
  - Thẻ `Token hôm nay` (561K), `Đang làm` (2), `Chờ anh` (1 - cam cảnh báo), `Việc xong hôm nay` (8).
  - Bong bóng thoại của Người điều phối: thông báo trạng thái tổng quan.
- `OfficeActivityFeed.tsx`:
  - Cột bên phải (rộng 320px) ghi lại dòng thời gian các hoạt động: `[Nhận việc]`, `[Đang chạy]`, `[Bàn giao]`, `[Xong]`.
  - Deliverable cards: bấm `[Mở]` nhúng preview `HtmlSandboxViewer` hoặc `MarkdownViewer`.
- Viết test `tests/OfficeActivityFeed.test.tsx`.

### Task 2.4: Tích Hợp Toàn Diện Trang `/office` (`apps/desktop/src/app/office/page.tsx`)
- Tích hợp `SidebarNav` (Cột 1).
- Tích hợp `OfficeKpiRibbon`, `Office3DCanvas`, toggle tab `3D / 2D`, và `OfficeActivityFeed` (Cột bên phải).
- Mở `AgentDetailModal` khi bấm vào nhân vật.
- Kiểm thử toàn diện test suite (`npx vitest run`) và build production (`next build`).
