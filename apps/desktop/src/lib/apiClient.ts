import {
  Agent,
  ApiError,
  ApiResponse,
  BoardTask,
  BrainDocumentItem,
  BrandProfile,
  BrandTemplate,
  ConnectorStatus,
  CsvImportResult,
  Department,
  ExecutionMode,
  InboxConversation,
  InboxMessage,
  ParsedTask,
  PriceHistoryItem,
  ProductItem,
  Project,
  ReviewDecidePayload,
  ReviewDecision,
  ReviewGate,
  SemanticSearchHit,
  StoryboardData,
  StoryboardSceneData,
  TaskLogEntry,
} from "./types";

export interface ApiClientConfig {
  baseUrl?: string;
  token?: string;
}

declare global {
  interface Window {
    __LOCAL_AUTH_TOKEN__?: string;
  }
}

export class ApiClient {
  private baseUrl: string;
  private token?: string;

  constructor(config?: ApiClientConfig) {
    this.baseUrl = (
      config?.baseUrl ||
      (typeof process !== "undefined" && process.env?.NEXT_PUBLIC_API_URL) ||
      "http://127.0.0.1:8765"
    ).replace(/\/$/, "");

    this.token = config?.token;
  }

  public setToken(token: string): void {
    this.token = token;
  }

  private resolveToken(): string {
    if (this.token) {
      return this.token;
    }
    if (typeof window !== "undefined" && window.__LOCAL_AUTH_TOKEN__) {
      return window.__LOCAL_AUTH_TOKEN__;
    }
    if (typeof process !== "undefined" && process.env?.NEXT_PUBLIC_LOCAL_AUTH_TOKEN) {
      return process.env.NEXT_PUBLIC_LOCAL_AUTH_TOKEN;
    }
    return "dev-local-token";
  }

  private async request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const url = `${this.baseUrl}${endpoint.startsWith("/") ? endpoint : `/${endpoint}`}`;
    const token = this.resolveToken();

    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      "X-Local-Auth-Token": token,
      ...(options.headers as Record<string, string>),
    };

    let response: Response;
    try {
      response = await fetch(url, {
        ...options,
        headers,
      });
    } catch (err) {
      throw new ApiError(
        `Không thể kết nối đến backend AI Agent Workspace tại ${this.baseUrl}: ${err instanceof Error ? err.message : String(err)}`,
        0,
        err
      );
    }

    let json: any = null;
    try {
      json = await response.json();
    } catch {
      // Non-JSON response
    }

    if (!response.ok) {
      const detail = json?.detail || json?.message || response.statusText;
      const errorMsg = typeof detail === "string" ? detail : JSON.stringify(detail);
      throw new ApiError(errorMsg, response.status, detail);
    }

    // Unpack backend standard { status: "success", data: ... }
    if (json && typeof json === "object" && "status" in json && "data" in json) {
      return json.data as T;
    }

    return json as T;
  }

  /**
   * Health check to detect whether the local backend sidecar daemon is running.
   */
  async checkHealth(): Promise<{ status: string; service: string; version: string }> {
    return this.request<{ status: string; service: string; version: string }>("/api/v1/health");
  }

  /**
   * List registered agents with optional department and status filtering.
   */
  async listAgents(departmentId?: string, status?: string): Promise<Agent[]> {
    const params = new URLSearchParams();
    if (departmentId) params.append("department_id", departmentId);
    if (status) params.append("status", status);

    const qs = params.toString() ? `?${params.toString()}` : "";
    const rawAgents = await this.request<any[]>(`/api/v1/agents${qs}`);

    return (rawAgents || []).map((raw) => this.normalizeAgent(raw));
  }

  /**
   * Get single agent by ID.
   */
  async getAgent(id: string): Promise<Agent> {
    const raw = await this.request<any>(`/api/v1/agents/${id}`);
    return this.normalizeAgent(raw);
  }

  /**
   * Create a new agent in the workspace.
   */
  async createAgent(payload: {
    name: string;
    displayName: string;
    role: string;
    departmentId?: string | null;
    description?: string;
    defaultModel?: string;
  }): Promise<Agent> {
    const raw = await this.request<any>("/api/v1/agents", {
      method: "POST",
      body: JSON.stringify({
        name: payload.name,
        displayName: payload.displayName,
        role: payload.role,
        departmentId: payload.departmentId ?? null,
        description: payload.description,
        defaultModel: payload.defaultModel || "gemini-2.5-flash",
      }),
    });
    return this.normalizeAgent(raw);
  }

  /**
   * Update an existing agent (e.g. assign or move department).
   */
  async updateAgent(
    agentId: string,
    payload: {
      displayName?: string;
      role?: string;
      description?: string;
      departmentId?: string | null;
      status?: string;
      defaultModel?: string;
    }
  ): Promise<Agent> {
    const raw = await this.request<any>(
      `/api/v1/agents/${encodeURIComponent(agentId)}`,
      {
        method: "PUT",
        body: JSON.stringify({
          ...(payload.displayName !== undefined
            ? { displayName: payload.displayName }
            : {}),
          ...(payload.role !== undefined ? { role: payload.role } : {}),
          ...(payload.description !== undefined
            ? { description: payload.description }
            : {}),
          ...(payload.departmentId !== undefined
            ? { departmentId: payload.departmentId ?? "" }
            : {}),
          ...(payload.status !== undefined ? { status: payload.status } : {}),
          ...(payload.defaultModel !== undefined
            ? { defaultModel: payload.defaultModel }
            : {}),
        }),
      }
    );
    return this.normalizeAgent(raw);
  }

  /**
   * List all functional departments along with assigned agents and skill counts.
   */
  async listDepartments(): Promise<Department[]> {
    const rawDepartments = await this.request<any[]>("/api/v1/departments");
    return (rawDepartments || []).map((raw) => ({
      id: raw.id,
      name: raw.name,
      description: raw.description ?? null,
      icon: raw.icon ?? null,
      color: raw.color ?? null,
      status: raw.status || "active",
      agentsCount: raw.agentsCount ?? raw.agents_count ?? raw.agents?.length ?? 0,
      agents_count: raw.agents_count ?? raw.agentsCount ?? raw.agents?.length ?? 0,
      agents: Array.isArray(raw.agents)
        ? raw.agents.map((a: any) => this.normalizeAgent(a))
        : undefined,
      createdAt: raw.createdAt ?? raw.created_at ?? null,
      created_at: raw.created_at ?? raw.createdAt ?? null,
      updatedAt: raw.updatedAt ?? raw.updated_at ?? null,
      updated_at: raw.updated_at ?? raw.updatedAt ?? null,
    }));
  }

  /**
   * List workspace projects with task counts and status summaries.
   */
  async listProjects(): Promise<Project[]> {
    const rawProjects = await this.request<any[]>("/api/v1/projects");
    return (rawProjects || []).map((raw) => ({
      id: raw.id,
      name: raw.name,
      description: raw.description ?? null,
      tags: raw.tags || [],
      defaultDepartmentId:
        raw.defaultDepartmentId ?? raw.default_department_id ?? null,
      default_department_id:
        raw.default_department_id ?? raw.defaultDepartmentId ?? null,
      taskCount: raw.taskCount ?? raw.task_count ?? 0,
      task_count: raw.task_count ?? raw.taskCount ?? 0,
      statusSummary: raw.statusSummary ?? raw.status_summary ?? {},
      status_summary: raw.status_summary ?? raw.statusSummary ?? {},
      createdAt: raw.createdAt ?? raw.created_at ?? null,
      created_at: raw.created_at ?? raw.createdAt ?? null,
      updatedAt: raw.updatedAt ?? raw.updated_at ?? null,
      updated_at: raw.updated_at ?? raw.updatedAt ?? null,
    }));
  }

  /**
   * Create a new workspace project.
   */
  async createProject(payload: {
    name: string;
    description?: string;
    tags?: string[];
    defaultDepartmentId?: string;
  }): Promise<Project> {
    const raw = await this.request<any>("/api/v1/projects", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    return {
      id: raw.id,
      name: raw.name,
      description: raw.description ?? null,
      tags: raw.tags || [],
      defaultDepartmentId:
        raw.defaultDepartmentId ?? raw.default_department_id ?? null,
      taskCount: raw.taskCount ?? raw.task_count ?? 0,
      statusSummary: raw.statusSummary ?? raw.status_summary ?? {},
      createdAt: raw.createdAt ?? raw.created_at ?? null,
      updatedAt: raw.updatedAt ?? raw.updated_at ?? null,
    };
  }

  /**
   * List tasks for the Kanban/List board with optional filtering.
   */
  async listTasks(filters?: {
    projectId?: string;
    status?: string;
    assignedAgentId?: string;
    limit?: number;
    offset?: number;
  }): Promise<BoardTask[]> {
    const params = new URLSearchParams();
    if (filters?.projectId) params.append("project_id", filters.projectId);
    if (filters?.status) params.append("status", filters.status);
    if (filters?.assignedAgentId)
      params.append("assigned_agent_id", filters.assignedAgentId);
    if (filters?.limit !== undefined) params.append("limit", String(filters.limit));
    if (filters?.offset !== undefined)
      params.append("offset", String(filters.offset));

    const qs = params.toString() ? `?${params.toString()}` : "";
    const rawTasks = await this.request<any[]>(`/api/v1/tasks${qs}`);
    return (rawTasks || []).map((raw) => this.normalizeTask(raw));
  }

  /**
   * Transition a task's FSM state via PATCH /api/v1/tasks/{taskId}/state.
   */
  async transitionTaskState(
    taskId: string,
    targetState: string,
    options?: { actor?: string; reason?: string }
  ): Promise<BoardTask> {
    const raw = await this.request<any>(
      `/api/v1/tasks/${encodeURIComponent(taskId)}/state`,
      {
        method: "PATCH",
        body: JSON.stringify({
          target_state: targetState,
          actor: options?.actor || "user",
          reason: options?.reason,
        }),
      }
    );
    return this.normalizeTask(raw);
  }

  /**
   * Fetch chronological TurnLog & TaskAuditLog timeline for a task.
   */
  async getTaskLogs(taskId: string): Promise<TaskLogEntry[]> {
    const rawLogs = await this.request<any[]>(
      `/api/v1/tasks/${encodeURIComponent(taskId)}/logs`
    );
    return (rawLogs || []).map((raw) => this.normalizeTaskLog(raw));
  }

  /**
   * Build authenticated WebSocket URL for live task events (/ws/tasks/{taskId}).
   */
  getTaskWebSocketUrl(taskId: string): string {
    const wsBase = this.baseUrl.replace(/^http/i, "ws");
    const token = encodeURIComponent(this.resolveToken());
    return `${wsBase}/ws/tasks/${encodeURIComponent(taskId)}?token=${token}`;
  }

  /**
   * Parse a natural language prompt, extracting mentions, entities, and creating a pending task.
   */
  async parseTask(
    promptText: string,
    options?: {
      projectId?: string;
      attachments?: string[];
      mode?: ExecutionMode;
    }
  ): Promise<ParsedTask> {
    const payload = {
      projectId: options?.projectId || "proj-default",
      promptText,
      attachments: options?.attachments || [],
      mode: options?.mode || "copilot",
    };

    const raw = await this.request<any>("/api/v1/tasks/parse", {
      method: "POST",
      body: JSON.stringify(payload),
    });

    return {
      taskId: raw.task_id || raw.taskId,
      task_id: raw.task_id || raw.taskId,
      intent: raw.intent,
      taskType: raw.task_type || raw.taskType,
      task_type: raw.task_type || raw.taskType,
      mentionedAgents: raw.mentioned_agents || raw.mentionedAgents || [],
      mentioned_agents: raw.mentioned_agents || raw.mentionedAgents || [],
      urls: raw.urls || [],
      attachmentIds: raw.attachment_ids || raw.attachmentIds || [],
      attachment_ids: raw.attachment_ids || raw.attachmentIds || [],
      entities: raw.entities || {},
      plan: raw.plan || null,
    };
  }

  /**
   * Retrieve recent prompt history for autocomplete and suggestions.
   */
  async getTaskHistory(query?: string, limit: number = 50): Promise<string[]> {
    const params = new URLSearchParams();
    if (query) params.append("query", query);
    if (limit) params.append("limit", String(limit));

    const qs = params.toString() ? `?${params.toString()}` : "";
    const history = await this.request<string[]>(`/api/v1/tasks/history${qs}`);
    return history || [];
  }

  /**
   * List Human-in-the-Loop review gates with optional task or status filtering.
   */
  async listReviews(taskId?: string, status?: string): Promise<ReviewGate[]> {
    const params = new URLSearchParams();
    if (taskId) params.append("task_id", taskId);
    if (status) params.append("status", status);

    const qs = params.toString() ? `?${params.toString()}` : "";
    const rawReviews = await this.request<any[]>(`/api/v1/reviews${qs}`);
    return (rawReviews || []).map((raw) => this.normalizeReview(raw));
  }

  /**
   * Create a new pending Human-in-the-Loop review gate for a task.
   */
  async createReview(payload: {
    taskId: string;
    gateType?: string;
    summary?: string;
    payload?: unknown;
    expiresInHours?: number;
  }): Promise<ReviewGate> {
    const raw = await this.request<any>("/api/v1/reviews", {
      method: "POST",
      body: JSON.stringify({
        task_id: payload.taskId,
        gate_type: payload.gateType || "hil",
        summary: payload.summary,
        payload: payload.payload,
        expires_in_hours: payload.expiresInHours,
      }),
    });
    return this.normalizeReview(raw);
  }

  /**
   * Retrieve a single Human-in-the-Loop review gate by ID.
   */
  async getReview(reviewId: string): Promise<ReviewGate> {
    const raw = await this.request<any>(`/api/v1/reviews/${encodeURIComponent(reviewId)}`);
    return this.normalizeReview(raw);
  }

  /**
   * Submit a human decision ('approve', 'edit', or 'reject') on a review gate.
   */
  async decideReview(
    reviewId: string,
    decision: ReviewDecision,
    payload?: ReviewDecidePayload
  ): Promise<ReviewGate> {
    const raw = await this.request<any>(
      `/api/v1/reviews/${encodeURIComponent(reviewId)}/decide`,
      {
        method: "PATCH",
        body: JSON.stringify({
          decision,
          feedback_text: payload?.feedbackText,
          edited_content: payload?.editedContent,
          actor: payload?.actor || "user",
        }),
      }
    );
    return this.normalizeReview(raw);
  }

  public streamMediaUrl(targetId: string, isFileRoute = false): string {
    const route = isFileRoute ? "files" : "artifacts";
    return `${this.baseUrl}/api/v1/${route}/${encodeURIComponent(targetId)}/stream`;
  }

  public async getArtifactStoryboard(artifactId: string): Promise<StoryboardData> {
    const raw = await this.request<any>(
      `/api/v1/artifacts/${encodeURIComponent(artifactId)}/storyboard`
    );
    return this.normalizeStoryboard(raw);
  }

  public async updateStoryboardScene(
    artifactId: string,
    sceneId: string,
    payload: {
      action?: "delete" | string;
      deleted?: boolean;
      overlayText?: string;
      overlay_text?: string;
      effect?: string;
      visualNotes?: string;
      visual_notes?: string;
      durationSec?: number;
      duration?: number;
    }
  ): Promise<StoryboardData> {
    const raw = await this.request<any>(
      `/api/v1/artifacts/${encodeURIComponent(artifactId)}/storyboard/scenes/${encodeURIComponent(sceneId)}`,
      {
        method: "PATCH",
        body: JSON.stringify({
          action: payload.action,
          deleted: payload.deleted,
          overlay_text: payload.overlayText ?? payload.overlay_text,
          effect: payload.effect,
          visual_notes: payload.visualNotes ?? payload.visual_notes,
          duration: payload.durationSec ?? payload.duration,
        }),
      }
    );
    return this.normalizeStoryboard(raw);
  }

  private normalizeStoryboard(raw: any): StoryboardData {
    if (!raw) {
      return {
        styleName: "Rainmaker Style",
        totalDuration: 0,
        warnings: [],
        scenes: [],
      };
    }
    const rawScenes = Array.isArray(raw.scenes) ? raw.scenes : [];
    const scenes: StoryboardSceneData[] = rawScenes.map((s: any, idx: number) => {
      const dur = Number(s.durationSec ?? s.duration ?? (s.end && s.start ? s.end - s.start : 3.0));
      return {
        sceneId: String(s.sceneId || s.scene_id || s.id || `s${idx + 1}`),
        scene_id: String(s.scene_id || s.sceneId || s.id || `s${idx + 1}`),
        start: s.start !== undefined ? Number(s.start) : undefined,
        end: s.end !== undefined ? Number(s.end) : undefined,
        startSec: s.startSec !== undefined ? Number(s.startSec) : s.start !== undefined ? Number(s.start) : undefined,
        endSec: s.endSec !== undefined ? Number(s.endSec) : s.end !== undefined ? Number(s.end) : undefined,
        durationSec: dur,
        duration: dur,
        overlayText: String(s.overlayText ?? s.overlay_text ?? s.text ?? ""),
        overlay_text: String(s.overlay_text ?? s.overlayText ?? s.text ?? ""),
        effect: String(s.effect || "none"),
        visualNotes: s.visualNotes ?? s.visual_notes ?? "",
        visual_notes: s.visual_notes ?? s.visualNotes ?? "",
        transition: s.transition ?? "cut",
      };
    });

    const calcTotal = Number(
      raw.totalDuration ?? raw.total_duration ?? scenes.reduce((acc, s) => acc + (s.durationSec || 0), 0)
    );

    return {
      styleName: raw.styleName || raw.style_name || "Rainmaker Style",
      style_name: raw.style_name || raw.styleName || "Rainmaker Style",
      totalDuration: calcTotal,
      total_duration: calcTotal,
      sceneCount: scenes.length,
      scene_count: scenes.length,
      warnings: Array.isArray(raw.warnings) ? raw.warnings : Array.isArray(raw.pacing_warnings) ? raw.pacing_warnings : [],
      pacing_warnings: Array.isArray(raw.pacing_warnings) ? raw.pacing_warnings : Array.isArray(raw.warnings) ? raw.warnings : [],
      scenes,
    };
  }

  private normalizeTask(raw: any): BoardTask {
    return {
      id: raw.id,
      projectId: raw.projectId || raw.project_id || "proj-default",
      project_id: raw.project_id || raw.projectId || "proj-default",
      title: raw.title,
      description: raw.description ?? null,
      status: raw.status || "pending",
      priority: raw.priority || "normal",
      assignedAgentId: raw.assignedAgentId ?? raw.assigned_agent_id ?? null,
      assigned_agent_id: raw.assigned_agent_id ?? raw.assignedAgentId ?? null,
      agentName: raw.agentName ?? raw.agent_name ?? null,
      agent_name: raw.agent_name ?? raw.agentName ?? null,
      agentDisplayName: raw.agentDisplayName ?? raw.agent_display_name ?? null,
      agent_display_name: raw.agent_display_name ?? raw.agentDisplayName ?? null,
      turnCount: raw.turnCount ?? raw.turn_count ?? 0,
      turn_count: raw.turn_count ?? raw.turnCount ?? 0,
      metadata: raw.metadata ?? null,
      startedAt: raw.startedAt ?? raw.started_at ?? null,
      started_at: raw.started_at ?? raw.startedAt ?? null,
      completedAt: raw.completedAt ?? raw.completed_at ?? null,
      completed_at: raw.completed_at ?? raw.completedAt ?? null,
      createdAt: raw.createdAt ?? raw.created_at ?? null,
      created_at: raw.created_at ?? raw.createdAt ?? null,
      updatedAt: raw.updatedAt ?? raw.updated_at ?? null,
      updated_at: raw.updated_at ?? raw.updatedAt ?? null,
    };
  }

  private normalizeTaskLog(raw: any): TaskLogEntry {
    return {
      id: raw.id,
      logType: raw.logType ?? raw.log_type ?? "turn",
      log_type: raw.log_type ?? raw.logType ?? "turn",
      taskId: raw.taskId ?? raw.task_id,
      task_id: raw.task_id ?? raw.taskId,
      subtaskId: raw.subtaskId ?? raw.subtask_id ?? null,
      subtask_id: raw.subtask_id ?? raw.subtaskId ?? null,
      agentId: raw.agentId ?? raw.agent_id ?? null,
      agent_id: raw.agent_id ?? raw.agentId ?? null,
      agentName: raw.agentName ?? raw.agent_name ?? null,
      agent_name: raw.agent_name ?? raw.agentName ?? null,
      agentDisplayName: raw.agentDisplayName ?? raw.agent_display_name ?? null,
      agent_display_name: raw.agent_display_name ?? raw.agentDisplayName ?? null,
      turnNumber: raw.turnNumber ?? raw.turn_number ?? null,
      turn_number: raw.turn_number ?? raw.turnNumber ?? null,
      action: raw.action ?? null,
      tool: raw.tool ?? null,
      inputPayload: raw.inputPayload ?? raw.input_payload,
      input_payload: raw.input_payload ?? raw.inputPayload,
      outputPayload: raw.outputPayload ?? raw.output_payload,
      output_payload: raw.output_payload ?? raw.outputPayload,
      steps: Array.isArray(raw.steps) ? raw.steps : [],
      durationMs: raw.durationMs ?? raw.duration_ms ?? null,
      duration_ms: raw.duration_ms ?? raw.durationMs ?? null,
      tokens: raw.tokens ?? null,
      status: raw.status ?? null,
      errorMessage: raw.errorMessage ?? raw.error_message ?? null,
      error_message: raw.error_message ?? raw.errorMessage ?? null,
      fromStatus: raw.fromStatus ?? raw.from_status ?? null,
      from_status: raw.from_status ?? raw.fromStatus ?? null,
      toStatus: raw.toStatus ?? raw.to_status ?? null,
      to_status: raw.to_status ?? raw.toStatus ?? null,
      actor: raw.actor ?? null,
      reason: raw.reason ?? null,
      createdAt: raw.createdAt ?? raw.created_at ?? null,
      created_at: raw.created_at ?? raw.createdAt ?? null,
    };
  }

  private normalizeReview(raw: any): ReviewGate {
    return {
      id: raw.id,
      taskId: raw.taskId || raw.task_id,
      task_id: raw.task_id || raw.taskId,
      checkpointId: raw.checkpointId ?? raw.checkpoint_id ?? null,
      checkpoint_id: raw.checkpoint_id ?? raw.checkpointId ?? null,
      gateType: raw.gateType || raw.gate_type || "hil",
      gate_type: raw.gate_type || raw.gateType || "hil",
      status: raw.status || "pending",
      decision: raw.decision ?? null,
      feedbackText: raw.feedbackText ?? raw.feedback_text ?? null,
      feedback_text: raw.feedback_text ?? raw.feedbackText ?? null,
      actor: raw.actor ?? null,
      summary: raw.summary ?? null,
      payload: raw.payload ?? null,
      editedContent: raw.editedContent ?? raw.edited_content ?? null,
      edited_content: raw.edited_content ?? raw.editedContent ?? null,
      expiresAt: raw.expiresAt ?? raw.expires_at ?? null,
      expires_at: raw.expires_at ?? raw.expiresAt ?? null,
      decidedAt: raw.decidedAt ?? raw.decided_at ?? null,
      decided_at: raw.decided_at ?? raw.decidedAt ?? null,
      createdAt: raw.createdAt ?? raw.created_at ?? null,
      created_at: raw.created_at ?? raw.createdAt ?? null,
    };
  }

  private normalizeAgent(raw: any): Agent {
    return {
      id: raw.id,
      name: raw.name,
      displayName: raw.displayName || raw.display_name || raw.name,
      display_name: raw.display_name || raw.displayName || raw.name,
      role: raw.role || "Chuyên viên AI",
      description: raw.description,
      avatar: raw.avatar,
      systemPrompt: raw.systemPrompt || raw.system_prompt,
      system_prompt: raw.system_prompt || raw.systemPrompt,
      departmentId: raw.departmentId || raw.department_id,
      department_id: raw.department_id || raw.departmentId,
      defaultModel: raw.defaultModel || raw.default_model,
      default_model: raw.default_model || raw.defaultModel,
      primaryModel: raw.primaryModel || raw.primary_model,
      primary_model: raw.primary_model || raw.primaryModel,
      fallbackModel: raw.fallbackModel || raw.fallback_model,
      fallback_model: raw.fallback_model || raw.fallbackModel,
      temperature: raw.temperature,
      maxTokens: raw.maxTokens || raw.max_tokens,
      max_tokens: raw.max_tokens || raw.maxTokens,
      status: raw.status || "idle",
      isSystem: raw.isSystem ?? raw.is_system ?? false,
      is_system: raw.is_system ?? raw.isSystem ?? false,
      skillsCount: raw.skillsCount ?? raw.skills_count ?? (raw.skill_ids?.length || 0),
      skills_count: raw.skills_count ?? raw.skillsCount ?? (raw.skill_ids?.length || 0),
      skillIds: raw.skillIds || raw.skill_ids || [],
      skill_ids: raw.skill_ids || raw.skillIds || [],
      createdAt: raw.createdAt || raw.created_at,
      created_at: raw.created_at || raw.createdAt,
      updatedAt: raw.updatedAt || raw.updated_at,
      updated_at: raw.updated_at || raw.updatedAt,
    };
  }

  // ---------------------------------------------------------------------------
  // Brain, Brand Profile, Product Catalog & Knowledge Management (Task 4.2)
  // ---------------------------------------------------------------------------

  public async getBrandProfile(
    projectId: string = "proj-default"
  ): Promise<{ profile: BrandProfile; templates: BrandTemplate[] }> {
    return this.request<{ profile: BrandProfile; templates: BrandTemplate[] }>(
      `/api/v1/brain/brand-profile?project_id=${encodeURIComponent(projectId)}`
    );
  }

  public async updateBrandProfile(payload: Partial<BrandProfile>): Promise<BrandProfile> {
    return this.request<BrandProfile>("/api/v1/brain/brand-profile", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  }

  public async getProducts(
    projectId: string = "proj-default",
    activeOnly: boolean = false
  ): Promise<ProductItem[]> {
    return this.request<ProductItem[]>(
      `/api/v1/brain/products?project_id=${encodeURIComponent(projectId)}&active_only=${activeOnly}`
    );
  }

  public async upsertProduct(payload: Partial<ProductItem>): Promise<ProductItem> {
    return this.request<ProductItem>("/api/v1/brain/products", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  public async deleteProduct(
    productId: string,
    projectId?: string
  ): Promise<{ status: string; product_id: string }> {
    const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
    return this.request<{ status: string; product_id: string }>(
      `/api/v1/brain/products/${encodeURIComponent(productId)}${query}`,
      { method: "DELETE" }
    );
  }

  public async getProductPriceHistory(
    productId: string,
    projectId?: string
  ): Promise<PriceHistoryItem[]> {
    const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
    return this.request<PriceHistoryItem[]>(
      `/api/v1/brain/products/${encodeURIComponent(productId)}/history${query}`
    );
  }

  public async importProductsCsv(
    fileOrContent: File | string,
    projectId: string = "proj-default"
  ): Promise<CsvImportResult> {
    const url = `/api/v1/brain/products/import-csv?project_id=${encodeURIComponent(projectId)}`;
    if (typeof fileOrContent === "string") {
      return this.request<CsvImportResult>(url, {
        method: "POST",
        body: JSON.stringify({ csv_content: fileOrContent }),
      });
    }

    const formData = new FormData();
    formData.append("file", fileOrContent);
    const headers: Record<string, string> = {};
    const token = this.resolveToken();
    if (token) {
      headers["X-Local-Auth-Token"] = token;
    }
    const resp = await fetch(`${this.baseUrl}${url}`, {
      method: "POST",
      headers,
      body: formData,
    });
    if (!resp.ok) {
      const errJson = await resp.json().catch(() => null);
      throw new ApiError(
        errJson?.detail || "Import CSV thất bại",
        resp.status,
        errJson
      );
    }
    return resp.json();
  }

  public async listBrainDocuments(collection?: string): Promise<BrainDocumentItem[]> {
    const query = collection ? `?collection=${encodeURIComponent(collection)}` : "";
    return this.request<BrainDocumentItem[]>(`/api/v1/brain/documents${query}`);
  }

  public async deleteBrainDocument(docId: string): Promise<{ status: string; doc_id: string }> {
    return this.request<{ status: string; doc_id: string }>(
      `/api/v1/brain/documents/${encodeURIComponent(docId)}`,
      { method: "DELETE" }
    );
  }

  public async searchBrain(
    query: string,
    collections: string[] = ["default"],
    topK: number = 5,
    minSimilarity: number = 0.7
  ): Promise<SemanticSearchHit[]> {
    return this.request<SemanticSearchHit[]>("/api/v1/brain/search", {
      method: "POST",
      body: JSON.stringify({
        query,
        collections,
        top_k: topK,
        min_similarity: minSimilarity,
      }),
    });
  }

  public async uploadBrainDocument(file: File, collection: string = "default"): Promise<any> {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("collection", collection);

    const headers: Record<string, string> = {};
    const token = this.resolveToken();
    if (token) {
      headers["X-Local-Auth-Token"] = token;
    }

    const resp = await fetch(`${this.baseUrl}/api/v1/brain/documents`, {
      method: "POST",
      headers,
      body: formData,
    });

    if (!resp.ok) {
      const errJson = await resp.json().catch(() => null);
      throw new ApiError(
        errJson?.detail || "Tải tài liệu thất bại",
        resp.status,
        errJson
      );
    }
    return resp.json();
  }

  // --- Task 4.6: Multi-channel Messaging & Inbox Endpoints ---

  public async getConversations(filter?: {
    status?: string;
    channel?: string;
    project_id?: string;
  }): Promise<InboxConversation[]> {
    const params = new URLSearchParams();
    if (filter?.status) params.set("status", filter.status);
    if (filter?.channel) params.set("channel", filter.channel);
    if (filter?.project_id) params.set("project_id", filter.project_id);
    const qs = params.toString() ? `?${params.toString()}` : "";
    return this.request<InboxConversation[]>(`/api/v1/inbox/conversations${qs}`);
  }

  public async getConversation(convId: string): Promise<InboxConversation> {
    return this.request<InboxConversation>(`/api/v1/inbox/conversations/${encodeURIComponent(convId)}`);
  }

  public async getConversationMessages(convId: string): Promise<InboxMessage[]> {
    return this.request<InboxMessage[]>(`/api/v1/inbox/conversations/${encodeURIComponent(convId)}/messages`);
  }

  public async takeoverConversation(convId: string): Promise<{ success: boolean; conversation: InboxConversation }> {
    return this.request<{ success: boolean; conversation: InboxConversation }>(
      `/api/v1/inbox/conversations/${encodeURIComponent(convId)}/takeover`,
      { method: "POST" }
    );
  }

  public async releaseConversation(convId: string): Promise<{ success: boolean; conversation: InboxConversation }> {
    return this.request<{ success: boolean; conversation: InboxConversation }>(
      `/api/v1/inbox/conversations/${encodeURIComponent(convId)}/release`,
      { method: "POST" }
    );
  }

  public async sendOperatorReply(
    convId: string,
    content: string,
    attachments?: any[]
  ): Promise<InboxMessage> {
    return this.request<InboxMessage>(
      `/api/v1/inbox/conversations/${encodeURIComponent(convId)}/reply`,
      {
        method: "POST",
        body: JSON.stringify({ content, attachments }),
      }
    );
  }

  public async getConnectorsStatus(): Promise<ConnectorStatus[]> {
    return this.request<ConnectorStatus[]>("/api/v1/inbox/connectors/status");
  }
}

export const defaultApiClient = new ApiClient();
