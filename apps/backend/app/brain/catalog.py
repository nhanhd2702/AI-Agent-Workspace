"""Brand Profile and Product Catalog Service with Vector Sync and Price Audit (Task 4.2).

Manages Brand Identity Guidelines and Product Catalog with VND pricing, price change
audit trails, CSV bulk import, and automatic synchronization to ChromaDB collections
('brand_profile' and 'products') for downstream agent semantic RAG retrieval.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import io
import json
import logging
from pathlib import Path
import re
from typing import Any, Optional
import uuid

logger = logging.getLogger(__name__)


def sanitize_csv_formula(val: Optional[str]) -> Optional[str]:
    """Disarms CSV Formula Injection (CWE-1236).

    Prepends a single quote to text fields starting with =, +, -, @, \\t, or \\r.
    """
    if val is None:
        return None
    s = str(val).strip()
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + str(val)
    return str(val)

from sqlalchemy.orm import Session

from app.brain.ingest import normalize_collection_name
from app.brain.retriever import BrainRetriever
from app.config import get_settings
from app.db.models import BrandProfile, Product

STARTER_BRAND_TEMPLATES = [
    {
        "id": "coach_educator",
        "name": "ChuyÃªn gia / Huáº¥n luyá»‡n viÃªn (Coach / Educator)",
        "tagline": "Khai má»Ÿ tiá» m nÄƒng - Dáº«n lá»‘i thÃ nh cÃ´ng",
        "tone_of_voice": "UyÃªn bÃ¡c, Ã¢n cáº§n, chÃ¢n thÃ nh, truyá» n cáº£m há»©ng vÃ  Ä‘á»™ng viÃªn há» c viÃªn.",
        "legal_boundaries": "KhÃ´ng cam káº¿t káº¿t quáº£ y táº¿/chá»¯a bá»‡nh; khÃ´ng há»©a háº¹n lÃ m giÃ u cáº¥p tá»‘c hoáº·c cam káº¿t thu nháº­p cá»¥ thá»ƒ; tÃ´n trá» ng báº£n quyá» n giÃ¡o trÃ¬nh.",
        "target_audience": "NgÆ°á» i Ä‘i lÃ m, sinh viÃªn, cÃ¡c cÃ¡ nhÃ¢n muá»‘n phÃ¡t triá»ƒn báº£n thÃ¢n vÃ  kÄ© nÄƒng nghá»  nghiá»‡p.",
        "brand_colors": ["#0284c7", "#0f172a", "#f8fafc"],
        "fonts": ["Inter", "Roboto"],
    },
    {
        "id": "ecommerce_retail",
        "name": "ThÆ°Æ¡ng máº¡i Ä iá»‡n tá»­ / BÃ¡n láº» (E-commerce / Retail)",
        "tagline": "Cháº¥t lÆ°á»£ng Ä‘á»‰nh cao - GiÃ¡ cáº£ cháº¡m sÃ n",
        "tone_of_voice": "NÄƒng Ä‘á»™ng, tráº» trung, gáº§n gÅ©i, kÃ­ch thÃ­ch hÃ nh Ä‘á»™ng mua sáº¯m ngay.",
        "legal_boundaries": "Ä á»•i tráº£ 7 ngÃ y miá»…n phÃ­ náº¿u cÃ³ lá»—i nhÃ  sáº£n xuáº¥t; báº£o hÃ nh chÃ­nh hÃ£ng 12 thÃ¡ng; cam káº¿t hÃ ng chÃ­nh hÃ£ng 100%, Ä‘á» n tiá» n gáº¥p Ä‘Ã´i náº¿u phÃ¡t hiá»‡n hÃ ng giáº£.",
        "target_audience": "KhÃ¡ch hÃ ng tráº» 18-35 tuá»•i, yÃªu thÃ­ch sá»± tiá»‡n lá»£i, sÄƒn Æ°u Ä‘Ã£i, mua sáº¯m online.",
        "brand_colors": ["#f97316", "#ef4444", "#111827"],
        "fonts": ["Montserrat", "Open Sans"],
    },
    {
        "id": "b2b_saas",
        "name": "Dá»‹ch vá»¥ Doanh nghiá»‡p B2B (B2B SaaS / Agency)",
        "tagline": "Tá»‘i Æ°u váº­n hÃ nh - Ä á»™t phÃ¡ doanh thu",
        "tone_of_voice": "ChuyÃªn nghiá»‡p, sÃºc tÃ­ch, dá»±a trÃªn dá»¯ liá»‡u dáº«n chá»©ng (data-driven), hÆ°á»›ng tá»›i ROI.",
        "legal_boundaries": "Báº£o máº­t thÃ´ng tin khÃ¡ch hÃ ng tuyá»‡t Ä‘á»‘i theo NDA; cam káº¿t SLA 99.9% uptime; tuÃ¢n thá»§ quy Ä‘á»‹nh báº£o vá»‡ dá»¯ liá»‡u doanh nghiá»‡p.",
        "target_audience": "Chá»§ doanh nghiá»‡p, CMO, CTO, quáº£n lÃ½ cáº¥p trung vÃ  cáº¥p cao.",
        "brand_colors": ["#3b82f6", "#1e1b4b", "#64748b"],
        "fonts": ["Plus Jakarta Sans", "Inter"],
    },
]


class CatalogService:
    """Manages BrandProfile and Product Catalog operations and Chroma vector synchronization."""

    STARTER_TEMPLATES = STARTER_BRAND_TEMPLATES

    def __init__(
        self,
        chroma_dir: Optional[Path] = None,
        workspace_root: Optional[Path] = None,
    ) -> None:
        if chroma_dir is not None:
            self.chroma_dir = Path(chroma_dir).resolve()
        else:
            self.chroma_dir = get_settings().resolved_chroma_dir

        self.chroma_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_root = (
            Path(workspace_root).resolve()
            if workspace_root is not None
            else get_settings().workspace_dir.resolve()
        )

        import chromadb

        self.chroma_client = chromadb.PersistentClient(path=str(self.chroma_dir))

    def get_starter_templates(self) -> list[dict[str, Any]]:
        """Returns the list of curated BrandProfile starter templates."""
        return list(self.STARTER_TEMPLATES)

    # --------------------------------------------------------------------------
    # Brand Profile Management
    # --------------------------------------------------------------------------

    def get_brand_profile(self, db: Session, project_id: str = "proj-default") -> BrandProfile:
        """Retrieves existing BrandProfile for project, or creates and seeds a default one."""
        profile = db.query(BrandProfile).filter_by(project_id=project_id).first()
        if not profile:
            profile = BrandProfile(
                id=f"bp_{uuid.uuid4().hex[:12]}",
                project_id=project_id,
                brand_name="ThÆ°Æ¡ng hiá»‡u cá»§a tÃ´i",
                tagline="Ä á»‹nh vá»‹ giÃ¡ trá»‹ cá»‘t lÃµi & chuyÃªn mÃ´n",
                target_audience="KhÃ¡ch hÃ ng tiá» m nÄƒng má»¥c tiÃªu",
                tone_of_voice="ChuyÃªn nghiá»‡p, tin cáº­y, há»¯u Ã­ch vÃ  rÃµ rÃ ng",
                brand_colors=["#0ea5e9", "#1e293b", "#f8fafc"],
                fonts=["Inter"],
                legal_boundaries="KhÃ´ng cam káº¿t káº¿t quáº£ phi thá»±c táº¿; báº£o máº­t thÃ´ng tin khÃ¡ch hÃ ng.",
                logo_asset_id=None,
                is_active=True,
            )
            db.add(profile)
            db.commit()
            db.refresh(profile)
            self._sync_brand_profile_to_chroma(profile)
        return profile

    def save_brand_profile(
        self,
        db: Session,
        data: dict[str, Any],
        project_id: str = "proj-default",
    ) -> BrandProfile:
        """Updates or creates BrandProfile and synchronizes text representation to ChromaDB."""
        profile = db.query(BrandProfile).filter_by(project_id=project_id).first()
        if not profile:
            profile = BrandProfile(
                id=data.get("id") or f"bp_{uuid.uuid4().hex[:12]}",
                project_id=project_id,
                brand_name=data.get("brand_name", "ThÆ°Æ¡ng hiá»‡u"),
            )
            db.add(profile)

        # Update fields
        for field in [
            "brand_name",
            "tagline",
            "target_audience",
            "tone_of_voice",
            "brand_colors",
            "fonts",
            "legal_boundaries",
            "logo_asset_id",
            "is_active",
        ]:
            if field in data and data[field] is not None:
                setattr(profile, field, data[field])

        profile.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(profile)

        # Sync to ChromaDB collection 'brand_profile'
        self._sync_brand_profile_to_chroma(profile)
        return profile

    def _sync_brand_profile_to_chroma(self, profile: BrandProfile) -> None:
        """Synchronizes BrandProfile guidelines into ChromaDB for agent RAG retrieval."""
        try:
            col_name = normalize_collection_name("brand_profile")
            col = self.chroma_client.get_or_create_collection(
                name=col_name,
                metadata={"hnsw:space": "cosine"},
            )

            colors_str = ", ".join(profile.brand_colors or [])
            fonts_str = ", ".join(profile.fonts or [])

            doc_text = (
                f"ThÆ°Æ¡ng hiá»‡u: {profile.brand_name}\n"
                f"Kháº©u hiá»‡u (Tagline): {profile.tagline or ''}\n"
                f"KhÃ¡ch hÃ ng má»¥c tiÃªu: {profile.target_audience or ''}\n"
                f"Giá» ng vÄƒn vÃ  Tone of Voice: {profile.tone_of_voice or ''}\n"
                f"Ranh giá»›i phÃ¡p lÃ½, cam káº¿t & Ä‘áº¡o Ä‘á»©c: {profile.legal_boundaries or ''}\n"
                f"Báº£ng mÃ u nháº­n diá»‡n thÆ°Æ¡ng hiá»‡u: {colors_str}\n"
                f"Font chá»¯ chuáº©n: {fonts_str}"
            )

            meta = {
                "doc_id": profile.id,
                "doc_title": f"Brand Profile - {profile.brand_name}",
                "collection": "brand_profile",
                "project_id": profile.project_id,
            }

            col.upsert(ids=[profile.id], documents=[doc_text], metadatas=[meta])
            BrainRetriever.clear_cache()
        except Exception as exc:
            logger.error("ChromaDB vector sync failed: %s", exc, exc_info=True)

    # --------------------------------------------------------------------------
    # Product Catalog Management
    # --------------------------------------------------------------------------

    def _product_to_text(self, product: Product) -> str:
        """Formats product into rich semantic text for vector search indexing."""
        deliverables_str = ", ".join(product.deliverables or [])
        policies_str = ", ".join(product.policies or [])
        faqs_lines: list[str] = []
        if product.faqs:
            for item in product.faqs:
                if isinstance(item, dict):
                    q = item.get("q") or item.get("question") or ""
                    a = item.get("a") or item.get("answer") or ""
                    if q:
                        faqs_lines.append(f"- Há» i: {q} | Ä Ã¡p: {a}")
        faqs_str = "\n".join(faqs_lines) if faqs_lines else "KhÃ´ng cÃ³"

        return (
            f"MÃ£ SKU: {product.sku}\n"
            f"TÃªn sáº£n pháº©m: {product.name}\n"
            f"GiÃ¡ niÃªm yáº¿t: {product.price_vnd:,} VND ({product.price_vnd} VND)\n"
            f"PhÃ¢n loáº¡i / Tier: {product.tier_type or 'TiÃªu chuáº©n'}\n"
            f"Tráº¡ng thÃ¡i: {'Ä ang bÃ¡n' if product.is_active else 'Ngá»«ng bÃ¡n'}\n"
            f"MÃ´ táº£ ngáº¯n: {product.short_desc or ''}\n"
            f"MÃ´ táº£ chi tiáº¿t: {product.full_desc or ''}\n"
            f"Quyá» n lá»£i & Deliverables: {deliverables_str}\n"
            f"ChÃ­nh sÃ¡ch & HoÃ n tiá» n: {policies_str}\n"
            f"CÃ¢u há» i thÆ°á» ng gáº·p (FAQs):\n{faqs_str}"
        )

    def _sync_products_batch_to_chroma(self, products: list[Product]) -> None:
        """Batch syncs multiple products into ChromaDB collection 'products' in a single operation."""
        if not products:
            return
        try:
            col_name = normalize_collection_name("products")
            col = self.chroma_client.get_or_create_collection(
                name=col_name,
                metadata={"hnsw:space": "cosine"},
            )

            ids: list[str] = []
            documents: list[str] = []
            metadatas: list[dict[str, Any]] = []

            for product in products:
                doc_text = self._product_to_text(product)
                meta = {
                    "doc_id": product.id,
                    "doc_title": f"{product.sku} - {product.name}",
                    "collection": "products",
                    "sku": product.sku,
                    "price_vnd": int(product.price_vnd),
                    "is_active": bool(product.is_active),
                    "project_id": str(product.project_id),
                }
                ids.append(product.id)
                documents.append(doc_text)
                metadatas.append(meta)

            col.upsert(ids=ids, documents=documents, metadatas=metadatas)
            BrainRetriever.clear_cache()
        except Exception as exc:
            logger.error("ChromaDB vector sync failed: %s", exc, exc_info=True)

    def _sync_product_to_chroma(self, product: Product) -> None:
        """Syncs single product document into ChromaDB collection 'products'."""
        self._sync_products_batch_to_chroma([product])

    def _remove_product_from_chroma(self, product_id: str) -> None:
        """Removes product document from ChromaDB collection 'products'."""
        try:
            col_name = normalize_collection_name("products")
            col = self.chroma_client.get_collection(name=col_name)
            col.delete(ids=[product_id])
            BrainRetriever.clear_cache()
        except Exception as exc:
            logger.error("ChromaDB vector sync failed: %s", exc, exc_info=True)

    def upsert_product(
        self,
        db: Session,
        data: dict[str, Any],
        project_id: str = "proj-default",
        sync_vector: bool = True,
    ) -> Product:
        """Creates or updates a product, logs price changes to price_history, and syncs vector."""
        sku = str(data.get("sku", "")).strip()
        if not sku:
            raise ValueError("Mã SKU không được để trống")

        new_price = int(data.get("price_vnd", 0))
        if new_price < 0:
            raise ValueError("Giá sản phẩm không được là số âm")

        # Find existing by ID or SKU within scoped project
        prod: Optional[Product] = None
        if data.get("id"):
            prod = db.get(Product, data["id"])
            if prod and prod.project_id != project_id:
                raise ValueError("Sản phẩm không thuộc dự án này")

        if not prod:
            prod = db.query(Product).filter_by(project_id=project_id, sku=sku).first()

        now_iso = datetime.now(timezone.utc).isoformat()

        if not prod:
            # Initial insert
            prod_id = data.get("id") or f"prod_{uuid.uuid4().hex[:12]}"
            history = [
                {
                    "price_vnd": new_price,
                    "recorded_at": now_iso,
                    "reason": "initial",
                }
            ]
            prod = Product(
                id=prod_id,
                project_id=project_id,
                sku=sku,
                name=data.get("name", ""),
                price_vnd=new_price,
                tier_type=data.get("tier_type"),
                short_desc=data.get("short_desc"),
                full_desc=data.get("full_desc"),
                deliverables=data.get("deliverables") or [],
                faqs=data.get("faqs") or [],
                policies=data.get("policies") or [],
                price_history=history,
                is_active=bool(data.get("is_active", True)),
            )
            db.add(prod)
        else:
            # Update
            history = list(prod.price_history or [])
            if prod.price_vnd != new_price:
                history.append(
                    {
                        "price_vnd": new_price,
                        "recorded_at": now_iso,
                        "reason": "update",
                    }
                )
            prod.price_history = history
            prod.sku = sku
            prod.name = data.get("name", prod.name)
            prod.price_vnd = new_price
            if "tier_type" in data:
                prod.tier_type = data["tier_type"]
            if "short_desc" in data:
                prod.short_desc = data["short_desc"]
            if "full_desc" in data:
                prod.full_desc = data["full_desc"]
            if "deliverables" in data:
                prod.deliverables = data["deliverables"]
            if "faqs" in data:
                prod.faqs = data["faqs"]
            if "policies" in data:
                prod.policies = data["policies"]
            if "is_active" in data:
                prod.is_active = bool(data["is_active"])
            prod.updated_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(prod)

        # Synchronize to ChromaDB if requested
        if sync_vector:
            self._sync_product_to_chroma(prod)
        return prod

    def get_price_history(
        self,
        db: Session,
        product_id: str,
        project_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Returns the price change history list for a product."""
        prod = db.get(Product, product_id)
        if not prod:
            return []
        if project_id is not None and prod.project_id != project_id:
            raise ValueError("Sản phẩm không thuộc dự án này")
        if not prod.price_history:
            return []
        return list(prod.price_history)

    def list_products(
        self,
        db: Session,
        project_id: str = "proj-default",
        active_only: bool = False,
    ) -> list[Product]:
        """Lists products for a project, optionally filtering for active products only."""
        query = db.query(Product).filter_by(project_id=project_id)
        if active_only:
            query = query.filter(Product.is_active == True)  # noqa: E712
        return query.order_by(Product.created_at.desc()).all()

    def delete_product(
        self,
        db: Session,
        product_id: str,
        project_id: Optional[str] = None,
    ) -> bool:
        """Deletes a product from the database and removes it from ChromaDB."""
        prod = db.get(Product, product_id)
        if not prod:
            return False
        if project_id is not None and prod.project_id != project_id:
            raise ValueError("Sản phẩm không thuộc dự án này")

        db.delete(prod)
        db.commit()

        self._remove_product_from_chroma(product_id)
        return True

    def import_csv(
        self,
        db: Session,
        csv_content: str,
        project_id: str = "proj-default",
    ) -> dict[str, Any]:
        """Imports up to 500 products from CSV string, handling errors gracefully per row."""
        # Clean BOM if present
        cleaned_content = csv_content.lstrip("\ufeff")
        f = io.StringIO(cleaned_content)

        # Detect delimiter (comma or semicolon)
        sample = cleaned_content[:2048]
        delimiter = ";" if sample.count(";") > sample.count(",") else ","

        reader = csv.reader(f, delimiter=delimiter)
        rows = list(reader)

        if not rows:
            return {"imported_count": 0, "errors": [{"row": 1, "sku": "", "error": "Tệp CSV trống"}]}

        # Parse header
        raw_headers = [h.strip().lower() for h in rows[0]]
        header_map: dict[str, int] = {}
        for idx, h in enumerate(raw_headers):
            # Normalize common variants
            clean_h = re.sub(r"[^a-z0-9_]", "", h)
            header_map[clean_h] = idx

        # Required headers check
        sku_col = header_map.get("sku")
        name_col = header_map.get("name") or header_map.get("tensanpham") or header_map.get("title")
        price_col = header_map.get("price_vnd") or header_map.get("price") or header_map.get("gia") or header_map.get("gia_vnd")

        imported_count = 0
        errors: list[dict[str, Any]] = []

        # Filter non-empty data rows
        data_rows_with_indices = [
            (idx, r) for idx, r in enumerate(rows[1:], start=2)
            if r and any(cell.strip() for cell in r)
        ]

        # Enforce maximum 500 data rows limit
        if len(data_rows_with_indices) > 500:
            return {
                "imported_count": 0,
                "errors": [
                    {
                        "row": 0,
                        "sku": "",
                        "error": "Tệp CSV vượt quá giới hạn tối đa 500 dòng sản phẩm",
                    }
                ],
            }

        imported_products: list[Product] = []

        for line_idx, row in data_rows_with_indices:
            def get_val(col_idx: Optional[int]) -> str:
                if col_idx is not None and col_idx < len(row):
                    return row[col_idx].strip()
                return ""

            raw_sku = get_val(sku_col)
            raw_name = get_val(name_col)
            price_str = get_val(price_col)

            if not raw_sku:
                errors.append({"row": line_idx, "sku": "", "error": "Thiếu mã SKU"})
                continue
            if not raw_name:
                errors.append({"row": line_idx, "sku": raw_sku, "error": "Thiếu tên sản phẩm"})
                continue

            # Parse price
            try:
                # Check original string for negative sign
                if "-" in price_str:
                    errors.append({"row": line_idx, "sku": raw_sku, "error": "Giá không được là số âm"})
                    continue
                # Remove currency symbols and dots/commas if formatted
                clean_price_str = re.sub(r"[^\d]", "", price_str)
                if not clean_price_str:
                    clean_price_str = "0"
                price_val = int(clean_price_str)
            except Exception:
                errors.append({"row": line_idx, "sku": raw_sku, "error": f"Giá không hợp lệ: {price_str}"})
                continue

            # Sanitize CSV Formula Injection (CWE-1236)
            sku = sanitize_csv_formula(raw_sku)
            name = sanitize_csv_formula(raw_name)

            tier_type = sanitize_csv_formula(get_val(header_map.get("tier_type") or header_map.get("tier")))
            short_desc = sanitize_csv_formula(get_val(header_map.get("short_desc") or header_map.get("motangan")))
            full_desc = sanitize_csv_formula(get_val(header_map.get("full_desc") or header_map.get("motachitiet")))
            deliv_raw = get_val(header_map.get("deliverables") or header_map.get("quyenloi"))
            pol_raw = get_val(header_map.get("policies") or header_map.get("chinhsach"))

            # Deliverables and policies list parsing with formula sanitization
            deliv_list = [
                sanitize_csv_formula(d.strip())
                for d in re.split(r"[;\n]", deliv_raw)
                if d.strip()
            ] if deliv_raw else []
            pol_list = [
                sanitize_csv_formula(p.strip())
                for p in re.split(r"[;\n]", pol_raw)
                if p.strip()
            ] if pol_raw else []

            prod_dict = {
                "sku": sku,
                "name": name,
                "price_vnd": price_val,
                "tier_type": tier_type or None,
                "short_desc": short_desc or None,
                "full_desc": full_desc or None,
                "deliverables": deliv_list,
                "policies": pol_list,
                "is_active": True,
            }

            try:
                # Upsert to SQLite without immediate individual ChromaDB sync
                prod = self.upsert_product(db, prod_dict, project_id=project_id, sync_vector=False)
                imported_products.append(prod)
                imported_count += 1
            except Exception as exc:
                errors.append({"row": line_idx, "sku": raw_sku, "error": str(exc)})

        # Batch synchronize all imported products to ChromaDB in a single operation
        if imported_products:
            self._sync_products_batch_to_chroma(imported_products)

        return {"imported_count": imported_count, "errors": errors}
