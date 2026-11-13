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


def test_tenant_isolation_probe(test_env):
    """Different projects can have products with the same SKU without collision or cross-overwrite."""
    db_factory = test_env["db_factory"]
    service: CatalogService = test_env["service"]
    client: TestClient = test_env["client"]

    from app.db.models import Project

    with db_factory() as db:
        if not db.get(Project, "proj-alpha"):
            db.add(Project(id="proj-alpha", name="Project Alpha"))
        if not db.get(Project, "proj-beta"):
            db.add(Project(id="proj-beta", name="Project Beta"))
        db.commit()

    with db_factory() as db:
        # 1. Project A creates SKU "SHARED-SKU"
        p_a = service.upsert_product(
            db,
            {"sku": "SHARED-SKU", "name": "Dự án A - Sp 1", "price_vnd": 100000},
            project_id="proj-alpha",
        )
        assert p_a.project_id == "proj-alpha"
        assert p_a.price_vnd == 100000
        p_a_id = p_a.id

        # 2. Project B creates product with SAME SKU "SHARED-SKU"
        p_b = service.upsert_product(
            db,
            {"sku": "SHARED-SKU", "name": "Dự án B - Sp 1", "price_vnd": 250000},
            project_id="proj-beta",
        )
        assert p_b.project_id == "proj-beta"
        assert p_b.price_vnd == 250000
        p_b_id = p_b.id

        # Ensure different IDs and no overwrite
        assert p_a_id != p_b_id

        # Reload Project A product and ensure untouched
        reloaded_a = db.get(Product, p_a_id)
        assert reloaded_a.name == "Dự án A - Sp 1"
        assert reloaded_a.price_vnd == 100000

        # 3. Project B attempts to overwrite Project A product by ID -> raises ValueError
        with pytest.raises(ValueError, match="không thuộc dự án này"):
            service.upsert_product(
                db,
                {"id": p_a_id, "sku": "HACK-SKU", "name": "Hack Attempt", "price_vnd": 500},
                project_id="proj-beta",
            )

        # 4. Project B attempts to view Project A product history -> raises ValueError
        with pytest.raises(ValueError, match="không thuộc dự án này"):
            service.get_price_history(db, p_a_id, project_id="proj-beta")

        # 5. Project B attempts to delete Project A product -> raises ValueError
        with pytest.raises(ValueError, match="không thuộc dự án này"):
            service.delete_product(db, p_a_id, project_id="proj-beta")

    # 6. Verify HTTP API enforcing HTTP 403 on cross-tenant attempts
    # Cross-project upsert by ID
    resp_cross_upsert = client.post(
        "/api/v1/brain/products",
        json={
            "id": p_a_id,
            "project_id": "proj-beta",
            "sku": "HACK",
            "name": "Hack from API",
            "price_vnd": 50000,
        },
    )
    assert resp_cross_upsert.status_code == 403
    assert "không thuộc dự án này" in resp_cross_upsert.json()["detail"]

    # Cross-project get price history
    resp_cross_hist = client.get(f"/api/v1/brain/products/{p_a_id}/history?project_id=proj-beta")
    assert resp_cross_hist.status_code == 403

    # Cross-project delete
    resp_cross_del = client.delete(f"/api/v1/brain/products/{p_a_id}?project_id=proj-beta")
    assert resp_cross_del.status_code == 403


def test_negative_price_validation(test_env):
    """Negative prices are rejected at both service level (ValueError) and API level (400 or 422)."""
    db_factory = test_env["db_factory"]
    service: CatalogService = test_env["service"]
    client: TestClient = test_env["client"]

    # 1. Service-level ValueError
    with db_factory() as db:
        with pytest.raises(ValueError, match="không được là số âm"):
            service.upsert_product(
                db,
                {"sku": "NEG-SRV", "name": "Giá âm", "price_vnd": -50000},
                project_id="proj-default",
            )

    # 2. API-level rejection
    resp_api = client.post(
        "/api/v1/brain/products",
        json={"sku": "NEG-API", "name": "Giá âm API", "price_vnd": -1000},
    )
    assert resp_api.status_code in (400, 422)


def test_csv_formula_injection_sanitization(test_env):
    """CSV cells with formula characters (=, +, -, @) are sanitized with leading single quote."""
    db_factory = test_env["db_factory"]
    service: CatalogService = test_env["service"]

    csv_content = (
        "sku,name,price_vnd,tier_type,short_desc,full_desc,deliverables,policies\n"
        "=CMD|calc,@SUM(1+1),500000,+VIP,-ShortDesc,-FullDesc,+Deliv 1;@Deliv 2,=Policy 1\n"
    )

    with db_factory() as db:
        res = service.import_csv(db, csv_content, project_id="proj-default")
        assert res["imported_count"] == 1
        assert len(res["errors"]) == 0

        prod = db.query(Product).filter_by(project_id="proj-default", sku="'=CMD|calc").first()
        assert prod is not None
        assert prod.sku == "'=CMD|calc"
        assert prod.name == "'@SUM(1+1)"
        assert prod.tier_type == "'+VIP"
        assert prod.short_desc == "'-ShortDesc"
        assert prod.full_desc == "'-FullDesc"
        assert prod.deliverables == ["'+Deliv 1", "'@Deliv 2"]
        assert prod.policies == ["'=Policy 1"]


def test_csv_over_500_rows_rejected(test_env):
    """CSV files containing more than 500 data rows are explicitly rejected without importing."""
    db_factory = test_env["db_factory"]
    service: CatalogService = test_env["service"]

    # Build CSV with 505 data rows
    lines = ["sku,name,price_vnd\n"]
    for i in range(1, 506):
        lines.append(f"ROW-{i},Product {i},10000\n")
    large_csv = "".join(lines)

    with db_factory() as db:
        res = service.import_csv(db, large_csv, project_id="proj-default")
        assert res["imported_count"] == 0
        assert len(res["errors"]) == 1
        assert res["errors"][0]["row"] == 0
        assert "vượt quá giới hạn tối đa 500 dòng sản phẩm" in res["errors"][0]["error"]

        # Ensure no products were inserted into the DB
        prods = db.query(Product).filter(Product.sku.like("ROW-%")).all()
        assert len(prods) == 0


def test_csv_batched_chroma_sync(test_env):
    """CSV import syncs all products to ChromaDB in a single batch."""
    db_factory = test_env["db_factory"]
    service: CatalogService = test_env["service"]
    chroma_dir = test_env["chroma_dir"]

    csv_content = (
        "sku,name,price_vnd,short_desc\n"
        "BATCH-01,Laptop Gaming ASUS ROG,25000000,May tinh choi game manh me\n"
        "BATCH-02,Ban phim co Khong day,1500000,Ban phim co bluetooth\n"
        "BATCH-03,Tai nghe Chuyen dung Studio,3200000,Tai nghe am thanh trung thuc\n"
    )

    with db_factory() as db:
        res = service.import_csv(db, csv_content, project_id="proj-default")
        assert res["imported_count"] == 3
        assert len(res["errors"]) == 0

    # Verify vector retriever can find batch products in ChromaDB
    retriever = BrainRetriever(chroma_dir=chroma_dir, default_min_similarity=0.3)
    hits = retriever.search(query="Laptop Gaming ASUS", collections=["products"], top_k=2)
    assert len(hits) > 0
    assert any("BATCH-01" in h.text for h in hits)


def test_chroma_sync_failure_logging(test_env, caplog):
    """Vector sync failure is logged with logger.error and does not crash the database operation."""
    import logging
    from unittest.mock import patch

    db_factory = test_env["db_factory"]
    service: CatalogService = test_env["service"]

    with patch.object(service.chroma_client, "get_or_create_collection", side_effect=RuntimeError("Chroma simulated down")):
        with caplog.at_level(logging.ERROR):
            with db_factory() as db:
                prod = service.upsert_product(
                    db,
                    {"sku": "CHROMA-FAIL", "name": "Chroma Fail Safe", "price_vnd": 300000},
                    project_id="proj-default",
                )
                assert prod is not None
                assert prod.sku == "CHROMA-FAIL"

            assert any("ChromaDB vector sync failed" in r.message for r in caplog.records)
