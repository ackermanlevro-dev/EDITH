"""Requires the real pgvector container and Ollama running."""

from backend.ingestion.sources import FileSource
from tests.pdf_fixtures import make_test_pdf


async def test_pdf_is_indexed_and_searchable(ctx, clean_documents, tmp_path):
    pdf_path = tmp_path / "manual.pdf"
    pdf_path.write_bytes(make_test_pdf("Kubernetes zxqwplotchi orchestration"))
    clean_documents.append(str(pdf_path.resolve()))

    results = await ctx.pipeline.index_source(FileSource([pdf_path]))
    assert results[0].status == "created"
    assert results[0].chunk_count > 0

    doc = await ctx.repository.get_by_source_path(str(pdf_path.resolve()))
    assert doc.mime_type == "application/pdf"

    search_results = await ctx.repository.hybrid_search(
        await ctx.embeddings.embed("zxqwplotchi"), "zxqwplotchi", 5
    )
    assert any(r.document_id == doc.id for r in search_results)


async def test_pdf_reindex_is_idempotent(ctx, clean_documents, tmp_path):
    pdf_path = tmp_path / "manual.pdf"
    pdf_path.write_bytes(make_test_pdf("Stable content"))
    clean_documents.append(str(pdf_path.resolve()))

    source = FileSource([pdf_path])
    first = await ctx.pipeline.index_source(source)
    assert first[0].status == "created"

    second = await ctx.pipeline.index_source(source)
    assert second[0].status == "unchanged"
