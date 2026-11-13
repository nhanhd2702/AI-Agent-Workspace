"use client";

import React, { useState, useMemo, useRef } from "react";
import {
  Package,
  Plus,
  Upload,
  Search,
  History,
  Edit2,
  Trash2,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  X,
  FileSpreadsheet,
} from "lucide-react";
import { ProductItem, PriceHistoryItem, CsvImportResult, CsvImportError } from "@/lib/types";

export interface ProductCatalogTableProps {
  products: ProductItem[];
  onUpsertProduct: (prod: Partial<ProductItem>) => Promise<any>;
  onDeleteProduct: (productId: string) => Promise<any>;
  onImportCsv: (fileOrContent: File | string) => Promise<CsvImportResult>;
  className?: string;
}

export function ProductCatalogTable({
  products = [],
  onUpsertProduct,
  onDeleteProduct,
  onImportCsv,
  className = "",
}: ProductCatalogTableProps) {
  const [searchTerm, setSearchTerm] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState<"all" | "active" | "inactive">("all");

  // Modals state
  const [editingProduct, setEditingProduct] = useState<Partial<ProductItem> | null>(null);
  const [isEditModalOpen, setIsEditModalOpen] = useState<boolean>(false);
  const [historyProduct, setHistoryProduct] = useState<ProductItem | null>(null);
  const [isHistoryModalOpen, setIsHistoryModalOpen] = useState<boolean>(false);

  // CSV Import State
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [importResult, setImportResult] = useState<CsvImportResult | null>(null);
  const [isImporting, setIsImporting] = useState<boolean>(false);
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);

  // Filtered products list
  const filteredProducts = useMemo(() => {
    return products.filter((prod) => {
      const matchSearch =
        !searchTerm ||
        prod.sku.toLowerCase().includes(searchTerm.toLowerCase()) ||
        prod.name.toLowerCase().includes(searchTerm.toLowerCase());

      const matchStatus =
        statusFilter === "all" ||
        (statusFilter === "active" && prod.is_active !== false) ||
        (statusFilter === "inactive" && prod.is_active === false);

      return matchSearch && matchStatus;
    });
  }, [products, searchTerm, statusFilter]);

  const formatVnd = (price: number): string => {
    return new Intl.NumberFormat("vi-VN").format(price) + " ₫";
  };

  const handleOpenAdd = () => {
    setEditingProduct({
      sku: "",
      name: "",
      price_vnd: 0,
      tier_type: "Tiêu chuẩn",
      short_desc: "",
      full_desc: "",
      deliverables: [],
      policies: [],
      is_active: true,
    });
    setIsEditModalOpen(true);
  };

  const handleOpenEdit = (prod: ProductItem) => {
    setEditingProduct({ ...prod });
    setIsEditModalOpen(true);
  };

  const handleOpenHistory = (prod: ProductItem) => {
    setHistoryProduct(prod);
    setIsHistoryModalOpen(true);
  };

  const handleSaveProduct = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingProduct) return;
    setIsSubmitting(true);
    try {
      await onUpsertProduct(editingProduct);
      setIsEditModalOpen(false);
      setEditingProduct(null);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleCsvFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setIsImporting(true);
    try {
      const res = await onImportCsv(file);
      setImportResult(res);
    } finally {
      setIsImporting(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  };

  return (
    <div className={`bg-gray-900 border border-gray-800 rounded-xl p-6 ${className}`}>
      {/* Top Header & Actions */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-6 border-b border-gray-800 gap-4">
        <div>
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <Package className="w-5 h-5 text-sky-400" />
            Danh mục Sản phẩm & Bảng giá (Product Catalog)
          </h2>
          <p className="text-xs text-gray-400 mt-1">
            Quản lý bảng giá VND, lịch sử biến động giá và đồng bộ tự động tới ChromaDB vector RAG cho tư vấn bán hàng.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleCsvFileChange}
            accept=".csv"
            className="hidden"
          />
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={isImporting}
            className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-gray-800 hover:bg-gray-700 border border-gray-700 text-xs font-medium text-gray-200 transition-colors cursor-pointer disabled:opacity-50"
          >
            <Upload className="w-4 h-4 text-emerald-400" />
            <span>{isImporting ? "Đang nhập..." : "Nhập CSV"}</span>
          </button>

          <button
            type="button"
            onClick={handleOpenAdd}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-sky-500 hover:bg-sky-600 text-xs font-medium text-white transition-colors cursor-pointer shadow-sm"
          >
            <Plus className="w-4 h-4" />
            <span>Thêm sản phẩm</span>
          </button>
        </div>
      </div>

      {/* CSV Import Result Banner */}
      {importResult && (
        <div className="mt-4 p-4 rounded-lg bg-gray-800/80 border border-gray-700 space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-xs font-medium text-emerald-400">
              <CheckCircle2 className="w-4 h-4" />
              <span>Đã nhập thành công {importResult.imported_count} sản phẩm vào bảng giá.</span>
            </div>
            <button
              type="button"
              onClick={() => setImportResult(null)}
              className="text-gray-400 hover:text-gray-200 cursor-pointer"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {importResult.errors.length > 0 && (
            <div className="mt-2 pt-2 border-t border-gray-700/60">
              <div className="flex items-center gap-1.5 text-xs font-medium text-amber-400 mb-2">
                <AlertTriangle className="w-3.5 h-3.5" />
                <span>Phát hiện {importResult.errors.length} dòng lỗi không thể nhập:</span>
              </div>
              <ul className="space-y-1 text-xs text-gray-400 max-h-36 overflow-y-auto">
                {importResult.errors.map((err, i) => (
                  <li key={i} className="flex items-center gap-2 font-mono">
                    <span className="text-gray-500">Dòng {err.row}:</span>
                    {err.sku && <span className="text-sky-400">[{err.sku}]</span>}
                    <span className="text-rose-400">{err.error}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Filter and Search Bar */}
      <div className="mt-6 flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search className="w-4 h-4 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="Tìm kiếm SKU hoặc tên sản phẩm..."
            className="w-full bg-gray-800 border border-gray-700 rounded-lg pl-9 pr-3.5 py-1.5 text-xs text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-sky-500"
          />
        </div>

        <div className="flex items-center gap-1 bg-gray-800/80 p-1 rounded-lg border border-gray-700 text-xs">
          <button
            type="button"
            onClick={() => setStatusFilter("all")}
            className={`px-3 py-1 rounded-md transition-colors cursor-pointer ${
              statusFilter === "all" ? "bg-gray-700 text-white font-medium" : "text-gray-400 hover:text-gray-200"
            }`}
          >
            Tất cả ({products.length})
          </button>
          <button
            type="button"
            onClick={() => setStatusFilter("active")}
            className={`px-3 py-1 rounded-md transition-colors cursor-pointer ${
              statusFilter === "active" ? "bg-gray-700 text-white font-medium" : "text-gray-400 hover:text-gray-200"
            }`}
          >
            Đang bán
          </button>
          <button
            type="button"
            onClick={() => setStatusFilter("inactive")}
            className={`px-3 py-1 rounded-md transition-colors cursor-pointer ${
              statusFilter === "inactive" ? "bg-gray-700 text-white font-medium" : "text-gray-400 hover:text-gray-200"
            }`}
          >
            Ngừng bán
          </button>
        </div>
      </div>

      {/* Products Table */}
      <div className="mt-4 border border-gray-800 rounded-lg overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="bg-gray-800/60 text-gray-400 uppercase tracking-wider font-semibold border-b border-gray-800">
            <tr>
              <th className="px-4 py-3">Mã SKU</th>
              <th className="px-4 py-3">Tên sản phẩm</th>
              <th className="px-4 py-3">Phân loại</th>
              <th className="px-4 py-3">Giá niêm yết</th>
              <th className="px-4 py-3">Trạng thái</th>
              <th className="px-4 py-3 text-right">Thao tác</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800/60 text-gray-200">
            {filteredProducts.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-gray-500 italic">
                  Chưa có sản phẩm nào phù hợp với điều kiện tìm kiếm.
                </td>
              </tr>
            ) : (
              filteredProducts.map((p) => (
                <tr key={p.id} className="hover:bg-gray-800/40 transition-colors">
                  <td className="px-4 py-3 font-mono font-medium text-sky-400 whitespace-nowrap">
                    {p.sku}
                  </td>
                  <td className="px-4 py-3 font-medium text-white max-w-xs truncate">
                    {p.name}
                  </td>
                  <td className="px-4 py-3 text-gray-400 whitespace-nowrap">
                    {p.tier_type || "—"}
                  </td>
                  <td className="px-4 py-3 font-semibold text-emerald-400 whitespace-nowrap">
                    {formatVnd(p.price_vnd)}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    {p.is_active !== false ? (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] bg-emerald-950/60 text-emerald-400 border border-emerald-800/50">
                        <CheckCircle2 className="w-3 h-3" />
                        Đang bán
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] bg-rose-950/60 text-rose-400 border border-rose-800/50">
                        <XCircle className="w-3 h-3" />
                        Ngừng bán
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right whitespace-nowrap space-x-1">
                    <button
                      type="button"
                      onClick={() => handleOpenHistory(p)}
                      className="p-1.5 text-gray-400 hover:text-sky-300 hover:bg-gray-800 rounded transition-colors cursor-pointer"
                      title="Xem lịch sử biến động giá"
                      aria-label="Lịch sử giá"
                    >
                      <History className="w-4 h-4" />
                    </button>
                    <button
                      type="button"
                      onClick={() => handleOpenEdit(p)}
                      className="p-1.5 text-gray-400 hover:text-amber-300 hover:bg-gray-800 rounded transition-colors cursor-pointer"
                      title="Chỉnh sửa sản phẩm"
                      aria-label="Chỉnh sửa"
                    >
                      <Edit2 className="w-4 h-4" />
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        if (confirm(`Bạn có chắc muốn xóa sản phẩm ${p.name}?`)) {
                          onDeleteProduct(p.id);
                        }
                      }}
                      className="p-1.5 text-gray-400 hover:text-rose-400 hover:bg-gray-800 rounded transition-colors cursor-pointer"
                      title="Xóa sản phẩm"
                      aria-label="Xóa"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Add / Edit Product Modal */}
      {isEditModalOpen && editingProduct && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
          <div className="bg-gray-900 border border-gray-800 rounded-xl max-w-lg w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-gray-800">
              <h3 className="text-base font-semibold text-white">
                {editingProduct.id ? "Chỉnh sửa sản phẩm" : "Thêm sản phẩm mới"}
              </h3>
              <button
                type="button"
                onClick={() => setIsEditModalOpen(false)}
                className="text-gray-400 hover:text-gray-200 cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleSaveProduct} className="space-y-4 text-xs">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-gray-300 mb-1">Mã SKU *</label>
                  <input
                    type="text"
                    required
                    value={editingProduct.sku || ""}
                    onChange={(e) => setEditingProduct({ ...editingProduct, sku: e.target.value })}
                    placeholder="PROD-001"
                    className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-gray-100 font-mono focus:ring-1 focus:ring-sky-500"
                  />
                </div>
                <div>
                  <label className="block text-gray-300 mb-1">Giá bán (VND) *</label>
                  <input
                    type="number"
                    min={0}
                    required
                    value={editingProduct.price_vnd ?? 0}
                    onChange={(e) => setEditingProduct({ ...editingProduct, price_vnd: Number(e.target.value) })}
                    placeholder="5000000"
                    className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-gray-100 font-semibold focus:ring-1 focus:ring-sky-500"
                  />
                </div>
              </div>

              <div>
                <label className="block text-gray-300 mb-1">Tên sản phẩm *</label>
                <input
                  type="text"
                  required
                  value={editingProduct.name || ""}
                  onChange={(e) => setEditingProduct({ ...editingProduct, name: e.target.value })}
                  placeholder="Khóa học AI Engineer Thực Chiến"
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-gray-100 focus:ring-1 focus:ring-sky-500"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-gray-300 mb-1">Phân loại (Tier)</label>
                  <input
                    type="text"
                    value={editingProduct.tier_type || ""}
                    onChange={(e) => setEditingProduct({ ...editingProduct, tier_type: e.target.value })}
                    placeholder="Course / Coaching / SaaS"
                    className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-gray-100 focus:ring-1 focus:ring-sky-500"
                  />
                </div>
                <div className="flex items-center pt-5">
                  <label className="flex items-center gap-2 cursor-pointer text-gray-300">
                    <input
                      type="checkbox"
                      checked={editingProduct.is_active !== false}
                      onChange={(e) => setEditingProduct({ ...editingProduct, is_active: e.target.checked })}
                      className="rounded bg-gray-800 border-gray-700 text-sky-500 focus:ring-0"
                    />
                    <span>Đang hoạt động (Mở bán)</span>
                  </label>
                </div>
              </div>

              <div>
                <label className="block text-gray-300 mb-1">Mô tả ngắn</label>
                <input
                  type="text"
                  value={editingProduct.short_desc || ""}
                  onChange={(e) => setEditingProduct({ ...editingProduct, short_desc: e.target.value })}
                  placeholder="Tóm tắt ngắn gọn 1-2 câu"
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-gray-100 focus:ring-1 focus:ring-sky-500"
                />
              </div>

              <div>
                <label className="block text-gray-300 mb-1">Mô tả chi tiết</label>
                <textarea
                  rows={3}
                  value={editingProduct.full_desc || ""}
                  onChange={(e) => setEditingProduct({ ...editingProduct, full_desc: e.target.value })}
                  placeholder="Nội dung khóa học, tính năng dịch vụ..."
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-gray-100 focus:ring-1 focus:ring-sky-500"
                />
              </div>

              <div className="pt-3 border-t border-gray-800 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setIsEditModalOpen(false)}
                  className="px-4 py-2 rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-300 font-medium cursor-pointer"
                >
                  Hủy
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="px-5 py-2 rounded-lg bg-sky-500 hover:bg-sky-600 disabled:opacity-50 text-white font-medium cursor-pointer"
                >
                  {isSubmitting ? "Đang lưu..." : "Lưu sản phẩm"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Price History Modal */}
      {isHistoryModalOpen && historyProduct && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
          <div className="bg-gray-900 border border-gray-800 rounded-xl max-w-md w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-gray-800">
              <div>
                <h3 className="text-base font-semibold text-white flex items-center gap-2">
                  <History className="w-4 h-4 text-sky-400" />
                  Lịch sử biến động giá
                </h3>
                <p className="text-xs text-gray-400 font-mono mt-0.5">
                  {historyProduct.sku} - {historyProduct.name}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setIsHistoryModalOpen(false)}
                className="text-gray-400 hover:text-gray-200 cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="space-y-3 max-h-64 overflow-y-auto">
              {(!historyProduct.price_history || historyProduct.price_history.length === 0) ? (
                <div className="text-xs text-gray-500 italic text-center py-4">
                  Chưa có lịch sử thay đổi giá.
                </div>
              ) : (
                <div className="border border-gray-800 rounded-lg overflow-hidden">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-gray-800/80 text-gray-400 font-medium border-b border-gray-800">
                      <tr>
                        <th className="px-3 py-2">Thời gian</th>
                        <th className="px-3 py-2">Giá niêm yết</th>
                        <th className="px-3 py-2">Lý do</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-800/60 text-gray-200">
                      {historyProduct.price_history.map((h, i) => (
                        <tr key={i} className="hover:bg-gray-800/30">
                          <td className="px-3 py-2 text-gray-400 font-mono text-[11px]">
                            {new Date(h.recorded_at).toLocaleString("vi-VN")}
                          </td>
                          <td className="px-3 py-2 font-semibold text-emerald-400">
                            {formatVnd(h.price_vnd)}
                          </td>
                          <td className="px-3 py-2">
                            <span
                              className={`px-2 py-0.5 rounded text-[10px] font-mono ${
                                h.reason === "initial"
                                  ? "bg-sky-950/60 text-sky-400 border border-sky-800/50"
                                  : "bg-amber-950/60 text-amber-400 border border-amber-800/50"
                              }`}
                            >
                              {h.reason}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <div className="pt-3 border-t border-gray-800 flex justify-end">
              <button
                type="button"
                onClick={() => setIsHistoryModalOpen(false)}
                className="px-4 py-1.5 rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-300 text-xs font-medium cursor-pointer"
              >
                Đóng
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
