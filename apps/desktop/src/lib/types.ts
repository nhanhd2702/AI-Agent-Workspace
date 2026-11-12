/**
 * Core domain types and API contracts for AI Agent Workspace desktop client.
 * Aligned with backend FastAPI endpoints and database schemas.
 */

export type ExecutionMode = "autopilot" | "copilot";

export type AgentStatus = "idle" | "busy" | "disabled" | string;

export interface Agent {
  id: string;
  name: string;
  displayName?: string;
  display_name?: string;
  role?: string;
  description?: string | null;
  avatar?: string | null;
  systemPrompt?: string | null;
  system_prompt?: string | null;
  departmentId?: string | null;
  department_id?: string | null;
  defaultModel?: string | null;
  default_model?: string | null;
  primaryModel?: string | null;
  primary_model?: string | null;
  fallbackModel?: string | null;
  fallback_model?: string | null;
  temperature?: number;
  maxTokens?: number;
  max_tokens?: number;
  status?: AgentStatus;
  isSystem?: boolean;
  is_system?: boolean;
  skillsCount?: number;
  skills_count?: number;
  skillIds?: string[];
  skill_ids?: string[];
  createdAt?: string | null;
  created_at?: string | null;
  updatedAt?: string | null;
  updated_at?: string | null;
}

export interface Department {
  id: string;
  name: string;
  description?: string | null;
  icon?: string | null;
  color?: string | null;
  status: "active" | "inactive" | string;
  agentsCount?: number;
  agents_count?: number;
  createdAt?: string | null;
  created_at?: string | null;
  updatedAt?: string | null;
  updated_at?: string | null;
}

export interface AttachmentItem {
  id: string;
  name: string;
  size?: number;
  type?: string;
  path?: string;
  file?: File;
}

export interface ParsedTask {
  taskId: string;
  task_id?: string;
  intent: string;
  taskType: string;
  task_type?: string;
  mentionedAgents: string[];
  mentioned_agents?: string[];
  urls: string[];
  attachmentIds: string[];
  attachment_ids?: string[];
  entities: Record<string, unknown>;
  plan?: unknown | null;
}

export type TimeGroup = "today" | "yesterday" | "past7days" | "older";

export interface SidebarTaskItem {
  id: string;
  title: string;
  status?: "pending" | "running" | "waiting_review" | "approved" | "delivered" | "completed" | "failed" | string;
  createdAt?: string | Date;
  group?: TimeGroup;
}

export type ReviewDecision = "approve" | "edit" | "reject";

export interface ReviewGate {
  id: string;
  taskId?: string;
  task_id?: string;
  checkpointId?: string | null;
  checkpoint_id?: string | null;
  gateType?: string;
  gate_type?: string;
  status?: "pending" | "approved" | "edited" | "rejected" | "expired" | string;
  decision?: ReviewDecision | string | null;
  feedbackText?: string | null;
  feedback_text?: string | null;
  actor?: string | null;
  summary?: string | null;
  payload?: unknown;
  editedContent?: string | Record<string, unknown> | unknown | null;
  edited_content?: string | Record<string, unknown> | unknown | null;
  expiresAt?: string | null;
  expires_at?: string | null;
  decidedAt?: string | null;
  decided_at?: string | null;
  createdAt?: string | null;
  created_at?: string | null;
}

export interface ReviewDecidePayload {
  feedbackText?: string;
  editedContent?: string;
  actor?: string;
}

export interface ApiResponse<T> {
  status: "success" | "error";
  data: T;
  detail?: string;
}

export class ApiError extends Error {
  statusCode: number;
  detail?: string | unknown;

  constructor(message: string, statusCode: number, detail?: string | unknown) {
    super(message);
    this.name = "ApiError";
    this.statusCode = statusCode;
    this.detail = detail;
  }
}
