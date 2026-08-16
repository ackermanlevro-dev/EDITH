"""Requires the real pgvector container and Ollama running - both are local
and free, so this is allowed to hit them directly rather than mock."""

from backend.ingestion.sources import FileSource


async def test_index_then_reindex_is_idempotent(ctx, clean_documents, tmp_path):
    doc_path = tmp_path / "test-doc.md"
    doc_path.write_text("# Test\n\nSome content about kubectl and docker-compose.\n")
    clean_documents.append(str(doc_path.resolve()))

    source = FileSource([doc_path])

    first = await ctx.pipeline.index_source(source)
    assert first[0].status == "created"
    assert first[0].chunk_count > 0

    second = await ctx.pipeline.index_source(source)
    assert second[0].status == "unchanged"
    assert second[0].chunk_count == 0  # unchanged skips re-embedding entirely

    doc = await ctx.repository.get_by_source_path(str(doc_path.resolve()))
    stored = await ctx.repository.chunk_count(doc.id)
    assert stored == first[0].chunk_count  # no duplicate rows from the no-op reindex


async def test_modifying_document_replaces_chunks_without_duplicating(ctx, clean_documents, tmp_path):
    doc_path = tmp_path / "test-doc2.md"
    doc_path.write_text("# Test\n\nOriginal content.\n")
    clean_documents.append(str(doc_path.resolve()))
    source = FileSource([doc_path])

    await ctx.pipeline.index_source(source)
    doc = await ctx.repository.get_by_source_path(str(doc_path.resolve()))

    doc_path.write_text(
        "# Test\n\nCompletely different content now, describing something else entirely.\n"
    )
    result = await ctx.pipeline.index_source(source)
    assert result[0].status == "updated"

    stored = await ctx.repository.chunk_count(doc.id)
    assert stored == result[0].chunk_count
    assert stored >= 1
