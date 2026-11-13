"use client";

import React, { useState, useEffect } from "react";
import { Sparkles, Save, CheckCircle2, Plus, X, ShieldAlert, Palette, Type } from "lucide-react";
import { BrandProfile, BrandTemplate } from "@/lib/types";

export interface BrandProfileFormProps {
  initialProfile?: Partial<BrandProfile>;
  templates?: BrandTemplate[];
  onSave?: (profile: Partial<BrandProfile>) => Promise<any>;
  className?: string;
}

export function BrandProfileForm({
  initialProfile,
  templates = [],
  onSave,
  className = "",
}: BrandProfileFormProps) {
  const [formData, setFormData] = useState<Partial<BrandProfile>>({
    brand_name: "",
    tagline: "",
    target_audience: "",
    tone_of_voice: "",
    legal_boundaries: "",
    brand_colors: ["#0ea5e9", "#1e293b"],
    fonts: ["Inter"],
    ...initialProfile,
  });

  const [selectedTemplateId, setSelectedTemplateId] = useState<string>("");
  const [newColor, setNewColor] = useState<string>("#3b82f6");
  const [newFont, setNewFont] = useState<string>("");
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [savedSuccess, setSavedSuccess] = useState<boolean>(false);

  useEffect(() => {
    if (initialProfile) {
      setFormData((prev) => ({
        ...prev,
        ...initialProfile,
        brand_colors: initialProfile.brand_colors || prev.brand_colors || ["#0ea5e9", "#1e293b"],
        fonts: initialProfile.fonts || prev.fonts || ["Inter"],
      }));
    }
  }, [initialProfile]);

  const handleApplyTemplate = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const templateId = e.target.value;
    setSelectedTemplateId(templateId);
    if (!templateId) return;

    const tpl = templates.find((t) => t.id === templateId);
    if (tpl) {
      setFormData((prev) => ({
        ...prev,
        tagline: tpl.tagline || prev.tagline,
        tone_of_voice: tpl.tone_of_voice,
        legal_boundaries: tpl.legal_boundaries,
        target_audience: tpl.target_audience || prev.target_audience,
        brand_colors: tpl.brand_colors && tpl.brand_colors.length > 0 ? tpl.brand_colors : prev.brand_colors,
        fonts: tpl.fonts && tpl.fonts.length > 0 ? tpl.fonts : prev.fonts,
      }));
    }
  };

  const handleAddColor = () => {
    if (!newColor.trim()) return;
    const colors = formData.brand_colors || [];
    if (!colors.includes(newColor)) {
      setFormData({ ...formData, brand_colors: [...colors, newColor] });
    }
  };

  const handleRemoveColor = (indexToRemove: number) => {
    const colors = (formData.brand_colors || []).filter((_, i) => i !== indexToRemove);
    setFormData({ ...formData, brand_colors: colors });
  };

  const handleAddFont = () => {
    if (!newFont.trim()) return;
    const fonts = formData.fonts || [];
    if (!fonts.includes(newFont.trim())) {
      setFormData({ ...formData, fonts: [...fonts, newFont.trim()] });
      setNewFont("");
    }
  };

  const handleRemoveFont = (indexToRemove: number) => {
    const fonts = (formData.fonts || []).filter((_, i) => i !== indexToRemove);
    setFormData({ ...formData, fonts });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSaving(true);
    setSavedSuccess(false);
    try {
      if (onSave) {
        await onSave(formData);
      }
      setSavedSuccess(true);
      setTimeout(() => setSavedSuccess(false), 3000);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className={`bg-gray-900 border border-gray-800 rounded-xl p-6 ${className}`}>
      <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-6 border-b border-gray-800 gap-4">
        <div>
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-sky-400" />
            Hồ sơ Thương hiệu & Phong cách (Brand Identity)
          </h2>
          <p className="text-xs text-gray-400 mt-1">
            Quy định tone of voice, đối tượng mục tiêu và ranh giới đạo đức/pháp lý được tiêm vào mọi Agent Content & Funnel.
          </p>
        </div>

        {templates.length > 0 && (
          <div className="flex items-center gap-2">
            <label htmlFor="template-selector" className="text-xs text-gray-400 whitespace-nowrap">
              Áp dụng mẫu có sẵn:
            </label>
            <select
              id="template-selector"
              aria-label="Áp dụng mẫu có sẵn"
              value={selectedTemplateId}
              onChange={handleApplyTemplate}
              className="bg-gray-800 border border-gray-700 text-gray-200 text-xs rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-sky-500"
            >
              <option value="">-- Chọn mẫu thương hiệu --</option>
              {templates.map((tpl) => (
                <option key={tpl.id} value={tpl.id}>
                  {tpl.name}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      <form onSubmit={handleSubmit} className="mt-6 space-y-6">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Tên thương hiệu */}
          <div>
            <label className="block text-xs font-medium text-gray-300 mb-1.5">
              Tên thương hiệu <span className="text-rose-400">*</span>
            </label>
            <input
              type="text"
              required
              value={formData.brand_name || ""}
              onChange={(e) => setFormData({ ...formData, brand_name: e.target.value })}
              placeholder="Ví dụ: AI Master Hub"
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3.5 py-2 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-sky-500"
            />
          </div>

          {/* Khẩu hiệu / Tagline */}
          <div>
            <label className="block text-xs font-medium text-gray-300 mb-1.5">
              Khẩu hiệu (Tagline)
            </label>
            <input
              type="text"
              value={formData.tagline || ""}
              onChange={(e) => setFormData({ ...formData, tagline: e.target.value })}
              placeholder="Ví dụ: Khai mở tiềm năng - Dẫn lối thành công"
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3.5 py-2 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-sky-500"
            />
          </div>
        </div>

        {/* Khách hàng mục tiêu */}
        <div>
          <label className="block text-xs font-medium text-gray-300 mb-1.5">
            Khách hàng mục tiêu (Target Audience)
          </label>
          <textarea
            rows={2}
            value={formData.target_audience || ""}
            onChange={(e) => setFormData({ ...formData, target_audience: e.target.value })}
            placeholder="Ví dụ: Người đi làm 24-40 tuổi, các nhà sáng lập solo, chủ doanh nghiệp vừa và nhỏ..."
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3.5 py-2 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-sky-500"
          />
        </div>

        {/* Giọng văn & Tone of voice */}
        <div>
          <label className="block text-xs font-medium text-gray-300 mb-1.5">
            Giọng văn & Tone of Voice <span className="text-rose-400">*</span>
          </label>
          <textarea
            rows={3}
            required
            value={formData.tone_of_voice || ""}
            onChange={(e) => setFormData({ ...formData, tone_of_voice: e.target.value })}
            placeholder="Ví dụ: Chuyên nghiệp, súc tích, dựa trên dữ liệu dẫn chứng, ân cần và truyền cảm hứng..."
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3.5 py-2 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-sky-500"
          />
        </div>

        {/* Ranh giới pháp lý & đạo đức */}
        <div>
          <label className="block text-xs font-medium text-gray-300 mb-1.5 flex items-center gap-1.5">
            <ShieldAlert className="w-3.5 h-3.5 text-amber-400" />
            Ranh giới pháp lý, cam kết & đạo đức (Legal Boundaries)
          </label>
          <textarea
            rows={3}
            value={formData.legal_boundaries || ""}
            onChange={(e) => setFormData({ ...formData, legal_boundaries: e.target.value })}
            placeholder="Ví dụ: Không hứa hẹn làm giàu cấp tốc; không cam kết thu nhập cụ thể; đổi trả trong vòng 7 ngày nếu lỗi kỹ thuật..."
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3.5 py-2 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-sky-500"
          />
        </div>

        {/* Bảng màu & Font chữ */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 pt-2">
          {/* Brand Colors */}
          <div>
            <label className="block text-xs font-medium text-gray-300 mb-2 flex items-center gap-1.5">
              <Palette className="w-3.5 h-3.5 text-sky-400" />
              Bảng màu nhận diện (Brand Colors)
            </label>
            <div className="flex flex-wrap items-center gap-2 mb-3">
              {(formData.brand_colors || []).map((color, idx) => (
                <span
                  key={idx}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-mono bg-gray-800 border border-gray-700 text-gray-200"
                >
                  <span
                    className="w-3.5 h-3.5 rounded-full border border-gray-600 inline-block shrink-0"
                    style={{ backgroundColor: color }}
                  />
                  <span>{color}</span>
                  <button
                    type="button"
                    onClick={() => handleRemoveColor(idx)}
                    className="hover:text-rose-400 transition-colors cursor-pointer"
                    aria-label={`Xóa màu ${color}`}
                  >
                    <X className="w-3 h-3" />
                  </button>
                </span>
              ))}
            </div>
            <div className="flex items-center gap-2">
              <input
                type="color"
                value={newColor}
                onChange={(e) => setNewColor(e.target.value)}
                className="w-8 h-8 rounded bg-gray-800 border border-gray-700 cursor-pointer p-0.5"
              />
              <input
                type="text"
                value={newColor}
                onChange={(e) => setNewColor(e.target.value)}
                className="w-28 bg-gray-800 border border-gray-700 rounded-lg px-2.5 py-1 text-xs font-mono text-gray-200"
              />
              <button
                type="button"
                onClick={handleAddColor}
                className="flex items-center gap-1 px-3 py-1 bg-gray-800 hover:bg-gray-700 border border-gray-700 text-xs text-gray-200 rounded-lg cursor-pointer transition-colors"
              >
                <Plus className="w-3.5 h-3.5" />
                Thêm màu
              </button>
            </div>
          </div>

          {/* Fonts */}
          <div>
            <label className="block text-xs font-medium text-gray-300 mb-2 flex items-center gap-1.5">
              <Type className="w-3.5 h-3.5 text-purple-400" />
              Font chữ đề xuất (Fonts)
            </label>
            <div className="flex flex-wrap items-center gap-2 mb-3">
              {(formData.fonts || []).map((font, idx) => (
                <span
                  key={idx}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs bg-gray-800 border border-gray-700 text-gray-200"
                >
                  <span>{font}</span>
                  <button
                    type="button"
                    onClick={() => handleRemoveFont(idx)}
                    className="hover:text-rose-400 transition-colors cursor-pointer"
                    aria-label={`Xóa font ${font}`}
                  >
                    <X className="w-3 h-3" />
                  </button>
                </span>
              ))}
            </div>
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={newFont}
                onChange={(e) => setNewFont(e.target.value)}
                placeholder="Ví dụ: Plus Jakarta Sans"
                className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-2.5 py-1 text-xs text-gray-200"
              />
              <button
                type="button"
                onClick={handleAddFont}
                className="flex items-center gap-1 px-3 py-1 bg-gray-800 hover:bg-gray-700 border border-gray-700 text-xs text-gray-200 rounded-lg cursor-pointer transition-colors"
              >
                <Plus className="w-3.5 h-3.5" />
                Thêm font
              </button>
            </div>
          </div>
        </div>

        {/* Submit & Status Bar */}
        <div className="pt-4 border-t border-gray-800 flex items-center justify-between">
          <div>
            {savedSuccess && (
              <span className="flex items-center gap-1.5 text-xs text-emerald-400">
                <CheckCircle2 className="w-4 h-4" />
                Đã lưu và đồng bộ vector RAG thành công!
              </span>
            )}
          </div>
          <button
            type="submit"
            disabled={isSaving}
            className="flex items-center gap-2 px-5 py-2 rounded-lg bg-sky-500 hover:bg-sky-600 disabled:opacity-50 text-white font-medium text-sm transition-colors cursor-pointer shadow-sm"
          >
            <Save className="w-4 h-4" />
            <span>{isSaving ? "Đang lưu..." : "Lưu hồ sơ"}</span>
          </button>
        </div>
      </form>
    </div>
  );
}
