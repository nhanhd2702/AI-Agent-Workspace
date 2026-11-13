"""SQLAlchemy ORM models for AI Agent Workspace (Văn Phòng AI).

Defines all 19 persistence entities:
1. Project
2. Department
3. Agent
4. Skill
5. AgentSkill
6. Task
7. SubTask
8. TurnLog
9. Artifact
10. ReviewGate
11. UsageRecord
12. BrandProfile
13. Product
14. Conversation
15. Message
16. ConnectorConfig
17. UserSettings
18. TaskAuditLog
19. FileAsset
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""
    pass


class TaskStatus(str, enum.Enum):
    """Lifecycle states for Task according to BA spec F01.4."""
    PENDING = "pending"
    RUNNING = "running"
    WAITING_REVIEW = "waiting_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    DELIVERED = "delivered"
    COMPLETED = "completed"
    PAUSED = "paused"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Project(Base):
    """High-level workspace project or tenant."""
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tags: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True)
    default_department_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    tasks: Mapped[list["Task"]] = relationship("Task", back_populates="project", cascade="all, delete-orphan")
    brand_profiles: Mapped[list["BrandProfile"]] = relationship("BrandProfile", back_populates="project", cascade="all, delete-orphan")
    products: Mapped[list["Product"]] = relationship("Product", back_populates="project", cascade="all, delete-orphan")
    conversations: Mapped[list["Conversation"]] = relationship("Conversation", back_populates="project", cascade="all, delete-orphan")


class Department(Base):
    """Functional department/team grouping agents (e.g. Đội Content, Đội Funnels)."""
    __tablename__ = "departments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    icon: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    color: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    agents: Mapped[list["Agent"]] = relationship("Agent", back_populates="department")


class Agent(Base):
    """Core AI Agent in registry with specialized system prompt and default model."""
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(String(128), nullable=False)
    avatar: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    department_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("departments.id", ondelete="SET NULL"), nullable=True
    )
    default_model: Mapped[str] = mapped_column(String(64), default="gemini-2.5-flash")
    fallback_model: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    temperature: Mapped[float] = mapped_column(Float, default=0.7)
    max_tokens: Mapped[int] = mapped_column(Integer, default=4096)
    status: Mapped[str] = mapped_column(String(32), default="idle")
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    config: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    department: Mapped[Optional["Department"]] = relationship("Department", back_populates="agents")
    skills: Mapped[list["AgentSkill"]] = relationship("AgentSkill", back_populates="agent", cascade="all, delete-orphan")
    tasks: Mapped[list["Task"]] = relationship("Task", back_populates="assigned_agent")
    usage_records: Mapped[list["UsageRecord"]] = relationship("UsageRecord", back_populates="agent")


class Skill(Base):
    """Skill package containing specialized SKILL.md prompt and allowed tools."""
    __tablename__ = "skills"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    allowed_tools: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    agents: Mapped[list["AgentSkill"]] = relationship("AgentSkill", back_populates="skill", cascade="all, delete-orphan")


class AgentSkill(Base):
    """Many-to-many binding between Agent and Skill with custom parameters."""
    __tablename__ = "agent_skills"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    skill_id: Mapped[str] = mapped_column(String(64), ForeignKey("skills.id", ondelete="CASCADE"), nullable=False)
    custom_params: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    agent: Mapped["Agent"] = relationship("Agent", back_populates="skills")
    skill: Mapped["Skill"] = relationship("Skill", back_populates="agents")


class Task(Base):
    """Master task record managed by Master Commander and tracked via FSM."""
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.id", ondelete="CASCADE"), default="proj-default", nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[TaskStatus] = mapped_column(
        SAEnum(TaskStatus, values_callable=lambda obj: [e.value for e in obj]),
        default=TaskStatus.PENDING,
        nullable=False,
        index=True,
    )
    assigned_agent_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    parent_task_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True
    )
    priority: Mapped[str] = mapped_column(String(32), default="normal")
    task_metadata: Mapped[Optional[dict[str, Any]]] = mapped_column("metadata", JSON, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __init__(self, **kwargs: Any) -> None:
        if "metadata" in kwargs and "task_metadata" not in kwargs:
            kwargs["task_metadata"] = kwargs.pop("metadata")
        super().__init__(**kwargs)

    project: Mapped["Project"] = relationship("Project", back_populates="tasks")
    assigned_agent: Mapped[Optional["Agent"]] = relationship("Agent", back_populates="tasks")
    subtasks: Mapped[list["SubTask"]] = relationship("SubTask", back_populates="task", cascade="all, delete-orphan")
    turn_logs: Mapped[list["TurnLog"]] = relationship("TurnLog", back_populates="task", cascade="all, delete-orphan")
    artifacts: Mapped[list["Artifact"]] = relationship("Artifact", back_populates="task", cascade="all, delete-orphan")
    review_gates: Mapped[list["ReviewGate"]] = relationship("ReviewGate", back_populates="task", cascade="all, delete-orphan")
    audit_logs: Mapped[list["TaskAuditLog"]] = relationship("TaskAuditLog", back_populates="task", cascade="all, delete-orphan")
    usage_records: Mapped[list["UsageRecord"]] = relationship("UsageRecord", back_populates="task")


class SubTask(Base):
    """Sub-task node in DAG execution graph."""
    __tablename__ = "subtasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    agent_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    instruction: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    depends_on: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    task: Mapped["Task"] = relationship("Task", back_populates="subtasks")
    agent: Mapped[Optional["Agent"]] = relationship("Agent")


class TurnLog(Base):
    """Execution turn log for tasks and sub-tasks."""
    __tablename__ = "turn_logs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    subtask_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("subtasks.id", ondelete="SET NULL"), nullable=True)
    agent_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    turn_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    action: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    tool: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    input_payload: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    output_payload: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="completed")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    task: Mapped["Task"] = relationship("Task", back_populates="turn_logs")
    subtask: Mapped[Optional["SubTask"]] = relationship("SubTask")
    agent: Mapped[Optional["Agent"]] = relationship("Agent")


class Artifact(Base):
    """Generated artifact (HTML, PNG, Markdown, MP4, etc.) registered with workspace."""
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    subtask_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("subtasks.id", ondelete="SET NULL"), nullable=True)
    created_by_agent_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    file_type: Mapped[str] = mapped_column(String(32), nullable=False)
    mime_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    category: Mapped[str] = mapped_column(String(32), default="output")
    artifact_metadata: Mapped[Optional[dict[str, Any]]] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __init__(self, **kwargs: Any) -> None:
        if "metadata" in kwargs and "artifact_metadata" not in kwargs:
            kwargs["artifact_metadata"] = kwargs.pop("metadata")
        super().__init__(**kwargs)

    task: Mapped["Task"] = relationship("Task", back_populates="artifacts")
    created_by_agent: Mapped[Optional["Agent"]] = relationship("Agent")


class ReviewGate(Base):
    """Human-in-the-Loop review gate holding execution for user feedback or approval."""
    __tablename__ = "review_gates"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    checkpoint_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    gate_type: Mapped[str] = mapped_column(String(32), default="hil")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    decision: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    feedback_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    actor: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    task: Mapped["Task"] = relationship("Task", back_populates="review_gates")


class UsageRecord(Base):
    """Token consumption and cost calculation record for an LLM call or turn."""
    __tablename__ = "usage_records"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    agent_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    turn_log_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("turn_logs.id", ondelete="SET NULL"), nullable=True)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    is_estimated: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    task: Mapped[Optional["Task"]] = relationship("Task", back_populates="usage_records")
    agent: Mapped[Optional["Agent"]] = relationship("Agent", back_populates="usage_records")


class BrandProfile(Base):
    """Brand identity guidelines injected into Content and Funnels system prompts."""
    __tablename__ = "brand_profiles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.id", ondelete="CASCADE"), default="proj-default", nullable=False
    )
    brand_name: Mapped[str] = mapped_column(String(255), nullable=False)
    tagline: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    target_audience: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tone_of_voice: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    brand_colors: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True)
    fonts: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True)
    legal_boundaries: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    logo_asset_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    project: Mapped["Project"] = relationship("Project", back_populates="brand_profiles")


class Product(Base):
    """Product catalog item with VND pricing and historical price audit trail."""
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("project_id", "sku", name="uq_project_sku"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.id", ondelete="CASCADE"), default="proj-default", nullable=False
    )
    sku: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    price_vnd: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tier_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    short_desc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    full_desc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    deliverables: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True)
    faqs: Mapped[Optional[list[dict[str, str]]]] = mapped_column(JSON, nullable=True)
    policies: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True)
    price_history: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(JSON, default=list, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    project: Mapped["Project"] = relationship("Project", back_populates="products")


class Conversation(Base):
    """Multi-channel conversation thread (Internal, Zalo, Telegram, etc.)."""
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.id", ondelete="CASCADE"), default="proj-default", nullable=False
    )
    channel: Mapped[str] = mapped_column(String(32), default="internal")
    channel_conv_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    participant_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="open")
    is_human_takeover: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    project: Mapped["Project"] = relationship("Project", back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    """Individual chat message within a Conversation."""
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    sender_type: Mapped[str] = mapped_column(String(32), nullable=False)
    sender_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    sender_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    attachments: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(JSON, nullable=True)
    message_metadata: Mapped[Optional[dict[str, Any]]] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    def __init__(self, **kwargs: Any) -> None:
        if "metadata" in kwargs and "message_metadata" not in kwargs:
            kwargs["message_metadata"] = kwargs.pop("metadata")
        super().__init__(**kwargs)

    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="messages")


class ConnectorConfig(Base):
    """External connector configuration and encrypted auth credentials."""
    __tablename__ = "connector_configs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    auth_payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    settings: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="disconnected")
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class UserSettings(Base):
    """Global user preferences, theme, and spending quota limits."""
    __tablename__ = "user_settings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default="settings-default")
    theme: Mapped[str] = mapped_column(String(32), default="dark")
    language: Mapped[str] = mapped_column(String(32), default="vi")
    daily_token_limit: Mapped[int] = mapped_column(Integer, default=1000000)
    daily_usd_limit: Mapped[float] = mapped_column(Float, default=10.0)
    auto_backup: Mapped[bool] = mapped_column(Boolean, default=True)
    preferences: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class TaskAuditLog(Base):
    """Append-only immutable audit log tracking every Task state transition."""
    __tablename__ = "task_audit_logs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_status: Mapped[str] = mapped_column(String(32), nullable=False)
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    task: Mapped["Task"] = relationship("Task", back_populates="audit_logs")


class FileAsset(Base):
    """File asset stored or uploaded in workspace library (F03/F06)."""
    __tablename__ = "file_assets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    task_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    file_type: Mapped[str] = mapped_column(String(32), nullable=False)
    mime_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    category: Mapped[str] = mapped_column(String(32), default="upload")
    file_metadata: Mapped[Optional[dict[str, Any]]] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __init__(self, **kwargs: Any) -> None:
        if "metadata" in kwargs and "file_metadata" not in kwargs:
            kwargs["file_metadata"] = kwargs.pop("metadata")
        super().__init__(**kwargs)

