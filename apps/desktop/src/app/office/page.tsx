"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  AlertCircle,
  Bot,
  Briefcase,
  Compass,
  GitMerge,
  Layers,
  PenTool,
  Plus,
  ShoppingCart,
  Sparkles,
  Users,
  Wifi,
  WifiOff,
  Wrench,
  X,
} from "lucide-react";
import { SidebarNav } from "@/components/layout/SidebarNav";
import { ApiClient } from "@/lib/apiClient";
import type { Agent, Department } from "@/lib/types";

const CORE_DEPARTMENT_ORDER = [
  "Đội Content",
  "Đội Funnels",
  "Nghiên cứu & Phát triển",
  "Thương mại điện tử",
];

type OfficeDepartment = Department & { isFallback?: boolean };

function getDepartmentIcon(name: string) {
  switch (name) {
    case "Đội Content":
      return PenTool;
    case "Đội Funnels":
      return GitMerge;
    case "Nghiên cứu & Phát triển":
      return Compass;
    case "Thương mại điện tử":
      return ShoppingCart;
    case "Chưa vào phòng":
      return Users;
    default:
      return Briefcase;
  }
}

function getAgentStatusBadge(status?: string) {
  const normalized = (status || "idle").toLowerCase();
  if (normalized === "busy" || normalized === "running") {
    return (
      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium bg-sky-950/80 text-sky-300 border border-sky-700/60">
        <span className="w-1.5 h-1.5 rounded-full bg-sky-400 animate-pulse" />
        Đang chạy
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium bg-emerald-950/60 text-emerald-300 border border-emerald-800/50">
      <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
      Nghỉ
    </span>
  );
}

export default function OfficePage() {
  const [apiClient] = useState(() => new ApiClient());
  const [departments, setDepartments] = useState<OfficeDepartment[]>([]);
  const [allAgents, setAllAgents] = useState<Agent[]>([]);
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
  const [loadedFromBackend, setLoadedFromBackend] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [errorBanner, setErrorBanner] = useState<string | null>(null);

  // Add/Assign agent modal state
  const [targetDept, setTargetDept] = useState<OfficeDepartment | null>(null);
  const [modalTab, setModalTab] = useState<"assign" | "create">("assign");
  const [selectedAgentId, setSelectedAgentId] = useState<string>("");
  const [newAgentName, setNewAgentName] = useState("");
  const [newAgentDisplayName, setNewAgentDisplayName] = useState("");
  const [newAgentRole, setNewAgentRole] = useState("");
  const [newAgentModel, setNewAgentModel] = useState("gemini-2.5-flash");
  const [isSaving, setIsSaving] = useState(false);
  const [modalError, setModalError] = useState<string | null>(null);

  const loadOfficeData = useCallback(async () => {
    setIsLoading(true);
    setErrorBanner(null);
    try {
      const [loadedDepts, loadedAgents] = await Promise.all([
        apiClient.listDepartments(),
        apiClient.listAgents(),
      ]);
      setBackendOnline(true);
      setLoadedFromBackend(true);
      setDepartments(loadedDepts || []);
      setAllAgents(loadedAgents || []);
    } catch (err) {
      setBackendOnline(false);
      setLoadedFromBackend(false);
      setErrorBanner(
        err instanceof Error
          ? err.message
          : "Không thể tải danh sách phòng ban và tác tử từ máy chủ."
      );
    } finally {
      setIsLoading(false);
    }
  }, [apiClient]);

  useEffect(() => {
    loadOfficeData();
  }, [loadOfficeData]);

  const unassignedAgents = useMemo(() => {
    return allAgents.filter(
      (a) => !(a.departmentId || a.department_id)
    );
  }, [allAgents]);

  const orderedDepartments = useMemo(() => {
    const byName = new Map(departments.map((d) => [d.name, d]));
    const core: OfficeDepartment[] = CORE_DEPARTMENT_ORDER.map(
      (name) =>
        byName.get(name) || {
          id: `dept-${name}`,
          name,
          status: "active",
          agentsCount: 0,
          agents: [],
          isFallback: true,
        }
    );
    const extras: OfficeDepartment[] = departments.filter(
      (d) => !CORE_DEPARTMENT_ORDER.includes(d.name)
    );
    return [...core, ...extras];
  }, [departments]);

  const departmentGroups = useMemo(() => {
    const groups = orderedDepartments.map((dept) => {
      const agentsFromDept =
        dept.agents && dept.agents.length > 0
          ? dept.agents
          : allAgents.filter(
              (a) => (a.departmentId || a.department_id) === dept.id
            );
      return {
        ...dept,
        resolvedAgents: agentsFromDept,
        isUnassignedGroup: false,
      };
    });

    groups.push({
      id: "unassigned",
      name: "Chưa vào phòng",
      description: "Các tác tử đang chờ phân công vào phòng ban chuyên môn",
      status: "active",
      agentsCount: unassignedAgents.length,
      resolvedAgents: unassignedAgents,
      isUnassignedGroup: true,
      isFallback: false,
    });

    return groups;
  }, [orderedDepartments, allAgents, unassignedAgents]);

  const assignableCandidates = useMemo(() => {
    if (!targetDept) return [];
    const candidates = allAgents.filter(
      (a) => (a.departmentId || a.department_id) !== targetDept.id
    );
    return candidates;
  }, [allAgents, targetDept]);

  const closeAddModal = () => {
    setTargetDept(null);
    setModalError(null);
  };

  const openAddModal = (dept: OfficeDepartment) => {
    if (!loadedFromBackend || dept.isFallback) {
      return;
    }
    setTargetDept(dept);
    const candidates = allAgents.filter(
      (a) => (a.departmentId || a.department_id) !== dept.id
    );
    if (candidates.length > 0) {
      setModalTab("assign");
      setSelectedAgentId(candidates[0].id);
    } else {
      setModalTab("create");
      setSelectedAgentId("");
    }
    setNewAgentName("");
    setNewAgentDisplayName("");
    setNewAgentRole("");
    setModalError(null);
  };

  const handleAssignOrCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!targetDept || isSaving) return;

    if (!loadedFromBackend || targetDept.isFallback) {
      setModalError("Phòng ban này chưa được đồng bộ từ máy chủ.");
      return;
    }

    setModalError(null);

    if (modalTab === "assign") {
      if (!selectedAgentId) {
        setModalError("Vui lòng chọn một Agent để chuyển vào phòng.");
        return;
      }
    } else {
      const trimmedName = newAgentName.trim();
      const trimmedDisplayName = newAgentDisplayName.trim();
      const trimmedRole = newAgentRole.trim();

      if (!trimmedName || !/^[a-zA-Z0-9_]+$/.test(trimmedName)) {
        setModalError(
          "Mã định danh (@name) không được để trống và chỉ gồm chữ cái, số hoặc dấu gạch dưới (_)."
        );
        return;
      }
      if (!trimmedDisplayName) {
        setModalError("Tên hiển thị không được để trống.");
        return;
      }
      if (!trimmedRole) {
        setModalError("Vai trò không được để trống.");
        return;
      }
    }

    setIsSaving(true);
    try {
      if (modalTab === "assign") {
        await apiClient.updateAgent(selectedAgentId, {
          departmentId: targetDept.id,
        });
      } else {
        await apiClient.createAgent({
          name: newAgentName.trim(),
          displayName: newAgentDisplayName.trim(),
          role: newAgentRole.trim(),
          departmentId: targetDept.id,
          defaultModel: newAgentModel.trim() || "gemini-2.5-flash",
        });
      }
      closeAddModal();
      await loadOfficeData();
    } catch (err) {
      setModalError(
        err instanceof Error
          ? err.message
          : "Không thể cập nhật thành viên phòng ban."
      );
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="flex h-screen bg-gray-950 text-gray-100 overflow-hidden font-sans">
      <SidebarNav
        activeNav="workspace"
        onNewTask={() => {
          if (typeof window !== "undefined") window.location.assign("/");
        }}
        onNavigate={(navId) => {
          if (navId === "workspace" && typeof window !== "undefined") {
            window.location.assign("/office");
          }
        }}
      />

      <main className="flex-1 flex flex-col h-full overflow-hidden bg-gray-950">
        {/* Header */}
        <header className="h-14 border-b border-gray-800 px-6 flex items-center justify-between shrink-0 bg-gray-900/60 backdrop-blur-sm">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-sky-400" />
              <h1 className="text-sm font-semibold text-white">
                Văn Phòng AI & Phòng Ban
              </h1>
            </div>

            <nav className="flex items-center gap-1 text-xs">
              <Link
                href="/"
                className="px-2.5 py-1 rounded-lg text-gray-400 hover:text-gray-100 hover:bg-gray-800/70 transition-colors"
              >
                Tổng Chỉ Huy
              </Link>
              <Link
                href="/office"
                className="px-2.5 py-1 rounded-lg bg-gray-800 text-sky-300 font-medium"
              >
                Văn Phòng
              </Link>
              <Link
                href="/board"
                className="px-2.5 py-1 rounded-lg text-gray-400 hover:text-gray-100 hover:bg-gray-800/70 transition-colors"
              >
                Bảng Công Việc
              </Link>
            </nav>
          </div>

          <div className="flex items-center gap-3 text-xs">
            {backendOnline === true ? (
              <span className="flex items-center gap-1.5 text-emerald-400 font-medium">
                <Wifi className="w-3.5 h-3.5" />
                <span>Đã kết nối</span>
              </span>
            ) : backendOnline === false ? (
              <span className="flex items-center gap-1.5 text-amber-400 font-medium">
                <WifiOff className="w-3.5 h-3.5" />
                <span>Chế độ ngoại tuyến</span>
              </span>
            ) : null}

            <span className="inline-flex items-center gap-1 text-gray-400">
              <Layers className="w-3.5 h-3.5 text-purple-400" />
              <span>{departmentGroups.length} nhóm phòng ban</span>
            </span>
          </div>
        </header>

        {/* Main Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {errorBanner && (
            <div
              role="alert"
              className="p-3 rounded-xl bg-rose-950/60 border border-rose-800/70 text-xs text-rose-200 flex items-center justify-between gap-3"
            >
              <span className="flex items-center gap-2">
                <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
                <span>{errorBanner}</span>
              </span>
              <button
                type="button"
                onClick={loadOfficeData}
                className="px-2.5 py-1 rounded-lg bg-rose-900/70 hover:bg-rose-800 text-rose-100 font-medium shrink-0 cursor-pointer"
              >
                Thử lại
              </button>
            </div>
          )}

          {isLoading ? (
            <div className="text-xs text-gray-400">Đang tải sơ đồ văn phòng AI...</div>
          ) : (
            <div className="space-y-6 max-w-7xl mx-auto">
              {departmentGroups.map((group) => {
                const Icon = getDepartmentIcon(group.name);
                const isSyntheticDept =
                  !loadedFromBackend || Boolean(group.isFallback);
                return (
                  <section
                    key={group.id}
                    data-testid={`department-group-${group.id}`}
                    className="rounded-2xl bg-gray-900/70 border border-gray-800 p-5 space-y-4"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-800/80 pb-3">
                      <div className="flex items-center gap-3">
                        <div className="w-9 h-9 rounded-xl bg-gray-800 border border-gray-700 flex items-center justify-center text-sky-400">
                          <Icon className="w-4 h-4" />
                        </div>
                        <div>
                          <div className="flex items-center gap-2">
                            <h2 className="text-sm font-semibold text-white">
                              {group.name}
                            </h2>
                            <span className="px-2 py-0.5 rounded-full text-[11px] font-mono bg-gray-800 text-gray-300">
                              {group.resolvedAgents.length} thành viên
                            </span>
                          </div>
                          {group.description && (
                            <p className="text-xs text-gray-400 mt-0.5">
                              {group.description}
                            </p>
                          )}
                        </div>
                      </div>

                      {!group.isUnassignedGroup && (
                        <button
                          type="button"
                          disabled={isSyntheticDept}
                          title={
                            isSyntheticDept
                              ? "Cần kết nối backend với phòng ban thật để thêm hoặc gán Agent"
                              : "Thêm hoặc gán Agent vào phòng ban này"
                          }
                          onClick={() => openAddModal(group)}
                          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium bg-sky-600/20 hover:bg-sky-600/30 text-sky-300 border border-sky-700/50 transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                          <Plus className="w-3.5 h-3.5" />
                          <span>+ Thêm vào phòng</span>
                        </button>
                      )}
                    </div>

                    {group.resolvedAgents.length === 0 ? (
                      <div className="py-6 text-center rounded-xl border border-dashed border-gray-800 text-xs text-gray-500">
                        Chưa có agent nào trong nhóm này.
                      </div>
                    ) : (
                      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3.5">
                        {group.resolvedAgents.map((agent) => {
                          const displayName =
                            agent.displayName ||
                            agent.display_name ||
                            agent.name;
                          const skillsCount =
                            agent.skillsCount ?? agent.skills_count ?? 0;
                          const modelName =
                            agent.defaultModel ||
                            agent.default_model ||
                            "gemini-2.5-flash";

                          return (
                            <article
                              key={agent.id}
                              className="rounded-xl bg-gray-950/90 border border-gray-800 hover:border-gray-700 p-4 space-y-3 transition-colors"
                            >
                              <div className="flex items-start justify-between gap-2">
                                <div className="flex items-center gap-2.5 min-w-0">
                                  <div className="w-8 h-8 rounded-lg bg-sky-950/70 border border-sky-800/50 flex items-center justify-center text-sky-400 shrink-0">
                                    <Bot className="w-4 h-4" />
                                  </div>
                                  <div className="min-w-0">
                                    <h3 className="text-xs font-semibold text-white truncate">
                                      {displayName}
                                    </h3>
                                    <p className="text-[11px] font-mono text-sky-400 truncate">
                                      @{agent.name}
                                    </p>
                                  </div>
                                </div>
                                {getAgentStatusBadge(agent.status)}
                              </div>

                              <p className="text-xs text-gray-400 line-clamp-2">
                                {agent.role || "Chuyên viên AI"}
                              </p>

                              <div className="pt-2 border-t border-gray-800/80 flex items-center justify-between gap-2 text-[11px] text-gray-400">
                                <span className="inline-flex items-center gap-1">
                                  <Wrench className="w-3 h-3 text-amber-400" />
                                  <span>{skillsCount} kỹ năng</span>
                                </span>
                                <span className="px-2 py-0.5 rounded bg-gray-900 border border-gray-800 font-mono text-[10px] text-gray-300 truncate max-w-[140px]">
                                  {modelName}
                                </span>
                              </div>
                            </article>
                          );
                        })}
                      </div>
                    )}
                  </section>
                );
              })}
            </div>
          )}
        </div>
      </main>

      {/* Modal: + Thêm vào phòng */}
      {targetDept && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
          role="dialog"
          aria-modal="true"
          aria-label="Thêm Agent vào phòng"
        >
          <div className="w-full max-w-md rounded-2xl bg-gray-900 border border-gray-800 p-5 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold text-white">
                  Thêm Agent vào phòng
                </h3>
                <p className="text-xs text-sky-400 mt-0.5">{targetDept.name}</p>
              </div>
              <button
                type="button"
                onClick={closeAddModal}
                aria-label="Đóng"
                className="p-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-gray-800 cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="flex gap-2 border-b border-gray-800 pb-2">
              <button
                type="button"
                onClick={() => {
                  setModalTab("assign");
                  setModalError(null);
                }}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium cursor-pointer ${
                  modalTab === "assign"
                    ? "bg-sky-600 text-white"
                    : "text-gray-400 hover:text-gray-200"
                }`}
              >
                Chọn Agent có sẵn
              </button>
              <button
                type="button"
                onClick={() => {
                  setModalTab("create");
                  setModalError(null);
                }}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium cursor-pointer ${
                  modalTab === "create"
                    ? "bg-sky-600 text-white"
                    : "text-gray-400 hover:text-gray-200"
                }`}
              >
                Tạo Agent mới
              </button>
            </div>

            <form onSubmit={handleAssignOrCreate} noValidate className="space-y-3">
              {modalTab === "assign" ? (
                <div className="space-y-1.5">
                  <label className="block text-xs font-medium text-gray-300">
                    Chọn tác tử để chuyển vào phòng
                  </label>
                  {assignableCandidates.length === 0 ? (
                    <p className="text-xs text-gray-500">
                      Không có tác tử nào ở ngoài phòng này. Hãy chuyển sang tab Tạo Agent mới.
                    </p>
                  ) : (
                    <select
                      value={selectedAgentId}
                      onChange={(e) => setSelectedAgentId(e.target.value)}
                      className="w-full rounded-xl bg-gray-950 border border-gray-700 px-3 py-2 text-xs text-gray-100 focus:outline-none focus:border-sky-500"
                    >
                      {assignableCandidates.map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.displayName || a.display_name || a.name} (@{a.name})
                        </option>
                      ))}
                    </select>
                  )}
                </div>
              ) : (
                <>
                  <div className="space-y-1">
                    <label className="block text-xs font-medium text-gray-300">
                      Mã định danh (@name)
                    </label>
                    <input
                      type="text"
                      required
                      pattern="[a-zA-Z0-9_]+"
                      value={newAgentName}
                      onChange={(e) => setNewAgentName(e.target.value)}
                      placeholder="VD: SeoWriter"
                      className="w-full rounded-xl bg-gray-950 border border-gray-700 px-3 py-2 text-xs text-gray-100 focus:outline-none focus:border-sky-500"
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="block text-xs font-medium text-gray-300">
                      Tên hiển thị
                    </label>
                    <input
                      type="text"
                      required
                      value={newAgentDisplayName}
                      onChange={(e) => setNewAgentDisplayName(e.target.value)}
                      placeholder="VD: Chuyên viên SEO"
                      className="w-full rounded-xl bg-gray-950 border border-gray-700 px-3 py-2 text-xs text-gray-100 focus:outline-none focus:border-sky-500"
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="block text-xs font-medium text-gray-300">
                      Vai trò
                    </label>
                    <input
                      type="text"
                      required
                      value={newAgentRole}
                      onChange={(e) => setNewAgentRole(e.target.value)}
                      placeholder="VD: SEO Content Specialist"
                      className="w-full rounded-xl bg-gray-950 border border-gray-700 px-3 py-2 text-xs text-gray-100 focus:outline-none focus:border-sky-500"
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="block text-xs font-medium text-gray-300">
                      Model mặc định
                    </label>
                    <input
                      type="text"
                      value={newAgentModel}
                      onChange={(e) => setNewAgentModel(e.target.value)}
                      className="w-full rounded-xl bg-gray-950 border border-gray-700 px-3 py-2 text-xs text-gray-100 focus:outline-none focus:border-sky-500"
                    />
                  </div>
                </>
              )}

              {modalError && (
                <div
                  role="alert"
                  className="p-2.5 rounded-xl bg-rose-950/70 border border-rose-800/70 text-xs text-rose-200 flex items-center gap-2"
                >
                  <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
                  <span>{modalError}</span>
                </div>
              )}

              <div className="flex items-center justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={closeAddModal}
                  className="px-3 py-1.5 rounded-lg text-xs text-gray-400 hover:text-gray-200 hover:bg-gray-800 cursor-pointer"
                >
                  Hủy
                </button>
                <button
                  type="submit"
                  disabled={
                    isSaving ||
                    (modalTab === "assign" && assignableCandidates.length === 0)
                  }
                  className="px-4 py-1.5 rounded-lg text-xs font-semibold bg-sky-600 hover:bg-sky-500 text-white disabled:opacity-40 cursor-pointer"
                >
                  {isSaving ? "Đang lưu..." : "Xác nhận"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
