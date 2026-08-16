"""Requires the real pgvector container and Ollama running."""

from backend.ingestion.sources import ObsidianSource


async def test_sync_creates_notes_from_a_fresh_vault(ctx, clean_documents, tmp_path):
    (tmp_path / "Linux").mkdir()
    (tmp_path / "Linux" / "networking.md").write_text(
        "# Networking\n\nip addr shows interface state.\n"
    )

    doc_path = str((tmp_path / "Linux" / "networking.md").resolve())
    clean_documents.append(doc_path)

    result = await ctx.pipeline.sync_vault(ObsidianSource(tmp_path), tmp_path)

    assert len(result.indexed) == 1
    assert result.indexed[0].status == "created"
    assert result.deleted == []

    doc = await ctx.repository.get_by_source_path(doc_path)
    assert doc is not None
    assert doc.category == "Linux"  # folder-as-category


async def test_sync_removes_notes_deleted_from_disk(ctx, clean_documents, tmp_path):
    note = tmp_path / "temp-note.md"
    note.write_text("# Temp\n\nThis note is about to be deleted.\n")
    doc_path = str(note.resolve())
    clean_documents.append(doc_path)

    first = await ctx.pipeline.sync_vault(ObsidianSource(tmp_path), tmp_path)
    assert first.indexed[0].status == "created"
    assert await ctx.repository.get_by_source_path(doc_path) is not None

    note.unlink()
    second = await ctx.pipeline.sync_vault(ObsidianSource(tmp_path), tmp_path)

    assert second.indexed == []  # nothing left to discover
    assert second.deleted == [doc_path]
    assert await ctx.repository.get_by_source_path(doc_path) is None


async def test_sync_is_scoped_to_the_vault_and_does_not_touch_other_documents(
    ctx, clean_documents, tmp_path
):
    from backend.ingestion.sources import FileSource

    unrelated = tmp_path / "unrelated-upload.md"
    unrelated.write_text("# Unrelated\n\nIndexed via plain file upload, not the vault.\n")
    clean_documents.append(str(unrelated.resolve()))
    await ctx.pipeline.index_source(FileSource([unrelated]))

    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()

    # First sync with nothing in the vault yet: the unrelated upload must
    # survive, since it's outside the vault path prefix entirely.
    empty_sync = await ctx.pipeline.sync_vault(ObsidianSource(vault_dir), vault_dir)
    assert empty_sync.indexed == []
    assert empty_sync.deleted == []
    assert await ctx.repository.get_by_source_path(str(unrelated.resolve())) is not None

    # Now add a note to the vault and sync again.
    vault_note = vault_dir / "note.md"
    vault_note.write_text("# Vault note\n\nContent.\n")
    clean_documents.append(str(vault_note.resolve()))

    result = await ctx.pipeline.sync_vault(ObsidianSource(vault_dir), vault_dir)
    assert result.indexed[0].status == "created"
    assert await ctx.repository.get_by_source_path(str(unrelated.resolve())) is not None
