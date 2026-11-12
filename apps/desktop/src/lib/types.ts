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
  agents?: Agent[];
  createdAt?: string | null;
  created_at?: string | null;
  updatedAt?: string | null;
  updated_at?: string | null;
}

export type TaskStatus =
  | "pending"
  | "running"
  | "waiting_review"
  | "approved"
  | "rejected"
  | "delivered"
  | "completed"
  | "paused"
  | "failed"
  | "cancelled";

export interface Project {
  id: string;
  name: string;
  description?: string | null;
  tags?: string[];
  defaultDepartmentId?: string | null;
  default_department_id?: string | null;
  taskCount?: number;
  task_count?: number;
  statusSummary?: Record<string, number>;
  status_summary?: Record<string, number>;
  createdAt?: string | null;
  created_at?: string | null;
  updatedAt?: string | null;
  updated_at?: string | null;
}

export interface BoardTask {
  id: string;
  projectId?: string;
  project_id?: string;
  title: string;
  description?: string | null;
  status: TaskStatus | string;
  priority?: string;
  assignedAgentId?: string | null;
  assigned_agent_id?: string | null;
  agentName?: string | null;
  agent_name?: string | null;
  agentDisplayName?: string | null;
  agent_display_name?: string | null;
  turnCount?: number;
  turn_count?: number;
  metadata?: Record<string, unknown> | null;
  startedAt?: string | null;
  started_at?: string | null;
  completedAt?: string | null;
  completed_at?: string | null;
  createdAt?: string | null;
  created_at?: string | null;
  updatedAt?: string | null;
  updated_at?: string | null;
}

export interface TaskLogStep {
  id?: string;
  name?: string;
  tool?: string;
  status?: string;
  durationMs?: number;
  duration_ms?: number;
  detail?: string;
  output?: unknown;
}

export interface TaskLogEntry {
  id: string;
  logType?: "turn" | "audit" | string;
  log_type?: "turn" | "audit" | string;
  taskId?: string;
  task_id?: string;
  subtaskId?: string | null;
  subtask_id?: string | null;
  agentId?: string | null;
  agent_id?: string | null;
  agentName?: string | null;
  agent_name?: string | null;
  agentDisplayName?: string | null;
  agent_display_name?: string | null;
  turnNumber?: number | null;
  turn_number?: number | null;
  action?: string | null;
  tool?: string | null;
  inputPayload?: unknown;
  input_payload?: unknown;
  outputPayload?: unknown;
  output_payload?: unknown;
  steps?: TaskLogStep[];
  durationMs?: number | null;
  duration_ms?: number | null;
  tokens?: number | null;
  status?: string | null;
  errorMessage?: string | null;
  error_message?: string | null;
  fromStatus?: string | null;
  from_status?: string | null;
  toStatus?: string | null;
  to_status?: string | null;
  actor?: string | null;
  reason?: string | null;
  createdAt?: string | null;
  created_at?: string | null;
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
