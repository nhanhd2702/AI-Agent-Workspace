"use client";

import React, { useState } from "react";
import {
  FileText,
  Upload,
  Search,
  Trash2,
  Database,
  Layers,
  CheckCircle2,
  AlertCircle,
  FileCode,
  FileSpreadsheet,
} from "lucide-react";
import { BrainDocumentItem, SemanticSearchHit } from "@/lib/types";

export interface DocumentKnowledgeTabProps {
  documents: BrainDocumentItem[];
  onUploadFile: (file: File, collection?: string) => Promise<any>;
  onDeleteDocument: (docId: string) => Promise<any>;
  onSearchTest: (query: string, collection: string) => Promise<SemanticSearchHit[]>;
  className?: string;
}

export function DocumentKnowledgeTab({
  documents = [],
  onUploadFile,
  onDeleteDocument,
  onSearchTest,
  className = "",
}: DocumentKnowledgeTabProps) {
  // Upload State
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [targetCollection, setTargetCollection] = useState<string>("default");
  const [isUploading, setIsUploading] = useState<boolean>(false);
  const [uploadStatus, setUploadStatus] = useState<{ success?: string; error?: string } | null>(null);

  // Search Tester State
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [searchCollection, setSearchCollection] = useState<string>("default");
  const [isSearching, setIsSearching] = useState<boolean>(false);
  const [searchResults, setSearchResults] = useState<SemanticSearchHit[] | null>(null);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      setSelectedFile(file);
      setUploadStatus(null);
    }
  };

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedFile) return;
    setIsUploading(true);
    setUploadStatus(null);
    try {
      await onUploadFile(selectedFile, targetCollection || "default");
      setUploadStatus({ success: `Đã nạp thành công ${selectedFile.name} vào kho tri thức!` });
      setSelectedFile(null);
    } catch (err: any) {
      setUploadStatus({ error: err?.message || "Tải tài liệu thất bại" });
    } finally {
      setIsUploading(false);
    }
  };

  const handleRunSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchQuery.trim()) return;
    setIsSearching(true);
    try {
      const hits = await onSearchTest(searchQuery.trim(), searchCollection || "default");
      setSearchResults(hits || []);
    } finally {
      setIsSearching(false);
    }
  };

  const getFileIcon = (filename: string) => {
    const lower = filename.toLowerCase();
    if (lower.endsWith(".csv")) return <FileSpreadsheet className="w-4 h-4 text-emerald-400" />;
    if (lower.endsWith(".md") || lower.endsWith(".txt")) return <FileCode className="w-4 h-4 text-sky-400" />;
    return <FileText className="w-4 h-4 text-amber-400" />;
  };

  return (
    <div className={`space-y-6 ${className}`}>
      {/* Upload Section */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
        <div className="pb-4 border-b border-gray-800">
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <Database className="w-5 h-5 text-sky-400" />
            Nạp Tài liệu & Cơ sở Tri thức (Document Ingestion)
          </h2>
          <p className="text-xs text-gray-400 mt-1">
            Hỗ trợ .pdf (văn bản trích xuất được), .docx, .txt, .md, .csv. Tự động băm vector và lưu trữ vào ChromaDB.
          </p>
        </div>

        <form onSubmit={handleUpload} className="mt-4 flex flex-col sm:flex-row items-stretch sm:items-end gap-3 text-xs">
          <div className="flex-1">
            <label className="block text-gray-300 font-medium mb-1.5">Chọn tệp tài liệu</label>
            <input
              type="file"
              accept=".pdf,.docx,.txt,.md,.csv"
              onChange={handleFileSelect}
              className="w-full text-xs text-gray-300 file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:text-xs file:font-medium file:bg-gray-800 file:text-sky-400 hover:file:bg-gray-700 cursor-pointer bg-gray-800/60 border border-gray-700 rounded-lg p-1.5"
            />
          </div>

          <div className="w-full sm:w-48">
            <label className="block text-gray-300 font-medium mb-1.5">Bộ sưu tập (Collection)</label>
            <input
              type="text"
              value={targetCollection}
              onChange={(e) => setTargetCollection(e.target.value)}
              placeholder="default / policies / faq"
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-gray-100 placeholder-gray-500 font-mono focus:ring-1 focus:ring-sky-500"
            />
          </div>

          <button
            type="submit"
            disabled={!selectedFile || isUploading}
            className="flex items-center justify-center gap-2 px-5 py-2.5 rounded-lg bg-sky-500 hover:bg-sky-600 disabled:opacity-50 text-white font-medium transition-colors cursor-pointer shadow-sm shrink-0"
          >
            <Upload className="w-4 h-4" />
            <span>{isUploading ? "Đang nạp..." : "Nạp tri thức"}</span>
          </button>
        </form>

        {uploadStatus?.success && (
          <div className="mt-3 flex items-center gap-2 text-xs text-emerald-400">
            <CheckCircle2 className="w-4 h-4 shrink-0" />
            <span>{uploadStatus.success}</span>
          </div>
        )}
        {uploadStatus?.error && (
          <div className="mt-3 flex items-center gap-2 text-xs text-rose-400">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{uploadStatus.error}</span>
          </div>
        )}
      </div>

      {/* Document List Table */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
        <div className="flex items-center justify-between pb-4 border-b border-gray-800">
          <div>
            <h3 className="text-base font-semibold text-white flex items-center gap-2">
              <Layers className="w-4 h-4 text-purple-400" />
              Tài liệu đã được đánh chỉ mục ({documents.length})
            </h3>
            <p className="text-xs text-gray-400 mt-0.5">Danh sách các tệp đã phân mảnh và index vào ChromaDB.</p>
          </div>
        </div>

        <div className="mt-4 border border-gray-800 rounded-lg overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-gray-800/60 text-gray-400 uppercase tracking-wider font-semibold border-b border-gray-800">
              <tr>
                <th className="px-4 py-3">Tên tài liệu</th>
                <th className="px-4 py-3">Bộ sưu tập</th>
                <th className="px-4 py-3">Phân mảnh</th>
                <th className="px-4 py-3">Kích thước</th>
                <th className="px-4 py-3 text-right">Thao tác</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800/60 text-gray-200">
              {documents.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-gray-500 italic">
                    Chưa có tài liệu nào được nạp vào kho tri thức.
                  </td>
                </tr>
              ) : (
                documents.map((doc) => (
                  <tr key={doc.doc_id} className="hover:bg-gray-800/40 transition-colors">
                    <td className="px-4 py-3 font-medium text-white flex items-center gap-2">
                      {getFileIcon(doc.filename)}
                      <span className="truncate max-w-sm">{doc.filename}</span>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <span className="px-2 py-0.5 rounded text-[11px] font-mono bg-purple-950/60 text-purple-300 border border-purple-800/50">
                        {doc.collection}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-300 whitespace-nowrap font-mono">
                      {doc.chunk_count} chunks
                    </td>
                    <td className="px-4 py-3 text-gray-400 whitespace-nowrap">
                      {doc.total_chars ? `${doc.total_chars.toLocaleString("vi-VN")} ký tự` : "—"}
                    </td>
                    <td className="px-4 py-3 text-right whitespace-nowrap">
                      <button
                        type="button"
                        onClick={() => {
                          if (confirm(`Bạn có chắc muốn xóa tài liệu ${doc.filename}?`)) {
                            onDeleteDocument(doc.doc_id);
                          }
                        }}
                        className="p-1.5 text-gray-400 hover:text-rose-400 hover:bg-gray-800 rounded transition-colors cursor-pointer"
                        title="Xóa tài liệu và vector chunks"
                        aria-label={`Xóa tài liệu ${doc.filename}`}
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
      </div>

      {/* Semantic Search Tester */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
        <div className="pb-4 border-b border-gray-800">
          <h3 className="text-base font-semibold text-white flex items-center gap-2">
            <Search className="w-4 h-4 text-emerald-400" />
            Trình thử nghiệm Semantic Search (Vector RAG Tester)
          </h3>
          <p className="text-xs text-gray-400 mt-0.5">
            Mô phỏng truy vấn ngữ nghĩa tương tự cách các Tác tử AI trích xuất tri thức khi soạn thảo hoặc tư vấn.
          </p>
        </div>

        <form onSubmit={handleRunSearch} className="mt-4 flex flex-col sm:flex-row items-stretch sm:items-center gap-3 text-xs">
          <div className="w-full sm:w-44">
            <label className="block text-gray-400 mb-1">Collection</label>
            <input
              type="text"
              value={searchCollection}
              onChange={(e) => setSearchCollection(e.target.value)}
              placeholder="default"
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-gray-100 font-mono focus:ring-1 focus:ring-sky-500"
            />
          </div>

          <div className="flex-1">
            <label className="block text-gray-400 mb-1">Câu hỏi hoặc từ khóa ngữ nghĩa</label>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Thử nghiệm câu hỏi semantic search (ví dụ: Chính sách hoàn tiền khóa học...)"
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3.5 py-2 text-gray-100 placeholder-gray-500 focus:ring-1 focus:ring-sky-500"
            />
          </div>

          <div className="pt-5">
            <button
              type="submit"
              disabled={isSearching || !searchQuery.trim()}
              className="flex items-center justify-center gap-2 px-5 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white font-medium transition-colors cursor-pointer shadow-sm w-full sm:w-auto"
            >
              <Search className="w-4 h-4" />
              <span>{isSearching ? "Đang dò..." : "Thử tìm kiếm"}</span>
            </button>
          </div>
        </form>

        {/* Search Results Display */}
        {searchResults !== null && (
          <div className="mt-5 space-y-3">
            <div className="text-xs text-gray-400 font-medium">
              Tìm thấy {searchResults.length} kết quả phù hợp (độ tương đồng ≥ 70%):
            </div>

            {searchResults.length === 0 ? (
              <div className="p-4 rounded-lg bg-gray-800/40 border border-gray-800 text-xs text-gray-500 italic text-center">
                Không tìm thấy phân mảnh tri thức nào khớp với câu hỏi trên ngưỡng tương đồng tối thiểu.
              </div>
            ) : (
              <div className="space-y-3 max-h-96 overflow-y-auto">
                {searchResults.map((hit) => {
                  const percent = Math.round(hit.score * 100);
                  return (
                    <div
                      key={hit.chunk_id}
                      className="p-4 rounded-lg bg-gray-800/60 border border-gray-700/60 space-y-2 text-xs"
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-semibold text-sky-300 flex items-center gap-1.5">
                          <FileText className="w-3.5 h-3.5 text-sky-400" />
                          {hit.doc_title}
                          {hit.page !== null && hit.page !== undefined && (
                            <span className="text-[11px] text-gray-400 font-normal">
                              (Trang {hit.page})
                            </span>
                          )}
                        </span>
                        <span className="px-2 py-0.5 rounded text-[11px] font-mono font-medium bg-emerald-950/80 text-emerald-300 border border-emerald-800/60">
                          {percent}%
                        </span>
                      </div>
                      <p className="text-gray-300 leading-relaxed font-mono whitespace-pre-wrap bg-gray-900/60 p-2.5 rounded border border-gray-800">
                        {hit.text}
                      </p>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
