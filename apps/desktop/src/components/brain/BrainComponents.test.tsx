import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import { BrandProfileForm } from "./BrandProfileForm";
import { ProductCatalogTable } from "./ProductCatalogTable";
import { DocumentKnowledgeTab } from "./DocumentKnowledgeTab";
import BrainPage from "@/app/brain/page";

describe("BrainComponents Unit & Integration Tests", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("BrandProfileForm", () => {
    const mockProfile = {
      id: "bp-1",
      brand_name: "Thương hiệu Mẫu",
      tagline: "Định vị giá trị",
      target_audience: "Doanh nghiệp vừa và nhỏ",
      tone_of_voice: "Chuyên nghiệp, tin cậy",
      brand_colors: ["#0ea5e9", "#1e293b"],
      fonts: ["Inter"],
      legal_boundaries: "Tuân thủ pháp luật.",
      logo_asset_id: null,
    };

    const mockTemplates = [
      {
        id: "coach_educator",
        name: "Chuyên gia / Huấn luyện viên (Coach / Educator)",
        tagline: "Khai mở tiềm năng - Dẫn lối thành công",
        tone_of_voice: "Uyên bác, ân cần, chân thành, truyền cảm hứng.",
        legal_boundaries: "Không cam kết kết quả y tế, không hứa hẹn làm giàu cấp tốc.",
        target_audience: "Người học phát triển kỹ năng",
        brand_colors: ["#0284c7", "#0f172a"],
      },
      {
        id: "ecommerce_retail",
        name: "Thương mại Điện tử / Bán lẻ (E-commerce / Retail)",
        tagline: "Chất lượng đỉnh cao - Giá cả chạm sàn",
        tone_of_voice: "Năng động, trẻ trung, kích thích hành động.",
        legal_boundaries: "Đổi trả 7 ngày, bảo hành chính hãng.",
        target_audience: "Khách hàng mua sắm online",
        brand_colors: ["#f97316", "#ef4444"],
      },
    ];

    it("renders profile fields and allows quick-applying a starter template", async () => {
      const handleSave = vi.fn().mockResolvedValue(true);

      render(
        <BrandProfileForm
          initialProfile={mockProfile}
          templates={mockTemplates}
          onSave={handleSave}
        />
      );

      // Verify fields exist
      expect(screen.getByDisplayValue("Thương hiệu Mẫu")).toBeInTheDocument();
      expect(screen.getByDisplayValue("Định vị giá trị")).toBeInTheDocument();
      expect(screen.getByDisplayValue("Chuyên nghiệp, tin cậy")).toBeInTheDocument();

      // Quick apply template selector
      const templateSelect = screen.getByLabelText(/Mẫu thương hiệu có sẵn|Áp dụng mẫu/i);
      fireEvent.change(templateSelect, { target: { value: "coach_educator" } });

      // Verify template values filled in
      expect(screen.getByDisplayValue("Khai mở tiềm năng - Dẫn lối thành công")).toBeInTheDocument();
      expect(screen.getByDisplayValue(/Uyên bác, ân cần/i)).toBeInTheDocument();

      // Save form
      const saveBtn = screen.getByRole("button", { name: /Lưu hồ sơ|Lưu thay đổi/i });
      fireEvent.click(saveBtn);

      await waitFor(() => {
        expect(handleSave).toHaveBeenCalledWith(
          expect.objectContaining({
            tagline: "Khai mở tiềm năng - Dẫn lối thành công",
          })
        );
      });
    });
  });

  describe("ProductCatalogTable", () => {
    const mockProducts = [
      {
        id: "prod-1",
        sku: "PROD-AI-01",
        name: "Khóa học AI Pro",
        price_vnd: 5000000,
        tier_type: "Course",
        short_desc: "Mô tả khóa học",
        full_desc: "Mô tả chi tiết",
        deliverables: ["12 videos", "Source code"],
        policies: ["Hoàn tiền 7 ngày"],
        faqs: [],
        price_history: [
          { price_vnd: 5000000, recorded_at: "2026-01-01T00:00:00Z", reason: "initial" },
        ],
        is_active: true,
      },
      {
        id: "prod-2",
        sku: "PROD-COACH-02",
        name: "Gói Coaching 1:1 VIP",
        price_vnd: 15000000,
        tier_type: "Coaching",
        short_desc: "Coach cá nhân",
        full_desc: "Chi tiết coach",
        deliverables: ["8 buổi Zoom"],
        policies: [],
        faqs: [],
        price_history: [
          { price_vnd: 18000000, recorded_at: "2026-01-01T00:00:00Z", reason: "initial" },
          { price_vnd: 15000000, recorded_at: "2026-02-01T00:00:00Z", reason: "update" },
        ],
        is_active: false,
      },
    ];

    it("displays formatted VND prices, searches products, and opens price history modal", async () => {
      const handleUpsert = vi.fn().mockResolvedValue(true);
      const handleDelete = vi.fn().mockResolvedValue(true);
      const handleCsvImport = vi.fn().mockResolvedValue({ imported_count: 0, errors: [] });

      render(
        <ProductCatalogTable
          products={mockProducts}
          onUpsertProduct={handleUpsert}
          onDeleteProduct={handleDelete}
          onImportCsv={handleCsvImport}
        />
      );

      // Verify formatted prices
      expect(screen.getByText(/^5\.000\.000/)).toBeInTheDocument();
      expect(screen.getByText(/^15\.000\.000/)).toBeInTheDocument();

      // Search filter
      const searchInput = screen.getByPlaceholderText(/Tìm kiếm SKU hoặc tên/i);
      fireEvent.change(searchInput, { target: { value: "PROD-COACH" } });

      expect(screen.getByText("Gói Coaching 1:1 VIP")).toBeInTheDocument();
      expect(screen.queryByText("Khóa học AI Pro")).not.toBeInTheDocument();

      // Clear search
      fireEvent.change(searchInput, { target: { value: "" } });

      // View price history modal for prod-2
      const historyButtons = screen.getAllByRole("button", { name: /Lịch sử giá|Xem lịch sử/i });
      fireEvent.click(historyButtons[1]);

      await waitFor(() => {
        expect(screen.getByText(/18\.000\.000/)).toBeInTheDocument();
        expect(screen.getByText(/initial/i)).toBeInTheDocument();
        expect(screen.getByText(/update/i)).toBeInTheDocument();
      });
    });

    it("handles CSV import and shows errors when provided", async () => {
      const handleCsvImport = vi.fn().mockResolvedValue({
        imported_count: 2,
        errors: [{ row: 4, sku: "ERR-01", error: "Thiếu tên sản phẩm" }],
      });

      render(
        <ProductCatalogTable
          products={mockProducts}
          onUpsertProduct={vi.fn()}
          onDeleteProduct={vi.fn()}
          onImportCsv={handleCsvImport}
        />
      );

      const importBtn = screen.getByRole("button", { name: /Nhập CSV|Import CSV/i });
      expect(importBtn).toBeInTheDocument();
    });
  });

  describe("DocumentKnowledgeTab", () => {
    const mockDocs = [
      {
        doc_id: "doc-1",
        filename: "ChinhSachHoanTien.pdf",
        collection: "policies",
        chunk_count: 4,
        total_chars: 3500,
        ingested_at: "2026-03-01T10:00:00Z",
      },
    ];

    it("lists documents and supports semantic search tester", async () => {
      const handleUpload = vi.fn().mockResolvedValue(true);
      const handleDelete = vi.fn().mockResolvedValue(true);
      const handleSearch = vi.fn().mockResolvedValue([
        {
          chunk_id: "doc-1_0",
          doc_id: "doc-1",
          doc_title: "ChinhSachHoanTien.pdf",
          collection: "policies",
          text: "Khách hàng được hoàn tiền trong vòng 7 ngày.",
          score: 0.88,
        },
      ]);

      render(
        <DocumentKnowledgeTab
          documents={mockDocs}
          onUploadFile={handleUpload}
          onDeleteDocument={handleDelete}
          onSearchTest={handleSearch}
        />
      );

      expect(screen.getByText("ChinhSachHoanTien.pdf")).toBeInTheDocument();
      expect(screen.getByText(/4 chunks/i)).toBeInTheDocument();

      // Test semantic search box
      const queryInput = screen.getByPlaceholderText(/Thử nghiệm câu hỏi semantic search/i);
      fireEvent.change(queryInput, { target: { value: "Điều kiện hoàn trả tiền" } });

      const searchBtn = screen.getByRole("button", { name: /Thử tìm kiếm|Tìm kiếm/i });
      fireEvent.click(searchBtn);

      await waitFor(() => {
        expect(handleSearch).toHaveBeenCalledWith("Điều kiện hoàn trả tiền", expect.any(String));
        expect(screen.getByText(/Khách hàng được hoàn tiền/i)).toBeInTheDocument();
        expect(screen.getByText(/88%/i)).toBeInTheDocument();
      });
    });
  });

  describe("BrainPage Navigation", () => {
    it("renders navigation tabs and switches content smoothly", async () => {
      global.fetch = vi.fn().mockImplementation((url: string) => {
        if (url.includes("/api/v1/brain/brand-profile")) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              profile: {
                id: "bp-1",
                brand_name: "AI Hub VN",
                tagline: "Tự động hóa thông minh",
                target_audience: "Mọi người",
                tone_of_voice: "Thân thiện",
                brand_colors: ["#0284c7"],
                fonts: ["Inter"],
                legal_boundaries: "",
              },
              templates: [],
            }),
          });
        }
        if (url.includes("/api/v1/brain/products")) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => [],
          });
        }
        if (url.includes("/api/v1/brain/documents")) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => [],
          });
        }
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({}),
        });
      });

      render(<BrainPage />);

      // Verify tab labels
      expect(screen.getByText("Tài liệu & Tri thức")).toBeInTheDocument();
      expect(screen.getByText("Hồ sơ Thương hiệu")).toBeInTheDocument();
      expect(screen.getByText("Danh mục Sản phẩm")).toBeInTheDocument();

      // Switch to Brand Profile tab
      fireEvent.click(screen.getByRole("button", { name: /Hồ sơ Thương hiệu/i }));
      await waitFor(() => {
        expect(screen.getByText(/Hồ sơ Thương hiệu & Phong cách/i)).toBeInTheDocument();
      });

      // Switch to Products tab
      fireEvent.click(screen.getByRole("button", { name: /Danh mục Sản phẩm/i }));
      await waitFor(() => {
        expect(screen.getByText(/Danh mục Sản phẩm & Bảng giá/i)).toBeInTheDocument();
      });
    });
  });
});
