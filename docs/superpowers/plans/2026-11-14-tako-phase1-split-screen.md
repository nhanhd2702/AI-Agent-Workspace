# Phase 1: Giao Diện Không Gian Làm Việc 3 Cột (Split-Screen Workspace) - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Xây dựng hoàn chỉnh giao diện không gian làm việc 3 cột (Split-Screen Workspace) chuẩn theo hệ thống mẫu TAKO / Văn Phòng AI trong 50 ảnh chụp Google Drive (`IMG_1530` - `IMG_1581`): Sidebar navigation chuẩn có avatar Chibi, Omnibar ra lệnh thông minh có popup 6 tab, Action Collapse Box đo ms, và Cột 3 Chi tiết nhiệm vụ (Pipeline & Sandbox Deliverable).

**Architecture:** Bố cục 3 cột chia tách độc lập (Sidebar 260px | Chat & Feed Flex-1 | Task Details & Preview 460px). Sử dụng Tailwind CSS, Lucide icons, React Context / Zustand state management, và WebSocket real-time subscription. Đảm bảo UI/UX Pro Max standards: bảng màu Indigo/Purple/Slate, contrast 4.5:1, animation 150-200ms, không phụ thuộc CDN ngoài.

**Tech Stack:** Next.js 15 (App Router), React 19, TypeScript, Tailwind CSS, Lucide React, Vitest, Testing Library.

**Spec:** [tako_workspace_ba_analysis.md](file:///d:/02_Study_Knowledge/AI/AI%20project/tako_workspace_ba_analysis.md) và [tako_workspace_ba_breakdown.xlsx](file:///d:/02_Study_Knowledge/AI/AI%20project/tako_workspace_ba_breakdown.xlsx).

---

## Global Constraints
- Nền ứng dụng chính: `#F8F9FE` / Card surface: `#FFFFFF` với border `#E2E8F0` và bo góc `rounded-2xl` (16px).
- Tuyệt đối không dùng emoji thay cho icon (dùng SVG Lucide React).
- Mọi nút bấm tương tác phải có `cursor-pointer`, transition 150-200ms, focus outline rõ ràng.
- Giao diện 3 cột phải thích ứng responsive (từ 1280px mở rộng 3 cột đầy đủ, <1024px cho phép ẩn/hiện Cột 3 qua toggle).
- Mọi file code mới phải có unit tests đạt 100% pass với `pnpm --filter desktop test -- --run`.

---

## Review Focus
1. **Omnibar Popup 6 Tab Focus:** Popup mở nổi mượt mà, bấm ra ngoài (click outside) tự đóng, phím Escape đóng, tìm kiếm tức thì lọc danh sách không giật lag.
2. **Action Collapse Box Timing:** Hiển thị chính xác thời gian ms/s từ WebSocket event, định dạng sạch sẽ, mặc định mở 3 bước gần nhất.
3. **Cột 3 Pipeline Synchronization:** Khi nhận event bước mới, tiến trình tự nhảy mốc (`Đang làm` -> `Chờ anh` -> `Đã bàn giao`), không bị mất đồng bộ khi người dùng chuyển qua lại các tab.
4. **Sandbox Deliverable Isolation:** Iframe preview phải có cờ sandbox an toàn, không rò rỉ cookie hoặc chặn thanh cuộn.
5. **Chibi Avatar Asset Consistency:** Lịch sử task và chat card hiển thị đúng avatar Chibi đặc trưng của từng Agent theo chuẩn bảng mẫu.

---

## Tasks

### Task 1.1: Nâng Cấp Sidebar Navigation Chuẩn & Avatar Chibi Lịch Sử Task
- [ ] **Step 1: Viết failing test cho SidebarNav mới**
  - File test: `apps/desktop/tests/SidebarNavTako.test.tsx`
  - Kiểm tra render 5 menu chuẩn: `🏢 Văn phòng AI` (badge việc chờ), `⏱️ Tự động`, `📁 Thư viện`, `🧠 Brain` (badge 1), `💬 Hội thoại khách` (/inbox).
  - Kiểm tra ô tìm kiếm `⌘K` và nút `[+] Tạo task mới`.
  - Kiểm tra render danh sách Tasks lịch sử (Hôm nay, Hôm qua) với avatar Chibi đặc trưng của từng Agent (xanh, tím, lục, mực).
- [ ] **Step 2: Chạy test để xác nhận test fail**
  - Command: `pnpm --filter desktop test -- tests/SidebarNavTako.test.tsx --run`
- [ ] **Step 3: Cập nhật component `SidebarNav.tsx`**
  - File: `apps/desktop/src/components/layout/SidebarNav.tsx`
  - Tạo cấu trúc dữ liệu Chibi avatars SVG / components cho 5 linh vật chính.
  - Tích hợp 5 menu chuẩn theo đường dẫn: `/office`, `/auto`, `/library`, `/brain`, `/inbox`.
  - Hiển thị khối `PROJECTS +` và `TASKS •` phân nhóm Hôm nay / Hôm qua có avatar Chibi và chấm trạng thái.
- [ ] **Step 4: Chạy lại test và xác nhận pass 100%**
  - Command: `pnpm --filter desktop test -- tests/SidebarNavTako.test.tsx --run`
- [ ] **Step 5: Commit code**
  - Commit message: `feat(desktop): upgrade SidebarNav with Tako 5-item menu and chibi agent avatars`

---

### Task 1.2: Xây Dựng Omnibar Ra Lệnh & Popup 6 Tab (`CommanderOmnibar.tsx`)
- [ ] **Step 1: Viết failing test cho CommanderOmnibar**
  - File test: `apps/desktop/tests/CommanderOmnibar.test.tsx`
  - Kiểm tra render input box, icon đính kèm (+, ảnh, màn hình).
  - Kiểm tra click `Gửi tới Người điều phối` mở popup 6 tab (`Agent`, `Đội`, `Skills`, `Connectors`, `Thư viện`, `Trang`).
  - Kiểm tra lọc search `🔍 Tìm kiếm agent...`.
  - Kiểm tra chọn model `GPT-6 Luna v` / `⚡ Antigravity CLI`.
  - Kiểm tra toggle `Rảnh tay`.
- [ ] **Step 2: Chạy test để xác nhận test fail**
  - Command: `pnpm --filter desktop test -- tests/CommanderOmnibar.test.tsx --run`
- [ ] **Step 3: Cài đặt component `CommanderOmnibar.tsx`**
  - File: `apps/desktop/src/components/chat/CommanderOmnibar.tsx`
  - Tạo popup floating với 6 tabs chuẩn theo mẫu `IMG_1540`.
  - Tích hợp chọn Đội (`Đội Content`, `Đội Funnels`, `Chưa vào phòng`).
  - Tích hợp chọn Model (OpenAI, Claude, Antigravity CLI local).
  - Hỗ trợ phím tắt Enter gửi, Shift+Enter xuống dòng, click outside để đóng popup.
- [ ] **Step 4: Chạy lại test và xác nhận pass 100%**
  - Command: `pnpm --filter desktop test -- tests/CommanderOmnibar.test.tsx --run`
- [ ] **Step 5: Commit code**
  - Commit message: `feat(desktop): create CommanderOmnibar with 6-tab destination popup and model selector`

---

### Task 1.3: Xây Dựng Action Collapse Box Đo Milliseconds & Human Decision Card
- [ ] **Step 1: Viết failing test cho ActionCollapseBox và HumanDecisionCard**
  - File test: `apps/desktop/tests/ActionCollapseBox.test.tsx`
  - Kiểm tra render khung "X thao tác" (ví dụ: `8 thao tác`).
  - Kiểm tra hiển thị chi tiết: `Đọc tệp • @skill/... • Hoàn tất • 44ms`.
  - Kiểm tra toggle `Xem thêm N bước`.
  - Kiểm tra render `HumanDecisionCard` với nút `[Đồng ý cho chạy thêm]` và callback khi bấm.
- [ ] **Step 2: Chạy test để xác nhận test fail**
  - Command: `pnpm --filter desktop test -- tests/ActionCollapseBox.test.tsx --run`
- [ ] **Step 3: Cài đặt component `ActionCollapseBox.tsx` & `HumanDecisionCard.tsx`**
  - File: `apps/desktop/src/components/chat/ActionCollapseBox.tsx`
  - File: `apps/desktop/src/components/chat/HumanDecisionCard.tsx`
  - Thiết kế accordion thu gọn/mở rộng với hiệu ứng mượt mà (150ms ease).
  - Định dạng thời gian latency chuẩn: `<1000ms` hiển thị `Xms`, `>1000ms` hiển thị `X.Xs`.
  - Card quyết định nổi bật theo mẫu `IMG_1551` với các lựa chọn chi phí credits và nút 1-click.
- [ ] **Step 4: Chạy lại test và xác nhận pass 100%**
  - Command: `pnpm --filter desktop test -- tests/ActionCollapseBox.test.tsx --run`
- [ ] **Step 5: Commit code**
  - Commit message: `feat(desktop): implement ActionCollapseBox with execution latency and HumanDecisionCard`

---

### Task 1.4: Xây Dựng Cột 3 - Bảng Chi Tiết Nhiệm Vụ & Live Preview (`TaskDetailsPanel.tsx`)
- [ ] **Step 1: Viết failing test cho TaskDetailsPanel**
  - File test: `apps/desktop/tests/TaskDetailsPanel.test.tsx`
  - Kiểm tra render 3 tab: `Việc` | `Tệp (N)` | `Trình duyệt (M)`.
  - Kiểm tra thanh tiến trình 5 mốc (`Đang làm` -> `Chờ anh` -> `Đã bàn giao`...).
  - Kiểm tra danh sách `DÒNG CÔNG VIỆC` (Pipeline các bước B1, B2, B3).
  - Kiểm tra mục `BÀN GIAO` và nút `[Mở]` xem Sandbox.
- [ ] **Step 2: Chạy test để xác nhận test fail**
  - Command: `pnpm --filter desktop test -- tests/TaskDetailsPanel.test.tsx --run`
- [ ] **Step 3: Cài đặt component `TaskDetailsPanel.tsx`**
  - File: `apps/desktop/src/components/chat/TaskDetailsPanel.tsx`
  - Tạo giao diện chuẩn cột 3 theo các ảnh chụp thực tế `IMG_1533`, `IMG_1550`, `IMG_1570`.
  - Tích hợp tab `Trình duyệt` mô phỏng viewport Chromium.
  - Tích hợp khung `ArtifactSandboxViewer` render file HTML hoặc Markdown bàn giao.
- [ ] **Step 4: Chạy lại test và xác nhận pass 100%**
  - Command: `pnpm --filter desktop test -- tests/TaskDetailsPanel.test.tsx --run`
- [ ] **Step 5: Commit code**
  - Commit message: `feat(desktop): build TaskDetailsPanel with 5-stage progress, workflow pipeline, and artifact preview`

---

### Task 1.5: Tích Hợp Toàn Bộ Giao Diện 3 Cột Vào Trang Chủ (`apps/desktop/src/app/page.tsx`)
- [ ] **Step 1: Viết failing test tích hợp cho toàn bộ trang chủ 3 cột**
  - File test: `apps/desktop/tests/TakoWorkspacePage.test.tsx`
  - Kiểm tra phối hợp 3 cột trên cùng 1 trang: Sidebar (Cột 1) + Feed & Omnibar (Cột 2) + Task Details (Cột 3).
  - Kiểm tra luồng gửi câu lệnh -> hiển thị kế hoạch Người điều phối -> cập nhật Pipeline Cột 3 -> hoàn thành bàn giao.
- [ ] **Step 2: Chạy test để xác nhận test fail**
  - Command: `pnpm --filter desktop test -- tests/TakoWorkspacePage.test.tsx --run`
- [ ] **Step 3: Cập nhật `apps/desktop/src/app/page.tsx`**
  - Tích hợp `SidebarNav`, `CommanderOmnibar`, `ActionCollapseBox`, `HumanDecisionCard`, và `TaskDetailsPanel`.
  - Kết nối WebSocket streaming real-time để nạp dữ liệu vào cả 3 cột mà không xung đột state.
  - Thêm nút thu gọn/mở rộng Cột 3 cho màn hình nhỏ.
- [ ] **Step 4: Chạy toàn bộ test suite của desktop**
  - Command: `pnpm --filter desktop test -- --run`
  - Đảm bảo 100% test suites pass.
- [ ] **Step 5: Build và kiểm tra production build**
  - Command: `pnpm --filter desktop build`
  - Đảm bảo code export tĩnh không lỗi.
- [ ] **Step 6: Commit code**
  - Commit message: `feat(desktop): integrate full 3-column split-screen workspace on home page`
