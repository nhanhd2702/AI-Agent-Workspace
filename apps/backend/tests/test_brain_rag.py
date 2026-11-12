"""Tests for Brain Module — Document Ingestion & ChromaDB RAG (Task 4.1)."""

from __future__ import annotations

import csv
import io
from pathlib import Path
import time

import docx
from fastapi.testclient import TestClient
import pypdf
import pytest

from app.brain.ingest import DocumentIngestor, IngestResult, ScannedPdfError, UnsupportedFormatError
from app.brain.retriever import BrainRetriever, ChunkHit
from app.config import AppSettings
from app.main import create_app


@pytest.fixture
def mock_pdf_empty_text(tmp_path: Path) -> Path:
    """Creates a valid PDF file with zero extractable text (simulating scanned image PDF)."""
    pdf_path = tmp_path / "scanned_image.pdf"
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with open(pdf_path, "wb") as f:
        writer.write(f)
    return pdf_path


@pytest.fixture
def sample_docx_file(tmp_path: Path) -> Path:
    """Creates a valid .docx file with formatted paragraphs and table."""
    doc_path = tmp_path / "policies.docx"
    doc = docx.Document()
    doc.add_heading("Chính Sách Hoàn Tiền", level=1)
    doc.add_paragraph("Khách hàng được hoàn tiền trong vòng 30 ngày kể từ ngày đăng ký khóa học.")
    table = doc.add_table(rows=2, cols=2)
    table.rows[0].cells[0].text = "Khóa Học"
    table.rows[0].cells[1].text = "Thời Hạn Hoàn Tiền"
    table.rows[1].cells[0].text = "AI Engineer Pro"
    table.rows[1].cells[1].text = "30 ngày hoàn 100%"
    doc.save(str(doc_path))
    return doc_path


@pytest.fixture
def sample_csv_file(tmp_path: Path) -> Path:
    """Creates a valid .csv file with business tabular data."""
    csv_path = tmp_path / "pricing.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Gói Dịch Vụ", "Thời Lượng", "Đơn Giá", "Ưu Đãi"])
        writer.writerow(["Gói Coach 1:1", "8 tuần", "5000000 VND", "Giảm 10% nếu thanh toán sớm"])
        writer.writerow(["Gói Doanh Nghiệp", "6 tháng", "25000000 VND", "Kèm mentor 24/7"])
    return csv_path


def test_scanned_pdf_rejected_with_clear_error(tmp_path: Path, mock_pdf_empty_text: Path):
    """PDF without extractable text must raise ScannedPdfError containing 'PDF dạng ảnh'."""
    ingestor = DocumentIngestor(chroma_dir=tmp_path / "chroma")
    with pytest.raises(ScannedPdfError, match="PDF dạng ảnh"):
        ingestor.ingest_file(mock_pdf_empty_text, collection="general")


def test_rag_filters_below_0_7_and_deduplicates_sha256(tmp_path: Path):
    """Tests SHA-256 deduplication and score filtering >= 0.7."""
    doc = tmp_path / "faq.txt"
    doc.write_text("Gói Coach giảm cân giá 5 triệu đồng cho lộ trình 8 tuần.", encoding="utf-8")
    ingestor = DocumentIngestor(chroma_dir=tmp_path / "chroma")
    r1 = ingestor.ingest_file(doc, collection="policies")
    r2 = ingestor.ingest_file(doc, collection="policies")
    assert r1.chunk_count >= 1
    assert r2.deduplicated is True
    assert r1.sha256 == r2.sha256
    retriever = BrainRetriever(chroma_dir=tmp_path / "chroma")
    hits = retriever.search("giá gói coach", collections=["policies"], min_similarity=0.7)
    assert all(h.score >= 0.7 for h in hits)


def test_ingest_and_retrieve_multiple_formats(
    tmp_path: Path,
    sample_docx_file: Path,
    sample_csv_file: Path,
):
    """Parses .docx, .txt, .md, .csv and retrieves relevant chunks."""
    chroma_dir = tmp_path / "chroma"
    ingestor = DocumentIngestor(chroma_dir=chroma_dir)

    # Ingest .docx
    res_docx = ingestor.ingest_file(sample_docx_file, collection="hr")
    assert res_docx.chunk_count >= 1
    assert res_docx.deduplicated is False

    # Ingest .csv
    res_csv = ingestor.ingest_file(sample_csv_file, collection="finance")
    assert res_csv.chunk_count >= 1

    # Ingest .md
    md_file = tmp_path / "architecture.md"
    md_file.write_text("# Kiến Trúc Hệ Thống\nHệ thống sử dụng ChromaDB làm vector database lưu trữ tài liệu.", encoding="utf-8")
    res_md = ingestor.ingest_file(md_file, collection="tech")
    assert res_md.chunk_count >= 1

    # Ingest unsupported format
    unsupported_file = tmp_path / "binary.bin"
    unsupported_file.write_bytes(b"\x00\x01\x02\x03\x04")
    with pytest.raises(UnsupportedFormatError):
        ingestor.ingest_file(unsupported_file, collection="tech")

    retriever = BrainRetriever(chroma_dir=chroma_dir)
    # Search across multiple collections
    hits = retriever.search(
        "Chính sách hoàn tiền 30 ngày khóa học AI",
        collections=["hr", "tech"],
        top_k=5,
        min_similarity=0.4,
    )
    assert len(hits) >= 1
    assert any("hoàn tiền" in h.text.lower() for h in hits)


def test_valid_pdf_with_page_metadata(tmp_path: Path):
    """Tests that a multi-page PDF extracts text and preserves page metadata."""
    from unittest.mock import MagicMock, patch

    pdf_path = tmp_path / "manual.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 dummy binary content")

    mock_page1 = MagicMock()
    mock_page1.extract_text.return_value = "Nội dung trang 1 về chính sách bảo hành sản phẩm."
    mock_page2 = MagicMock()
    mock_page2.extract_text.return_value = "Nội dung trang 2 về quy trình bảo dưỡng thiết bị định kỳ."

    mock_reader = MagicMock()
    mock_reader.pages = [mock_page1, mock_page2]

    chroma_dir = tmp_path / "chroma"
    ingestor = DocumentIngestor(chroma_dir=chroma_dir)

    with patch("pypdf.PdfReader", return_value=mock_reader):
        res = ingestor.ingest_file(pdf_path, collection="manuals")

    assert res.chunk_count == 2
    retriever = BrainRetriever(chroma_dir=chroma_dir)
    hits = retriever.search("chính sách bảo hành", collections=["manuals"], min_similarity=0.4)
    assert len(hits) >= 1
    hit_p1 = [h for h in hits if "chính sách" in h.text.lower()][0]
    assert hit_p1.page == 1


def test_cache_ttl_and_invalidation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """5-minute TTL cache returns cached results and invalidates on ingestion or deletion."""
    chroma_dir = tmp_path / "chroma"
    ingestor = DocumentIngestor(chroma_dir=chroma_dir)
    retriever = BrainRetriever(chroma_dir=chroma_dir)

    doc1 = tmp_path / "doc1.txt"
    doc1.write_text("Tài liệu hướng dẫn an ninh thông tin bảo mật dữ liệu doanh nghiệp.", encoding="utf-8")
    r1 = ingestor.ingest_file(doc1, collection="security")

    # Initial query
    hits1 = retriever.search("an ninh thông tin bảo mật", collections=["security"], min_similarity=0.5)
    assert len(hits1) >= 1

    # Query again within TTL - should hit cache
    hits2 = retriever.search("an ninh thông tin bảo mật", collections=["security"], min_similarity=0.5)
    assert hits1 == hits2

    # Ingestion of new doc invalidates cache
    doc2 = tmp_path / "doc2.txt"
    doc2.write_text("Cập nhật quy định mới về an ninh mạng năm 2026.", encoding="utf-8")
    ingestor.ingest_file(doc2, collection="security")

    # Cache should be cleared
    hits3 = retriever.search("an ninh thông tin bảo mật", collections=["security"], min_similarity=0.5)
    assert len(hits3) >= 1

    # Test deletion invalidates cache
    retriever.delete_document(r1.doc_id)
    assert len(retriever.list_documents(collection="security")) == 1

    # Advance time past 300s TTL
    current_time = time.time()
    monkeypatch.setattr(time, "time", lambda: current_time + 301)
    hits_after_ttl = retriever.search("quy định an ninh mạng", collections=["security"], min_similarity=0.5)
    assert len(hits_after_ttl) >= 1


def test_limits_enforcement_max_docs_and_mb(tmp_path: Path):
    """Enforces max_docs <= 100 and max_total_mb <= 50MB caps."""
    chroma_dir = tmp_path / "chroma"
    ingestor = DocumentIngestor(chroma_dir=chroma_dir, max_docs=2, max_total_mb=0.001)

    f1 = tmp_path / "f1.txt"
    f1.write_text("Content 1", encoding="utf-8")
    f2 = tmp_path / "f2.txt"
    f2.write_text("Content 2", encoding="utf-8")
    f3 = tmp_path / "f3.txt"
    f3.write_text("Content 3", encoding="utf-8")

    ingestor.ingest_file(f1, collection="general")
    ingestor.ingest_file(f2, collection="general")

    # Exceeds max_docs=2
    with pytest.raises(ValueError, match="giới hạn số lượng tài liệu"):
        ingestor.ingest_file(f3, collection="general")

    # Test size limit cap
    ingestor_size = DocumentIngestor(chroma_dir=tmp_path / "chroma_size", max_docs=10, max_total_mb=0.0001)  # ~100 bytes
    large_file = tmp_path / "large.txt"
    large_file.write_text("A" * 1500, encoding="utf-8")
    with pytest.raises(ValueError, match="dung lượng"):
        ingestor_size.ingest_file(large_file, collection="general")


def test_brain_api_endpoints_full_lifecycle(tmp_path: Path):
    """Tests POST/GET/DELETE /api/v1/brain/documents and POST /api/v1/brain/search."""
    settings = AppSettings(
        workspace_dir=tmp_path / "workspace",
        chroma_dir=tmp_path / "chroma",
        local_auth_token="test-secret-token",
    )
    app = create_app(settings)
    client = TestClient(app)
    headers = {"X-Local-Auth-Token": "test-secret-token"}

    # 1. Ingest via multipart file upload
    file_content = "Hướng dẫn sử dụng hệ thống AI Workspace và quản lý phòng ban.".encode("utf-8")
    response = client.post(
        "/api/v1/brain/documents",
        headers=headers,
        files={"file": ("guide.txt", io.BytesIO(file_content), "text/plain")},
        data={"collection": "manuals"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    doc_id = data["doc_id"]
    assert data["filename"] == "guide.txt"
    assert data["collection"] == "manuals"
    assert data["chunk_count"] >= 1
    assert data["deduplicated"] is False

    # 2. Ingest duplicate file upload -> deduplicated is True
    dup_response = client.post(
        "/api/v1/brain/documents",
        headers=headers,
        files={"file": ("guide.txt", io.BytesIO(file_content), "text/plain")},
        data={"collection": "manuals"},
    )
    assert dup_response.status_code == 200
    assert dup_response.json()["deduplicated"] is True

    # 3. Ingest scanned empty PDF -> 400 Bad Request with "PDF dạng ảnh"
    pdf_path = tmp_path / "empty.pdf"
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with open(pdf_path, "wb") as f:
        writer.write(f)
    with open(pdf_path, "rb") as f:
        pdf_err_response = client.post(
            "/api/v1/brain/documents",
            headers=headers,
            files={"file": ("empty.pdf", f, "application/pdf")},
            data={"collection": "manuals"},
        )
    assert pdf_err_response.status_code == 400
    assert "PDF dạng ảnh" in pdf_err_response.json()["detail"]

    # 4. Ingest unsupported format -> 422
    unsupported_response = client.post(
        "/api/v1/brain/documents",
        headers=headers,
        files={"file": ("test.bin", io.BytesIO(b"\x00\x01\x02"), "application/octet-stream")},
        data={"collection": "manuals"},
    )
    assert unsupported_response.status_code == 422

    # 5. List documents
    list_response = client.get("/api/v1/brain/documents", headers=headers)
    assert list_response.status_code == 200
    docs = list_response.json()
    assert len(docs) == 1
    assert docs[0]["doc_id"] == doc_id

    # 6. Search
    search_response = client.post(
        "/api/v1/brain/search",
        headers=headers,
        json={
            "query": "hướng dẫn quản trị hệ thống AI",
            "collections": ["manuals"],
            "top_k": 3,
            "min_similarity": 0.3,
        },
    )
    assert search_response.status_code == 200
    hits = search_response.json()
    assert len(hits) >= 1
    assert hits[0]["doc_id"] == doc_id

    # 7. Delete document
    del_response = client.delete(f"/api/v1/brain/documents/{doc_id}", headers=headers)
    assert del_response.status_code == 200

    # 8. List after delete should be empty
    list_after = client.get("/api/v1/brain/documents", headers=headers)
    assert list_after.status_code == 200
    assert len(list_after.json()) == 0

    # 9. Delete non-existent doc -> 404
    del_404 = client.delete(f"/api/v1/brain/documents/{doc_id}", headers=headers)
    assert del_404.status_code == 404


def test_secret_masking_in_search_results(tmp_path: Path):
    """Ensures API keys, tokens and passwords in document chunks are masked in search outputs."""
    settings = AppSettings(
        workspace_dir=tmp_path / "workspace",
        chroma_dir=tmp_path / "chroma",
        local_auth_token="test-secret-token",
    )
    app = create_app(settings)
    client = TestClient(app)
    headers = {"X-Local-Auth-Token": "test-secret-token"}

    sensitive_content = (
        "Cấu hình tích hợp OpenAI: api_key='sk-abcdef1234567890abcdef1234567890' "
        "và mật khẩu database password: 'supersecretpassword123' cho phòng ban."
    ).encode("utf-8")

    ingest_res = client.post(
        "/api/v1/brain/documents",
        headers=headers,
        files={"file": ("secrets.txt", io.BytesIO(sensitive_content), "text/plain")},
        data={"collection": "configs"},
    )
    assert ingest_res.status_code == 200

    search_res = client.post(
        "/api/v1/brain/search",
        headers=headers,
        json={
            "query": "cấu hình openai api_key và password",
            "collections": ["configs"],
            "top_k": 3,
            "min_similarity": 0.2,
        },
    )
    assert search_res.status_code == 200
    hits = search_res.json()
    assert len(hits) >= 1
    hit_text = hits[0]["text"]
    assert "sk-abcdef1234567890abcdef1234567890" not in hit_text
    assert "supersecretpassword123" not in hit_text
    assert "***REDACTED***" in hit_text


def test_brain_api_json_ingest_and_auth(tmp_path: Path):
    """Tests JSON body file_path ingestion and auth token enforcement."""
    settings = AppSettings(
        workspace_dir=tmp_path / "workspace",
        chroma_dir=tmp_path / "chroma",
        local_auth_token="secure-token",
    )
    app = create_app(settings)
    client = TestClient(app)

    # 1. Auth failure without token
    res_no_auth = client.get("/api/v1/brain/documents")
    assert res_no_auth.status_code == 401

    headers = {"X-Local-Auth-Token": "secure-token"}

    # 2. Ingest via JSON file_path
    local_doc = tmp_path / "local_policy.md"
    local_doc.write_text("# Chính sách an toàn\nTuân thủ quy trình xác thực đa yếu tố.", encoding="utf-8")

    res_json = client.post(
        "/api/v1/brain/documents",
        headers=headers,
        json={"file_path": str(local_doc), "collection": "policies"},
    )
    assert res_json.status_code == 200
    assert res_json.json()["filename"] == "local_policy.md"
    assert res_json.json()["collection"] == "policies"
    assert res_json.json()["deduplicated"] is False

    # 3. Missing file_path in JSON
    res_bad_json = client.post(
        "/api/v1/brain/documents",
        headers=headers,
        json={"collection": "policies"},
    )
    assert res_bad_json.status_code == 422

    # 4. Non-existent file_path
    res_not_found = client.post(
        "/api/v1/brain/documents",
        headers=headers,
        json={"file_path": str(tmp_path / "non_existent.md"), "collection": "policies"},
    )
    assert res_not_found.status_code == 404

    # 5. Search unknown collection returns empty list
    search_empty = client.post(
        "/api/v1/brain/search",
        headers=headers,
        json={"query": "test", "collections": ["non_existent_col"], "top_k": 5, "min_similarity": 0.5},
    )
    assert search_empty.status_code == 200
    assert search_empty.json() == []
