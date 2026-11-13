import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import LibraryPage from "@/app/library/page";

describe("LibraryPage Unit & Integration Tests (Task 5.3)", () => {
  const mockStorage = {
    used_bytes: 125829120, // ~120 MB
    max_bytes: 5368709120, // 5 GB
    percentage: 2.34,
    used_mb: 120.0,
    max_gb: 5.0,
  };

  const mockFiles = [
    {
      id: "f-1",
      name: "banner_hero.png",
      file_path: "workspace/proj-default/2026-11/task-1/banner_hero.png",
      file_type: "image",
      mime_type: "image/png",
      size_bytes: 1048576, // 1 MB
      category: "output",
      project_id: "proj-default",
      created_at: "2026-11-12T10:00:00Z",
    },
    {
      id: "f-2",
      name: "promo_video.mp4",
      file_path: "workspace/proj-default/2026-11/task-2/promo_video.mp4",
      file_type: "video",
      mime_type: "video/mp4",
      size_bytes: 25165824, // 24 MB
      category: "output",
      project_id: "proj-default",
      created_at: "2026-11-12T11:00:00Z",
    },
    {
      id: "f-3",
      name: "report_kpi.pdf",
      file_path: "workspace/proj-finance/2026-11/task-3/report_kpi.pdf",
      file_type: "document",
      mime_type: "application/pdf",
      size_bytes: 524288, // 512 KB
      category: "document",
      project_id: "proj-finance",
      created_at: "2026-11-12T12:00:00Z",
    },
    {
      id: "f-4",
      name: "landing.html",
      file_path: "workspace/proj-default/2026-11/task-4/landing.html",
      file_type: "code",
      mime_type: "text/html",
      size_bytes: 40960, // 40 KB
      category: "output",
      project_id: "proj-default",
      created_at: "2026-11-12T13:00:00Z",
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
  });

  const setupFetchMock = (overrides?: { files?: any[]; storage?: any }) => {
    return vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      if (url.includes("/api/v1/files/storage")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            status: "success",
            data: overrides?.storage ?? mockStorage,
          }),
        });
      }
      if (url.includes("/api/v1/files/export") && init?.method === "POST") {
        return Promise.resolve({
          ok: true,
          status: 200,
          blob: async () => new Blob(["fake-zip-data"], { type: "application/zip" }),
          headers: new Headers({ "content-disposition": "attachment; filename=bundle.zip" }),
        });
      }
      if (url.includes("/api/v1/files/cleanup") && init?.method === "POST") {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            status: "success",
            data: { cleaned_files: 5, freed_bytes: 10485760 },
          }),
        });
      }
      if (url.includes("/api/v1/files/") && init?.method === "DELETE") {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ status: "success", data: { deleted: true } }),
        });
      }
      if (url.includes("/api/v1/files/upload") && init?.method === "POST") {
        return Promise.resolve({
          ok: true,
          status: 201,
          json: async () => ({
            status: "success",
            data: {
              id: "f-new",
              name: "uploaded_doc.pdf",
              file_type: "document",
              size_bytes: 12345,
            },
          }),
        });
      }
      if (url.includes("/api/v1/files")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            status: "success",
            data: overrides?.files ?? mockFiles,
          }),
        });
      }
      return Promise.reject(new Error(`Unhandled URL: ${url}`));
    });
  };

  it("renders storage meter bar, action buttons, and filter tabs", async () => {
    global.fetch = setupFetchMock();

    render(<LibraryPage />);

    // Storage meter bar
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /Thư viện tệp/i })).toBeInTheDocument();
      expect(screen.getByText(/5\.0 GB/i)).toBeInTheDocument();
    });

    // Action buttons
    expect(screen.getByRole("button", { name: /Tải lên/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Dọn dẹp tệp tạm/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Xuất ZIP/i })).toBeInTheDocument();

    // Filter tabs matching Slide 48/50
    expect(screen.getByRole("tab", { name: /Tất cả/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Hình ảnh/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Video & Media/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Tài liệu/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Code & HTML/i })).toBeInTheDocument();

    // Renders mock files
    expect(screen.getByText("banner_hero.png")).toBeInTheDocument();
    expect(screen.getByText("promo_video.mp4")).toBeInTheDocument();
    expect(screen.getByText("report_kpi.pdf")).toBeInTheDocument();
    expect(screen.getByText("landing.html")).toBeInTheDocument();
  });

  it("filters file list when clicking category tab", async () => {
    global.fetch = setupFetchMock();

    render(<LibraryPage />);

    await waitFor(() => {
      expect(screen.getByText("banner_hero.png")).toBeInTheDocument();
    });

    // Click "Hình ảnh"
    fireEvent.click(screen.getByRole("tab", { name: /Hình ảnh/i }));

    expect(screen.getByText("banner_hero.png")).toBeInTheDocument();
    expect(screen.queryByText("promo_video.mp4")).not.toBeInTheDocument();
    expect(screen.queryByText("report_kpi.pdf")).not.toBeInTheDocument();
    expect(screen.queryByText("landing.html")).not.toBeInTheDocument();

    // Click "Video & Media"
    fireEvent.click(screen.getByRole("tab", { name: /Video & Media/i }));
    expect(screen.queryByText("banner_hero.png")).not.toBeInTheDocument();
    expect(screen.getByText("promo_video.mp4")).toBeInTheDocument();
  });

  it("filters file list by search input", async () => {
    global.fetch = setupFetchMock();

    render(<LibraryPage />);

    await waitFor(() => {
      expect(screen.getByText("banner_hero.png")).toBeInTheDocument();
    });

    const searchInput = screen.getByPlaceholderText(/Tìm kiếm tệp/i);
    fireEvent.change(searchInput, { target: { value: "kpi" } });

    expect(screen.getByText("report_kpi.pdf")).toBeInTheDocument();
    expect(screen.queryByText("banner_hero.png")).not.toBeInTheDocument();
    expect(screen.queryByText("promo_video.mp4")).not.toBeInTheDocument();
  });

  it("handles batch export ZIP of selected files", async () => {
    const fetchMock = setupFetchMock();
    global.fetch = fetchMock;

    render(<LibraryPage />);

    await waitFor(() => {
      expect(screen.getByText("banner_hero.png")).toBeInTheDocument();
    });

    // Checkbox for f-1 and f-2
    const checkboxes = screen.getAllByRole("checkbox", { name: /select-file/i });
    expect(checkboxes.length).toBeGreaterThanOrEqual(2);

    fireEvent.click(checkboxes[0]);
    fireEvent.click(checkboxes[1]);

    const exportBtn = screen.getByRole("button", { name: /Xuất ZIP/i });
    expect(exportBtn).not.toBeDisabled();

    fireEvent.click(exportBtn);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/files/export"),
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ file_ids: ["f-1", "f-2"] }),
        })
      );
    });
  });

  it("executes temp files cleanup upon confirmation", async () => {
    const fetchMock = setupFetchMock();
    global.fetch = fetchMock;

    render(<LibraryPage />);

    await waitFor(() => {
      expect(screen.getByText("banner_hero.png")).toBeInTheDocument();
    });

    const cleanupBtn = screen.getByRole("button", { name: /Dọn dẹp tệp tạm/i });
    fireEvent.click(cleanupBtn);

    // Confirm dialog / modal
    const confirmBtn = await screen.findByRole("button", { name: /Xác nhận dọn dẹp/i });
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/files/cleanup"),
        expect.objectContaining({ method: "POST" })
      );
    });
  });
});
