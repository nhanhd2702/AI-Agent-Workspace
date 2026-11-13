"""Cycle-checked DAG Task Planner for Master Commander (F01.2 / F01.3).

Decomposes ParsedIntent into <= 10 SubTaskNodes organized as a validated
directed acyclic graph (DAG) with Kahn's topological sort and parallel wave grouping.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional
import uuid

from app.orchestrator.parser import ParsedIntent


class DagCycleError(ValueError):
    """Raised when a DAG contains a self-loop or multi-node cycle."""


@dataclass
class SubTaskNode:
    """Single node in a task execution DAG."""

    id: str
    agent_id: str
    instruction: str
    depends_on: list[str] = field(default_factory=list)
    requires_review: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize node into a JSON/checkpoint-safe dictionary."""
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "instruction": self.instruction,
            "depends_on": list(self.depends_on),
            "requires_review": self.requires_review,
            "metadata": dict(self.metadata),
        }


@dataclass
class ExecutionPlan:
    """Validated DAG execution plan with topological node order and parallel waves."""

    task_id: str
    task_type: str
    nodes: list[SubTaskNode]
    waves: list[list[str]]
    mode: str = "autopilot"

    def to_dict(self) -> dict[str, Any]:
        """Serialize execution plan into a JSON/checkpoint-safe dictionary."""
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "mode": self.mode,
            "nodes": [n.to_dict() for n in self.nodes],
            "waves": [list(w) for w in self.waves],
        }


# Template steps: (step_key, canonical_agent_name, instruction_template, depends_on_keys, copilot_review_gate)
_TASK_TYPE_TEMPLATES: dict[str, list[tuple[str, str, str, list[str], bool]]] = {
    "content_research": [
        (
            "collect",
            "DeepResearcher",
            "Thu thập và phân tích dữ liệu nguồn, đối thủ & xu hướng cho: {goal}",
            [],
            False,
        ),
        (
            "draft",
            "ContentWriter",
            "Tổng hợp insight và soạn thảo nội dung bài viết cho: {goal}",
            ["collect"],
            True,
        ),
        (
            "visual",
            "ImageStudio",
            "Thiết kế hình ảnh và ấn phẩm đồ họa kèm theo cho: {goal}",
            ["draft"],
            False,
        ),
    ],
    "copywriting": [
        (
            "angle",
            "DeepResearcher",
            "Nghiên cứu insight đối tượng mục tiêu và góc tiếp cận cho: {goal}",
            [],
            False,
        ),
        (
            "draft",
            "ContentWriter",
            "Soạn thảo nội dung/kịch bản chính chuẩn văn phong thương hiệu cho: {goal}",
            ["angle"],
            True,
        ),
        (
            "polish",
            "ContentWriter",
            "Tối ưu tiêu đề, hook mở đầu và CTA chuyển đổi cho: {goal}",
            ["draft"],
            False,
        ),
    ],
    "image_design": [
        (
            "brief",
            "ContentWriter",
            "Xây dựng brief thông điệp, bố cục chữ và thông số kích thước cho: {goal}",
            [],
            False,
        ),
        (
            "render",
            "ImageStudio",
            "Thiết kế ấn phẩm đồ họa HTML/CSS/SVG trực quan cho: {goal}",
            ["brief"],
            True,
        ),
    ],
    "video_edit": [
        (
            "storyboard",
            "ContentWriter",
            "Lên kịch bản phân cảnh và storyboard chi tiết cho: {goal}",
            [],
            True,
        ),
        (
            "assets",
            "ImageStudio",
            "Chuẩn bị thumbnail và graphic overlay cho từng phân cảnh: {goal}",
            ["storyboard"],
            False,
        ),
        (
            "assemble",
            "VideoEditor",
            "Biên tập timeline, kiểm tra nhịp điệu pacing và dựng video hoàn chỉnh cho: {goal}",
            ["storyboard", "assets"],
            False,
        ),
    ],
    "funnel_strategy": [
        (
            "funnel",
            "FunnelsAgent",
            "Thiết kế kiến trúc phễu bán hàng đa tầng và luồng chuyển đổi cho: {goal}",
            [],
            False,
        ),
        (
            "growth",
            "GrowthAdvisor",
            "Tối ưu cơ chế upsell/downsell, định giá và KPI tăng trưởng cho: {goal}",
            ["funnel"],
            True,
        ),
        (
            "landing",
            "UIDesigner",
            "Xây dựng trang landing page HTML responsive offline cho: {goal}",
            ["growth"],
            False,
        ),
    ],
    "landing_page": [
        (
            "copy",
            "ContentWriter",
            "Viết nội dung các section (Hero, Lợi ích, Social Proof, FAQ, CTA) cho: {goal}",
            [],
            False,
        ),
        (
            "wireframe",
            "FunnelsAgent",
            "Thiết kế cấu trúc chuyển đổi và wireframe landing page cho: {goal}",
            [],
            False,
        ),
        (
            "visuals",
            "ImageStudio",
            "Thiết kế visual minh họa và banner tương thích giao diện cho: {goal}",
            ["wireframe"],
            False,
        ),
        (
            "build",
            "UIDesigner",
            "Xây dựng trang landing page HTML/CSS responsive offline cho: {goal}",
            ["copy", "visuals"],
            True,
        ),
    ],
    "sales_chat": [
        (
            "catalog",
            "ProductAnalyst",
            "Trích xuất thông số sản phẩm, bảng giá và chính sách liên quan cho: {goal}",
            [],
            False,
        ),
        (
            "script",
            "SalesAgent",
            "Soạn kịch bản tư vấn bán hàng, xử lý từ chối và chốt đơn cho: {goal}",
            ["catalog"],
            True,
        ),
        (
            "support",
            "CustomerSupportAgent",
            "Bổ sung hướng dẫn chăm sóc sau bán và giải đáp thắc mắc cho: {goal}",
            ["script"],
            False,
        ),
    ],
    "general": [
        (
            "coordinate",
            "Commander",
            "Phân tích mục tiêu tổng thể và phân công đầu việc cho: {goal}",
            [],
            False,
        ),
        (
            "deliver",
            "ReportAgent",
            "Tổng hợp kết quả thực thi và hoàn thiện báo cáo cho: {goal}",
            ["coordinate"],
            True,
        ),
    ],
}


class DagPlanner:
    """Validates and constructs cycle-free execution DAGs capped at 10 nodes."""

    MAX_NODES = 10

    @classmethod
    def validate_dag(cls, nodes: list[SubTaskNode]) -> list[SubTaskNode]:
        """Validate DAG constraints and return nodes in Kahn's topological order.

        Raises:
            ValueError: If >10 nodes, blank/duplicate IDs, or unknown dependencies exist.
            DagCycleError: If a self-loop or multi-node cycle exists.
        """
        if len(nodes) > cls.MAX_NODES:
            raise ValueError(
                f"DAG exceeds maximum limit of {cls.MAX_NODES} nodes (got {len(nodes)})"
            )

        if not nodes:
            return []

        node_map: dict[str, SubTaskNode] = {}
        order_index: dict[str, int] = {}
        for idx, node in enumerate(nodes):
            if not node.id or not node.id.strip():
                raise ValueError("Node id must not be empty")
            if node.id in node_map:
                raise ValueError(f"Duplicate node id '{node.id}' in DAG")
            node_map[node.id] = node
            order_index[node.id] = idx

        # Validate dependency targets & self-loops, build adjacency graph
        dependents: dict[str, list[str]] = {n.id: [] for n in nodes}
        in_degree: dict[str, int] = {}

        for node in nodes:
            seen_deps: set[str] = set()
            for dep in node.depends_on:
                if dep == node.id:
                    raise DagCycleError(f"Self-loop detected on node '{node.id}'")
                if dep not in node_map:
                    raise ValueError(
                        f"Node '{node.id}' depends on unknown node '{dep}'"
                    )
                if dep not in seen_deps:
                    seen_deps.add(dep)
                    dependents[dep].append(node.id)
            in_degree[node.id] = len(seen_deps)

        # Kahn's topological sort preserving deterministic input order
        queue: deque[str] = deque(
            n.id for n in nodes if in_degree[n.id] == 0
        )
        ordered: list[SubTaskNode] = []

        while queue:
            current_id = queue.popleft()
            ordered.append(node_map[current_id])
            for child_id in dependents[current_id]:
                in_degree[child_id] -= 1
                if in_degree[child_id] == 0:
                    queue.append(child_id)

        if len(ordered) != len(nodes):
            cycle_nodes = sorted(nid for nid, deg in in_degree.items() if deg > 0)
            raise DagCycleError(
                f"Cycle detected in DAG involving nodes: {cycle_nodes}"
            )

        return ordered

    @classmethod
    def compute_waves(cls, nodes: list[SubTaskNode]) -> list[list[str]]:
        """Group validated DAG nodes into parallel execution waves (BFS levels)."""
        ordered = cls.validate_dag(nodes)
        if not ordered:
            return []

        wave_index_by_id: dict[str, int] = {}
        for node in ordered:
            if not node.depends_on:
                wave_index_by_id[node.id] = 0
            else:
                wave_index_by_id[node.id] = (
                    max(wave_index_by_id[dep] for dep in node.depends_on) + 1
                )

        max_wave = max(wave_index_by_id.values())
        waves: list[list[str]] = [[] for _ in range(max_wave + 1)]
        for node in ordered:
            waves[wave_index_by_id[node.id]].append(node.id)
        return waves

    @classmethod
    def _build_agent_lookup(cls, agents: Iterable[Any]) -> dict[str, tuple[str, str]]:
        """Map lower-case agent name/id -> (agent_id, agent_name) safely."""
        lookup: dict[str, tuple[str, str]] = {}
        for agent in agents or []:
            agent_id = getattr(agent, "id", None)
            agent_name = getattr(agent, "name", None)
            if isinstance(agent, dict):
                agent_id = agent.get("id")
                agent_name = agent.get("name")
            if agent_id and agent_name:
                pair = (str(agent_id), str(agent_name))
                lookup[str(agent_name).lower()] = pair
                lookup[str(agent_id).lower()] = pair
        return lookup

    @classmethod
    def _resolve_agent(
        cls,
        canonical_name: str,
        lookup: dict[str, tuple[str, str]],
    ) -> tuple[str, str]:
        """Resolve canonical agent name to (agent_id, agent_name) with graceful fallback."""
        match = lookup.get(canonical_name.lower())
        if match:
            return match
        return (canonical_name, canonical_name)

    @classmethod
    def build_plan(
        cls,
        intent: ParsedIntent,
        agents: list[Any],
        task_id: Optional[str] = None,
        mode: str = "autopilot",
    ) -> ExecutionPlan:
        """Build and validate a multi-step DAG ExecutionPlan from ParsedIntent."""
        normalized_mode = (mode or "autopilot").strip().lower()
        if normalized_mode not in {"autopilot", "copilot"}:
            raise ValueError(
                f"Invalid mode '{mode}': expected 'autopilot' or 'copilot'"
            )

        resolved_task_id = task_id or f"task-{uuid.uuid4().hex[:12]}"
        task_type = intent.task_type if intent.task_type in _TASK_TYPE_TEMPLATES else "general"
        template = _TASK_TYPE_TEMPLATES[task_type]
        lookup = cls._build_agent_lookup(agents)

        goal_summary = intent.cleaned_prompt or intent.raw_prompt
        if intent.urls:
            goal_summary = f"{goal_summary} (nguồn: {', '.join(intent.urls)})"

        nodes: list[SubTaskNode] = []
        for step_key, agent_slug, instr_tpl, deps, is_gate in template:
            resolved_id, resolved_name = cls._resolve_agent(agent_slug, lookup)
            nodes.append(
                SubTaskNode(
                    id=step_key,
                    agent_id=resolved_id,
                    instruction=instr_tpl.format(goal=goal_summary),
                    depends_on=list(deps),
                    requires_review=bool(is_gate and normalized_mode == "copilot"),
                    metadata={
                        "agent_name": resolved_name,
                        "task_type": task_type,
                        "output_format": intent.entities.get("output_format"),
                        "target_count": intent.entities.get("target_count"),
                    },
                )
            )

        # Ensure every @mentioned agent is represented in the DAG without exceeding 10 nodes
        if intent.mentioned_agents:
            for idx, mentioned in enumerate(intent.mentioned_agents):
                m_id, m_name = cls._resolve_agent(mentioned, lookup)
                assigned_names = {
                    str(n.metadata.get("agent_name", n.agent_id)).lower() for n in nodes
                }
                assigned_ids = {n.agent_id.lower() for n in nodes}
                if m_name.lower() in assigned_names or m_id.lower() in assigned_ids:
                    continue

                if idx == 0 and nodes:
                    # Assign primary mentioned agent to the first execution node
                    nodes[0].agent_id = m_id
                    nodes[0].metadata["agent_name"] = m_name
                elif len(nodes) < cls.MAX_NODES:
                    # Append specialized parallel/final collaboration step depending on previous leaf
                    leaf_ids = [
                        n.id
                        for n in nodes
                        if not any(n.id in other.depends_on for other in nodes)
                    ]
                    new_node_id = f"collab_{idx}"
                    nodes.append(
                        SubTaskNode(
                            id=new_node_id,
                            agent_id=m_id,
                            instruction=f"Phối hợp chuyên môn @{m_name} hoàn thiện đầu ra cho: {goal_summary}",
                            depends_on=leaf_ids,
                            requires_review=False,
                            metadata={
                                "agent_name": m_name,
                                "task_type": task_type,
                                "mentioned": True,
                            },
                        )
                    )

        # Enforce hard 10-node ceiling before validation
        nodes = nodes[: cls.MAX_NODES]
        ordered = cls.validate_dag(nodes)
        waves = cls.compute_waves(ordered)

        return ExecutionPlan(
            task_id=resolved_task_id,
            task_type=task_type,
            nodes=ordered,
            waves=waves,
            mode=normalized_mode,
        )
