import {
  Agent,
  ApiError,
  ApiResponse,
  ExecutionMode,
  ParsedTask,
  ReviewDecidePayload,
  ReviewDecision,
  ReviewGate,
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
}

export const defaultApiClient = new ApiClient();
