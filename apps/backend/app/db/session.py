"""SQLite database initialization, session factory management, and idempotent default seeder."""

from __future__ import annotations

from pathlib import Path
from typing import Generator, Optional

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from app.db.models import (
    Agent,
    Base,
    Department,
    Project,
    UserSettings,
)

# Standard 5 departments according to BA spec F02.3
DEFAULT_DEPARTMENTS = [
    {
        "id": "dept-content",
        "name": "Đội Content",
        "description": "Sáng tạo nội dung đa kênh, viết bài, kịch bản, video & hình ảnh",
        "icon": "pen-tool",
        "color": "#3B82F6",
    },
    {
        "id": "dept-funnels",
        "name": "Đội Funnels",
        "description": "Thiết kế phễu bán hàng, landing page, tối ưu tỷ lệ chuyển đổi",
        "icon": "git-merge",
        "color": "#8B5CF6",
    },
    {
        "id": "dept-rd",
        "name": "Nghiên cứu & Phát triển",
        "description": "Nghiên cứu thị trường, phân tích đối thủ, xu hướng YouTube & web",
        "icon": "compass",
        "color": "#10B981",
    },
    {
        "id": "dept-ecommerce",
        "name": "Thương mại điện tử",
        "description": "Quản lý sản phẩm, giá bán, tư vấn bán hàng & chăm sóc khách hàng",
        "icon": "shopping-cart",
        "color": "#F59E0B",
    },
    {
        "id": "dept-office",
        "name": "Văn phòng",
        "description": "Điều phối trung tâm, lập kế hoạch DAG và báo cáo hiệu suất",
        "icon": "briefcase",
        "color": "#6366F1",
    },
]

# Standard 12 core agents according to BA spec F02.1
DEFAULT_AGENTS = [
    {
        "id": "agent-commander",
        "name": "Commander",
        "display_name": "Master Commander",
        "description": "Chỉ huy trưởng điều phối, phân tích lệnh tự nhiên và phân rã DAG",
        "role": "Master Commander & Orchestrator",
        "department_id": "dept-office",
        "is_system": True,
        "default_model": "gemini-2.5-flash",
        "system_prompt": "Bạn là Master Commander điều phối toàn bộ hệ sinh thái tác tử AI.",
    },
    {
        "id": "agent-deep-researcher",
        "name": "DeepResearcher",
        "display_name": "Deep Researcher",
        "description": "Chuyên gia nghiên cứu thị trường, đối thủ, đào sâu YouTube & web",
        "role": "Deep Research Specialist",
        "department_id": "dept-rd",
        "is_system": False,
        "default_model": "gemini-2.5-flash",
        "system_prompt": "Bạn là chuyên gia nghiên cứu thị trường, phân tích video và dữ liệu web.",
    },
    {
        "id": "agent-content-writer",
        "name": "ContentWriter",
        "display_name": "Content Writer",
        "description": "Chuyên viên sản xuất nội dung bài viết, kịch bản, copywriting chuẩn viral",
        "role": "Content Copywriter",
        "department_id": "dept-content",
        "is_system": False,
        "default_model": "gemini-2.5-flash",
        "system_prompt": "Bạn là chuyên gia sáng tạo nội dung, copywriting và viết kịch bản.",
    },
    {
        "id": "agent-image-studio",
        "name": "ImageStudio",
        "display_name": "Image Studio",
        "description": "Chuyên gia thiết kế banner, hình ảnh social qua HTML/CSS/SVG render",
        "role": "Visual & Image Designer",
        "department_id": "dept-content",
        "is_system": False,
        "default_model": "gemini-2.5-flash",
        "system_prompt": "Bạn là chuyên viên thiết kế đồ họa, hình ảnh trực quan HTML/SVG.",
    },
    {
        "id": "agent-video-editor",
        "name": "VideoEditor",
        "display_name": "Video Editor",
        "description": "Biên tập video ngắn, cắt ghép ffmpeg, pacing linter và storyboard",
        "role": "Video Production Specialist",
        "department_id": "dept-content",
        "is_system": False,
        "default_model": "gemini-2.5-flash",
        "system_prompt": "Bạn là chuyên gia biên tập video, dựng storyboard và linter nhịp điệu.",
    },
    {
        "id": "agent-funnels-agent",
        "name": "FunnelsAgent",
        "display_name": "Funnels Strategist",
        "description": "Chiến lược gia phễu bán hàng đa tầng, sơ đồ chuyển đổi khách hàng",
        "role": "Funnels Strategist",
        "department_id": "dept-funnels",
        "is_system": False,
        "default_model": "gemini-2.5-flash",
        "system_prompt": "Bạn là nhà kiến trúc phễu bán hàng, chiến lược chuyển đổi đa kênh.",
    },
    {
        "id": "agent-growth-advisor",
        "name": "GrowthAdvisor",
        "display_name": "Growth Advisor",
        "description": "Cố vấn tăng trưởng doanh số, chiến lược giá bán và phân tích KPI",
        "role": "Growth & Pricing Advisor",
        "department_id": "dept-funnels",
        "is_system": False,
        "default_model": "gemini-2.5-flash",
        "system_prompt": "Bạn là cố vấn tăng trưởng kinh doanh, định giá sản phẩm và tối ưu KPI.",
    },
    {
        "id": "agent-ui-designer",
        "name": "UIDesigner",
        "display_name": "UI Designer",
        "description": "Thiết kế giao diện landing page, template HTML offline responsive",
        "role": "UI/UX Landing Page Designer",
        "department_id": "dept-funnels",
        "is_system": False,
        "default_model": "gemini-2.5-flash",
        "system_prompt": "Bạn là chuyên gia thiết kế giao diện UI/UX và landing page HTML responsive.",
    },
    {
        "id": "agent-sales-agent",
        "name": "SalesAgent",
        "display_name": "Sales Specialist",
        "description": "Chuyên viên tư vấn bán hàng, xử lý từ chối và chốt đơn đa kênh",
        "role": "Sales Consultant",
        "department_id": "dept-ecommerce",
        "is_system": False,
        "default_model": "gemini-2.5-flash",
        "system_prompt": "Bạn là chuyên viên tư vấn bán hàng chuyên nghiệp, thấu hiểu khách hàng.",
    },
    {
        "id": "agent-customer-support-agent",
        "name": "CustomerSupportAgent",
        "display_name": "Customer Support",
        "description": "Hỗ trợ khách hàng, giải đáp thắc mắc dịch vụ và chính sách",
        "role": "Support Specialist",
        "department_id": "dept-ecommerce",
        "is_system": False,
        "default_model": "gemini-2.5-flash",
        "system_prompt": "Bạn là chuyên viên chăm sóc khách hàng, giải đáp thắc mắc và hỗ trợ kịp thời.",
    },
    {
        "id": "agent-report-agent",
        "name": "ReportAgent",
        "display_name": "Report Specialist",
        "description": "Tổng hợp số liệu, xuất báo cáo hiệu suất văn phòng định kỳ",
        "role": "Reporting Specialist",
        "department_id": "dept-office",
        "is_system": False,
        "default_model": "gemini-2.5-flash",
        "system_prompt": "Bạn là chuyên viên phân tích dữ liệu và lập báo cáo tổng hợp văn phòng.",
    },
    {
        "id": "agent-product-analyst",
        "name": "ProductAnalyst",
        "display_name": "Product Analyst",
        "description": "Phân tích danh mục sản phẩm, tính năng, định vị thị trường",
        "role": "Product Analyst",
        "department_id": "dept-ecommerce",
        "is_system": False,
        "default_model": "gemini-2.5-flash",
        "system_prompt": "Bạn là chuyên gia phân tích sản phẩm, nghiên cứu danh mục và định vị thị trường.",
    },
]


# Module-level sessionmaker factory cache
_FACTORIES: dict[str, sessionmaker[Session]] = {}


def reset_db_cache() -> None:
    """Clears cached sessionmaker instances (useful for test isolation)."""
    _FACTORIES.clear()


def init_db(
    db_path: Optional[Path | str] = None,
    force_recreate: bool = False,
    cache: Optional[bool] = None,
) -> sessionmaker[Session]:
    """Initializes SQLite database, enables foreign keys & WAL mode, and returns a sessionmaker.

    Caches the sessionmaker by resolved path to prevent recreating Engines and running DDL
    create_all on each get_db() invocation.

    Args:
        db_path: Path to SQLite database file. If None, resolves from AppSettings.
        force_recreate: If True, bypasses and replaces any existing cached sessionmaker.
        cache: If True, caches the sessionmaker. Defaults to True for file databases and False
            for in-memory databases (:memory:) to preserve test isolation.

    Returns:
        SQLAlchemy sessionmaker configured with the initialized SQLite engine.
    """
    if db_path is None:
        from app.config import get_settings
        settings = get_settings()
        db_path = settings.resolved_db_path

    is_memory = str(db_path) == ":memory:"
    should_cache = cache if cache is not None else not is_memory

    if not is_memory:
        path = Path(db_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        cache_key = str(path)
        engine_url = f"sqlite:///{path.as_posix()}"
    else:
        cache_key = ":memory:"
        engine_url = "sqlite:///:memory:"

    if should_cache and not force_recreate and cache_key in _FACTORIES:
        return _FACTORIES[cache_key]

    if is_memory:
        engine = create_engine(
            engine_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            echo=False,
        )
    else:
        engine = create_engine(
            engine_url,
            connect_args={"check_same_thread": False},
            echo=False,
        )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection: object, connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    if should_cache:
        _FACTORIES[cache_key] = factory

    return factory


def seed_defaults(session: Session) -> None:
    """Seeds default Project, 5 Departments, 12 Core Agents, and UserSettings idempotently.

    Safe to execute multiple times without duplicating or corrupting data.
    """
    # 1. Default Project
    if not session.get(Project, "proj-default"):
        session.add(
            Project(
                id="proj-default",
                name="Văn phòng Mặc định",
                description="Không gian làm việc chính",
                default_department_id="dept-office",
            )
        )

    # 2. 5 Standard Departments
    for dept_data in DEFAULT_DEPARTMENTS:
        existing_dept = session.get(Department, dept_data["id"])
        if not existing_dept:
            by_name = session.query(Department).filter_by(name=dept_data["name"]).first()
            if not by_name:
                session.add(Department(**dept_data))

    session.flush()

    # 3. 12 Core Agents
    for agent_data in DEFAULT_AGENTS:
        existing_agent = session.get(Agent, agent_data["id"])
        if not existing_agent:
            # Also check by unique name to avoid conflicts
            by_name = session.query(Agent).filter_by(name=agent_data["name"]).first()
            if not by_name:
                session.add(Agent(**agent_data))

    # 4. Default UserSettings
    if not session.get(UserSettings, "settings-default"):
        session.add(
            UserSettings(
                id="settings-default",
                theme="dark",
                language="vi",
                daily_token_limit=1000000,
                daily_usd_limit=10.0,
            )
        )

    session.commit()


def get_db(
    request: Request = None,  # type: ignore[assignment]
    db_path: Optional[Path | str] = None,
) -> Generator[Session, None, None]:
    """FastAPI dependency for yielding database sessions.

    Supports both FastAPI dependency injection (resolving db_path from request.app.state.settings)
    and direct function calls get_db(db_path) for test suites.
    """
    resolved_path: Optional[Path | str] = None
    if isinstance(request, Request):
        app_settings = getattr(request.app.state, "settings", None)
        if app_settings is not None:
            resolved_path = app_settings.resolved_db_path
    elif isinstance(request, (Path, str)):
        resolved_path = request
    elif db_path is not None:
        resolved_path = db_path

    SessionLocal = init_db(resolved_path, cache=True)
    with SessionLocal() as session:
        yield session
