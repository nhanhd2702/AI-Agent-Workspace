"""Tests for Brand Profile, Product Catalog, Price History, CSV Import, and Vector Sync (Task 4.2)."""

from __future__ import annotations

import io
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.brain.catalog import CatalogService
from app.brain.retriever import BrainRetriever
from app.config import AppSettings
from app.db.models import BrandProfile, Product
from app.db.session import init_db
from app.main import create_app


@pytest.fixture
def test_env(tmp_path: Path):
    """Provides isolated test environment with SQLite, ChromaDB, and FastAPI TestClient."""
    settings = AppSettings(
        workspace_dir=tmp_path / "workspace",
        local_auth_token="catalog-test-secret",
    )
    (tmp_path / "workspace").mkdir(parents=True, exist_ok=True)
    db_factory = init_db(settings.resolved_db_path, cache=False)
    app = create_app(settings)
    client = TestClient(app, headers={"X-Local-Auth-Token": "catalog-test-secret"})
    service = CatalogService(
        chroma_dir=settings.resolved_chroma_dir,
        workspace_root=settings.workspace_dir,
    )
    return {
        "settings": settings,
        "db_factory": db_factory,
        "client": client,
        "service": service,
        "chroma_dir": settings.resolved_chroma_dir,
    }


def test_brand_profile_default_and_templates(test_env):
    """CatalogService returns default BrandProfile and at least 3 starter templates."""
    db_factory = test_env["db_factory"]
    service: CatalogService = test_env["service"]

    with db_factory() as db:
        profile = service.get_brand_profile(db, project_id="proj-default")
        assert profile is not None
        assert profile.project_id == "proj-default"
        assert profile.brand_name != ""

        templates = service.get_starter_templates()
        assert len(templates) >= 3
        template_ids = [t["id"] for t in templates]
        assert "coach_educator" in template_ids
        assert "ecommerce_retail" in template_ids
        assert "b2b_saas" in template_ids

        # Verify template properties
        coach = next(t for t in templates if t["id"] == "coach_educator")
        assert len(coach["tone_of_voice"]) > 10
        assert len(coach["legal_boundaries"]) > 10
        assert "coach" in coach["name"].lower() or "educator" in coach["name"].lower()


def test_save_brand_profile_and_vector_sync(test_env):
    """Saving brand profile updates DB and syncs vector representation to ChromaDB."""
    db_factory = test_env["db_factory"]
    service: CatalogService = test_env["service"]
    chroma_dir = test_env["chroma_dir"]

    data = {
        "brand_name": "Minh CÃ´ng Nghá»‡",
        "tagline": "Khai mÃ´ng trÃ­ tuá»‡ nhÃ¢n táº¡o",
        "target_audience": "Cá»™ng Ä‘á»“ng láº­p trÃ¬nh viÃªn vÃ  sÃ¡ng táº¡o ná»™i dung",
        "tone_of_voice": "UyÃªn bÃ¡c, hÃ i hÆ°á»›c, tháº¥t truyá» n, tháº£o luáº­n chuyÃªn sÃ¢u",
        "brand_colors": ["#00f5d4", "#7b2cbf", "#0b090a"],
        "fonts": ["Inter", "JetBrains Mono"],
        "legal_boundaries": "KhÃ´ng cam káº¿t thu nháº­p, tuÃ¢n thá»§ báº£n quyá» n mÃ£ nguá»“n má»Ÿ.",
    }

    with db_factory() as db:
        saved = service.save_brand_profile(db, data, project_id="proj-default")
        assert saved.brand_name == "Minh CÃ´ng Nghá»‡"
        assert saved.tagline == "Khai mÃ´ng trÃ­ tuá»‡ nhÃ¢n táº¡o"
        assert len(saved.brand_colors) == 3

    # Verify vector sync into ChromaDB collection 'brand_profile'
    retriever = BrainRetriever(chroma_dir=chroma_dir, default_min_similarity=0.4)
    hits = retriever.search(query="quy Ä‘á»‹nh báº£n quyá» n vÃ  giá»›i háº¡n phÃ¡p lÃ½", collections=["brand_profile"], top_k=3)
    assert len(hits) > 0
    assert "Minh CÃ´ng Nghá»‡" in hits[0].text or "báº£n quyá» n" in hits[0].text


def test_product_upsert_price_history_and_vector_sync(test_env):
    """Upserting products tracks price audit history and syncs to ChromaDB."""
    db_factory = test_env["db_factory"]
    service: CatalogService = test_env["service"]
    chroma_dir = test_env["chroma_dir"]

    prod_data = {
        "sku": "AI-PRO-01",
        "name": "KhÃ³a há» c AI Engineer Thá»±c Chiáº¿n",
        "price_vnd": 5000000,
        "tier_type": "Course",
        "short_desc": "KhÃ³a Ä‘Ã o táº¡o kÄ© sÆ° AI toÃ n diá»‡n",
        "full_desc": "ChÆ°Æ¡ng trÃ¬nh 12 tuáº§n xÃ¢y dá»±ng há»‡ thá»‘ng AI Agent tá»± hÃ nh vá»›i LangGraph vÃ  Fastify.",
        "deliverables": ["12 buá»•i video", "Repo source code", "Mentor 1:1"],
        "policies": ["HoÃ n tiá» n trong 7 ngÃ y", "Báº£o lÆ°u 6 thÃ¡ng"],
        "faqs": [{"q": "HÃ³a Ä‘Æ¡n VAT cÃ³ khÃ´ng?", "a": "CÃ³ xuáº¥t hÃ³a Ä‘Æ¡n VAT doanh nghiá»‡p."}],
    }

    # 1. Initial insert
    with db_factory() as db:
        p1 = service.upsert_product(db, prod_data, project_id="proj-default")
        assert p1.sku == "AI-PRO-01"
        assert p1.price_vnd == 5000000
        assert p1.price_history is not None
        assert len(p1.price_history) == 1
        assert p1.price_history[0]["price_vnd"] == 5000000
        assert p1.price_history[0]["reason"] == "initial"
        p1_id = p1.id

    # 2. Price update
    update_data = dict(prod_data)
    update_data["price_vnd"] = 4500000
    with db_factory() as db:
        p2 = service.upsert_product(db, update_data, project_id="proj-default")
        assert p2.id == p1_id
        assert p2.price_vnd == 4500000
        assert len(p2.price_history) == 2
        assert p2.price_history[1]["price_vnd"] == 4500000
        assert p2.price_history[1]["reason"] == "update"

        # Check get_price_history method
        history = service.get_price_history(db, p1_id)
        assert len(history) == 2
        assert history[0]["price_vnd"] == 5000000
        assert history[1]["price_vnd"] == 4500000

    # 3. Vector search via retriever in collection 'products'
    retriever = BrainRetriever(chroma_dir=chroma_dir, default_min_similarity=0.4)
    hits = retriever.search(query="KhÃ³a há» c AI Engineer LangGraph", collections=["products"], top_k=2)
    assert len(hits) > 0
    assert "AI-PRO-01" in hits[0].text or "KhÃ³a há» c AI Engineer" in hits[0].text


def test_product_list_and_delete(test_env):
    """Listing with active_only filter and deletion from DB & ChromaDB."""
    db_factory = test_env["db_factory"]
    service: CatalogService = test_env["service"]
    chroma_dir = test_env["chroma_dir"]

    with db_factory() as db:
        service.upsert_product(
            db,
            {"sku": "P-ACT", "name": "Sáº£n pháº©m Ä ang bÃ¡n", "price_vnd": 100000, "is_active": True},
            project_id="proj-default",
        )
        p_inact = service.upsert_product(
            db,
            {"sku": "P-INACT", "name": "Sáº£n pháº©m Ngá»«ng bÃ¡n", "price_vnd": 200000, "is_active": False},
            project_id="proj-default",
        )

        all_prods = service.list_products(db, project_id="proj-default", active_only=False)
        assert len(all_prods) >= 2

        active_prods = service.list_products(db, project_id="proj-default", active_only=True)
        skus = [p.sku for p in active_prods]
        assert "P-ACT" in skus
        assert "P-INACT" not in skus

        # Delete inactive product
        deleted = service.delete_product(db, p_inact.id)
        assert deleted is True

        all_after = service.list_products(db, project_id="proj-default", active_only=False)
        assert not any(p.sku == "P-INACT" for p in all_after)

    # Verify deleted from vector collection
    retriever = BrainRetriever(chroma_dir=chroma_dir, default_min_similarity=0.4)
    hits = retriever.search(query="Sáº£n pháº©m Ngá»«ng bÃ¡n", collections=["products"], top_k=5)
    assert not any("P-INACT" in h.text for h in hits)


def test_import_csv_valid_and_errors(test_env):
    """Import CSV parses rows, detects invalid entries, and syncs valid rows."""
    db_factory = test_env["db_factory"]
    service: CatalogService = test_env["service"]

    csv_content = (
        "sku,name,price_vnd,tier_type,short_desc,full_desc,deliverables,policies\n"
        "CSV-001,GÃ³i TÆ° váº¥n 1:1,3000000,Coaching,TÆ° váº¥n chiáº¿n lÆ°á»£c,TÆ° váº¥n 1-1 chuyÃªn sÃ¢u,Buá»•i gáº·p 2h,KhÃ´ng hoÃ n tiá» n\n"
        "CSV-002,Ebook Tá»± Ä‘á»™ng hÃ³a,250000,Digital,SÃ¡ch Ä‘iá»‡n tá»­ PDF,Cáº©m nang hÆ°á»›ng dáº«n chi tiáº¿t,File PDF;File Epub,HoÃ n tiá» n 24h\n"
        ",Thiáº¿u SKU,100000,Invalid,KhÃ´ng cÃ³ mÃ£,MÃ´ táº£,deliverable,policy\n"
        "CSV-ERR,GiÃ¡ Ã¢m,-50000,Invalid,GiÃ¡ khÃ´ng há»£p lá»‡,MÃ´ táº£,deliverable,policy\n"
    )

    with db_factory() as db:
        res = service.import_csv(db, csv_content, project_id="proj-default")
        assert res["imported_count"] == 2
        assert len(res["errors"]) == 2
        assert res["errors"][0]["row"] == 4  # 1-indexed row 4 (3rd data row)
        assert res["errors"][1]["row"] == 5

        # Verify products in db
        p1 = db.query(Product).filter_by(sku="CSV-001").first()
        assert p1 is not None
        assert p1.price_vnd == 3000000
        assert "Buá»•i gáº·p 2h" in p1.deliverables


def test_brain_api_brand_profile_and_products_flow(test_env):
    """Full HTTP API test for Brand Profile and Product Catalog endpoints."""
    client: TestClient = test_env["client"]

    # 1. GET /api/v1/brain/brand-profile
    resp_get_bp = client.get("/api/v1/brain/brand-profile")
    assert resp_get_bp.status_code == 200
    bp_data = resp_get_bp.json()
    assert "profile" in bp_data
    assert "templates" in bp_data
    assert len(bp_data["templates"]) >= 3

    # 2. PUT /api/v1/brain/brand-profile
    update_bp_payload = {
        "brand_name": "Antigravity Global",
        "tagline": "AI Workspace for Solo Founders",
        "tone_of_voice": "Bold, insightful, practical",
        "target_audience": "Global developers",
        "brand_colors": ["#0ea5e9", "#10b981"],
        "fonts": ["Inter"],
        "legal_boundaries": "No financial advice.",
    }
    resp_put_bp = client.put("/api/v1/brain/brand-profile", json=update_bp_payload)
    assert resp_put_bp.status_code == 200
    updated_bp = resp_put_bp.json()
    assert updated_bp["brand_name"] == "Antigravity Global"
    assert updated_bp["tagline"] == "AI Workspace for Solo Founders"

    # 3. POST /api/v1/brain/products (create)
    product_payload = {
        "sku": "API-PROD-1",
        "name": "Combo AI Mastery",
        "price_vnd": 8900000,
        "tier_type": "Bundle",
        "short_desc": "Combo toÃ n diá»‡n",
        "full_desc": "Bao gá»“m táº¥t cáº£ cÃ¡c khÃ³a há» c vÃ  cÃ´ng cá»¥",
        "deliverables": ["All courses", "Private Discord"],
        "policies": ["Trá»n Ä‘á»i"],
        "faqs": [{"q": "Há»c trong bao lÃ¢u?", "a": "Tá»± há»c linh hoáº¡t"}],
        "is_active": True,
    }
    resp_post_p = client.post("/api/v1/brain/products", json=product_payload)
    assert resp_post_p.status_code in (200, 201)
    created_p = resp_post_p.json()
    assert created_p["sku"] == "API-PROD-1"
    prod_id = created_p["id"]

    # 4. GET /api/v1/brain/products
    resp_list_p = client.get("/api/v1/brain/products")
    assert resp_list_p.status_code == 200
    items = resp_list_p.json()
    assert any(item["sku"] == "API-PROD-1" for item in items)

    # 5. GET /api/v1/brain/products/{id}/history
    resp_hist = client.get(f"/api/v1/brain/products/{prod_id}/history")
    assert resp_hist.status_code == 200
    hist = resp_hist.json()
    assert len(hist) >= 1
    assert hist[0]["price_vnd"] == 8900000

    # 6. POST /api/v1/brain/products/import-csv
    csv_file_data = (
        "sku,name,price_vnd,tier_type,short_desc,full_desc,deliverables,policies\n"
        "BULK-1,Sáº£n pháº©m 1,120000,Basic,Desc 1,Full 1,Deliv 1,Pol 1\n"
        "BULK-2,Sáº£n pháº©m 2,340000,Premium,Desc 2,Full 2,Deliv 2,Pol 2\n"
    ).encode("utf-8")
    resp_csv = client.post(
        "/api/v1/brain/products/import-csv",
        files={"file": ("products.csv", io.BytesIO(csv_file_data), "text/csv")},
    )
    assert resp_csv.status_code == 200
    csv_res = resp_csv.json()
    assert csv_res["imported_count"] == 2
    assert len(csv_res["errors"]) == 0

    # 7. DELETE /api/v1/brain/products/{id}
    resp_del = client.delete(f"/api/v1/brain/products/{prod_id}")
    assert resp_del.status_code == 200
    assert resp_del.json()["status"] == "deleted"

    # Confirm deleted
    resp_list_after = client.get("/api/v1/brain/products")
    assert not any(item["id"] == prod_id for item in resp_list_after.json())
