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

export interface StoryboardSceneData {
  sceneId: string;
  scene_id?: string;
  start?: number;
  end?: number;
  durationSec?: number;
  duration?: number;
  overlayText: string;
  overlay_text?: string;
  effect: string;
  visualNotes?: string;
  visual_notes?: string;
  transition?: string;
  startSec?: number;
  endSec?: number;
}

export interface StoryboardData {
  styleName?: string;
  style_name?: string;
  totalDuration?: number;
  total_duration?: number;
  sceneCount?: number;
  scene_count?: number;
  warnings?: string[];
  pacing_warnings?: string[];
  scenes: StoryboardSceneData[];
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

// -----------------------------------------------------------------------------
// Brain, Brand Profile & Product Catalog Domain Types (Task 4.2)
// -----------------------------------------------------------------------------

export interface BrandTemplate {
  id: string;
  name: string;
  tagline?: string;
  tone_of_voice: string;
  legal_boundaries: string;
  target_audience?: string;
  brand_colors?: string[];
  fonts?: string[];
}

export interface BrandProfile {
  id: string;
  project_id?: string;
  brand_name: string;
  tagline?: string | null;
  target_audience?: string | null;
  tone_of_voice?: string | null;
  brand_colors?: string[];
  fonts?: string[];
  legal_boundaries?: string | null;
  logo_asset_id?: string | null;
  is_active?: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface PriceHistoryItem {
  price_vnd: number;
  recorded_at: string;
  reason: "initial" | "update" | string;
}

export interface ProductItem {
  id: string;
  project_id?: string;
  sku: string;
  name: string;
  price_vnd: number;
  tier_type?: string | null;
  short_desc?: string | null;
  full_desc?: string | null;
  deliverables?: string[];
  faqs?: Array<{ q?: string; a?: string; question?: string; answer?: string }>;
  policies?: string[];
  price_history?: PriceHistoryItem[];
  is_active?: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface CsvImportError {
  row: number;
  sku: string;
  error: string;
}

export interface CsvImportResult {
  imported_count: number;
  errors: CsvImportError[];
}

export interface BrainDocumentItem {
  doc_id: string;
  filename: string;
  collection: string;
  chunk_count: number;
  total_chars?: number;
  sha256?: string;
  ingested_at?: string;
}

export interface SemanticSearchHit {
  chunk_id: string;
  doc_id: string;
  doc_title: string;
  collection: string;
  text: string;
  score: number;
  page?: number | null;
}

export interface InboxMessage {
  id: string;
  conversation_id: string;
  sender_type: "customer" | "agent" | "human" | "system" | string;
  sender_id?: string | null;
  sender_name?: string | null;
  content: string;
  attachments?: any[];
  metadata?: Record<string, any>;
  created_at?: string;
}

export interface InboxConversation {
  id: string;
  project_id: string;
  channel: "zalo" | "telegram" | "internal" | string;
  channel_conv_id?: string | null;
  title?: string | null;
  participant_name?: string | null;
  status: "open" | "waiting" | "in_progress" | "closed" | string;
  is_human_takeover: boolean;
  created_at?: string;
  updated_at?: string;
  last_message?: {
    id: string;
    sender_type: string;
    sender_name?: string | null;
    content: string;
    created_at?: string;
  } | null;
  unread_count?: number;
}

export interface ConnectorStatus {
  id: string;
  name: string;
  provider: "zalo" | "telegram" | "internal" | string;
  status: "connected" | "disconnected" | "expired" | "needs_reauth" | string;
  is_enabled: boolean;
  last_sync_at?: string | null;
  qr_code_url?: string | null;
}

// --- Task 5.1: Settings, LLM Providers & Connector Health Types ---

export interface LlmProviderConfig {
  provider: string;
  name: string;
  has_key: boolean;
  masked_key: string;
  default_model: string;
  base_url?: string | null;
  is_enabled: boolean;
  status: "connected" | "disconnected" | "disabled" | string;
  updated_at?: string | null;
}

export interface LlmProviderUpdatePayload {
  provider: string;
  api_key?: string | null;
  default_model?: string | null;
  base_url?: string | null;
  is_enabled?: boolean;
}

export interface LlmTestResult {
  success: boolean;
  provider: string;
  model?: string;
  latency_ms?: number;
  message: string;
}

export interface ConnectorHealthItem {
  id: string;
  name: string;
  category: "runtime" | "storage" | "external" | string;
  healthy: boolean;
  status: "ready" | "connected" | "disconnected" | "missing" | "error" | string;
  message?: string | null;
  details?: Record<string, any> | null;
  last_checked: string;
}

export interface UserProfileSettings {
  id: string;
  theme: "dark" | "light" | "system" | string;
  language: "vi" | "en" | string;
  daily_token_limit: number;
  daily_usd_limit: number;
  auto_backup: boolean;
  preferences?: Record<string, any>;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface ProfileUpdatePayload {
  theme?: string;
  language?: string;
  daily_token_limit?: number;
  daily_usd_limit?: number;
  auto_backup?: boolean;
  preferences?: Record<string, any>;
}

export interface AgentUsageStat {
  agent_id: string;
  agent_name: string;
  requests: number;
  tokens: number;
  total_tokens?: number;
  cost_usd: number;
  percentage?: number;
}

export interface ModelUsageStat {
  model_name: string;
  requests: number;
  tokens: number;
  total_tokens?: number;
  cost_usd: number;
}

export interface DailyTrendItem {
  date: string;
  tokens: number;
  cost_usd: number;
  requests: number;
}

export interface TaskStatsItem {
  total: number;
  total_tasks?: number;
  completed: number;
  completed_tasks?: number;
  failed: number;
  failed_tasks?: number;
  in_progress: number;
  success_rate_pct: number;
}

export interface QuotaStatusItem {
  daily_limit_usd: number;
  spent_today_usd: number;
  remaining_today_usd?: number;
  percentage_used?: number;
  warning_triggered: boolean;
  exceeded: boolean;
  daily_token_limit?: number;
  tokens_spent_today?: number;
}

export interface MonitoringDashboardData {
  period: "today" | "7d" | "30d" | "all" | string;
  total_tokens: number;
  total_cost_usd: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_requests: number;
  by_agent: AgentUsageStat[];
  by_model: ModelUsageStat[];
  daily_trends: DailyTrendItem[];
  task_stats: TaskStatsItem;
  quota?: QuotaStatusItem;
}




