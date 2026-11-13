"use client";

import React, { useState, useEffect, useCallback } from "react";
import {
  Brain,
  FileText,
  Sparkles,
  Package,
  Layers,
  AlertCircle,
  RefreshCw,
} from "lucide-react";
import { SidebarNav } from "@/components/layout/SidebarNav";
import { BrandProfileForm } from "@/components/brain/BrandProfileForm";
import { ProductCatalogTable } from "@/components/brain/ProductCatalogTable";
import { DocumentKnowledgeTab } from "@/components/brain/DocumentKnowledgeTab";
import { defaultApiClient } from "@/lib/apiClient";
import {
  BrandProfile,
  BrandTemplate,
  ProductItem,
  BrainDocumentItem,
  SemanticSearchHit,
  CsvImportResult,
} from "@/lib/types";

type BrainTab = "knowledge" | "brand" | "products";

export default function BrainPage() {
  const [activeTab, setActiveTab] = useState<BrainTab>("knowledge");
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Domain states
  const [brandProfile, setBrandProfile] = useState<BrandProfile | null>(null);
  const [brandTemplates, setBrandTemplates] = useState<BrandTemplate[]>([]);
  const [products, setProducts] = useState<ProductItem[]>([]);
  const [documents, setDocuments] = useState<BrainDocumentItem[]>([]);

  const loadBrainData = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [bpRes, prodList, docList] = await Promise.all([
        defaultApiClient.getBrandProfile().catch(() => null),
        defaultApiClient.getProducts().catch(() => []),
        defaultApiClient.listBrainDocuments().catch(() => []),
      ]);

      if (bpRes) {
        setBrandProfile(bpRes.profile);
        setBrandTemplates(bpRes.templates || []);
      }
      setProducts(prodList || []);
      setDocuments(docList || []);
    } catch (err: any) {
      setError(err?.message || "Không thể tải dữ liệu Brain.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadBrainData();
  }, [loadBrainData]);

  const handleNavigate = (navId: string) => {
    if (typeof window === "undefined") return;
    if (navId === "workspace") window.location.assign("/");
    else if (navId === "office") window.location.assign("/office");
    else if (navId === "board") window.location.assign("/board");
    else if (navId === "brain") window.location.assign("/brain");
  };

  // Document Handlers
  const handleUploadFile = async (file: File, collection?: string) => {
    await defaultApiClient.uploadBrainDocument(file, collection);
    const updated = await defaultApiClient.listBrainDocuments();
    setDocuments(updated);
  };

  const handleDeleteDocument = async (docId: string) => {
    await defaultApiClient.deleteBrainDocument(docId);
    setDocuments((prev) => prev.filter((d) => d.doc_id !== docId));
  };

  const handleSearchTest = async (
    query: string,
    collection: string
  ): Promise<SemanticSearchHit[]> => {
    return defaultApiClient.searchBrain(query, [collection || "default"]);
  };

  // Brand Profile Handlers
  const handleSaveBrandProfile = async (data: Partial<BrandProfile>) => {
    const saved = await defaultApiClient.updateBrandProfile(data);
    setBrandProfile(saved);
  };

  // Product Catalog Handlers
  const handleUpsertProduct = async (data: Partial<ProductItem>) => {
    await defaultApiClient.upsertProduct(data);
    const updated = await defaultApiClient.getProducts();
    setProducts(updated);
  };

  const handleDeleteProduct = async (productId: string) => {
    await defaultApiClient.deleteProduct(productId);
    setProducts((prev) => prev.filter((p) => p.id !== productId));
  };

  const handleImportCsv = async (fileOrContent: File | string): Promise<CsvImportResult> => {
    const res = await defaultApiClient.importProductsCsv(fileOrContent);
    const updated = await defaultApiClient.getProducts();
    setProducts(updated);
    return res;
  };

  return (
    <div className="flex h-screen bg-gray-950 text-gray-100 overflow-hidden">
      {/* Sidebar Navigation */}
      <SidebarNav
        activeNav="brain"
        onNavigate={handleNavigate}
        onNewTask={() => {
          if (typeof window !== "undefined") window.location.assign("/");
        }}
      />

      {/* Main Content Area */}
      <main className="flex-1 flex flex-col h-full overflow-hidden">
        {/* Top Header */}
        <header className="px-8 py-5 border-b border-gray-800 bg-gray-900/60 backdrop-blur-md flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-sky-500/10 border border-sky-500/20 flex items-center justify-center text-sky-400">
              <Brain className="w-5 h-5" />
            </div>
            <div>
              <h1 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
                Brain - Trung tâm Tri thức & Thương hiệu
              </h1>
              <p className="text-xs text-gray-400">
                Kho lưu trữ RAG, hồ sơ nhận diện thương hiệu và danh mục bảng giá sản phẩm tích hợp cho các Tác tử AI.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={loadBrainData}
              disabled={isLoading}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-gray-800 hover:bg-gray-700 border border-gray-700 text-xs text-gray-300 font-medium transition-colors cursor-pointer"
              title="Làm mới dữ liệu"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} />
              <span>Làm mới</span>
            </button>
          </div>
        </header>

        {/* Tab Navigation */}
        <div className="px-8 border-b border-gray-800 bg-gray-900/40">
          <nav className="flex space-x-6 text-sm">
            <button
              type="button"
              onClick={() => setActiveTab("knowledge")}
              className={`py-3.5 px-1 border-b-2 font-medium text-xs flex items-center gap-2 transition-colors cursor-pointer ${
                activeTab === "knowledge"
                  ? "border-sky-500 text-sky-400"
                  : "border-transparent text-gray-400 hover:text-gray-200"
              }`}
            >
              <FileText className="w-4 h-4" />
              <span>Tài liệu & Tri thức</span>
              <span className="ml-1 px-1.5 py-0.2 rounded-full text-[10px] bg-gray-800 text-gray-400 font-mono">
                {documents.length}
              </span>
            </button>

            <button
              type="button"
              onClick={() => setActiveTab("brand")}
              className={`py-3.5 px-1 border-b-2 font-medium text-xs flex items-center gap-2 transition-colors cursor-pointer ${
                activeTab === "brand"
                  ? "border-sky-500 text-sky-400"
                  : "border-transparent text-gray-400 hover:text-gray-200"
              }`}
            >
              <Sparkles className="w-4 h-4" />
              <span>Hồ sơ Thương hiệu</span>
            </button>

            <button
              type="button"
              onClick={() => setActiveTab("products")}
              className={`py-3.5 px-1 border-b-2 font-medium text-xs flex items-center gap-2 transition-colors cursor-pointer ${
                activeTab === "products"
                  ? "border-sky-500 text-sky-400"
                  : "border-transparent text-gray-400 hover:text-gray-200"
              }`}
            >
              <Package className="w-4 h-4" />
              <span>Danh mục Sản phẩm</span>
              <span className="ml-1 px-1.5 py-0.2 rounded-full text-[10px] bg-gray-800 text-gray-400 font-mono">
                {products.length}
              </span>
            </button>
          </nav>
        </div>

        {/* Tab Body */}
        <div className="flex-1 overflow-y-auto p-8">
          {error && (
            <div className="mb-6 p-4 rounded-xl bg-rose-950/40 border border-rose-800/60 flex items-center gap-3 text-xs text-rose-300">
              <AlertCircle className="w-4 h-4 shrink-0 text-rose-400" />
              <span>{error}</span>
            </div>
          )}

          {activeTab === "knowledge" && (
            <DocumentKnowledgeTab
              documents={documents}
              onUploadFile={handleUploadFile}
              onDeleteDocument={handleDeleteDocument}
              onSearchTest={handleSearchTest}
            />
          )}

          {activeTab === "brand" && (
            <BrandProfileForm
              initialProfile={brandProfile || undefined}
              templates={brandTemplates}
              onSave={handleSaveBrandProfile}
            />
          )}

          {activeTab === "products" && (
            <ProductCatalogTable
              products={products}
              onUpsertProduct={handleUpsertProduct}
              onDeleteProduct={handleDeleteProduct}
              onImportCsv={handleImportCsv}
            />
          )}
        </div>
      </main>
    </div>
  );
}
