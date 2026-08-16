"""Requires the real pgvector container and Ollama running. Always uses
tmp_path as the vault, never the real configured one."""

from backend.ingestion.sources import ObsidianSource


async def test_frontmatter_domain_and_category_override_folder_fallback(ctx, clean_documents, tmp_path):
    (tmp_path / "Linux").mkdir()
    note = tmp_path / "Linux" / "grub.md"
    note.write_text(
        "---\n"
        "domain: technology\n"
        "category: bootloaders\n"
        "---\n\n"
        "# GRUB\n\nBoot loader notes.\n"
    )
    clean_documents.append(str(note.resolve()))

    await ctx.pipeline.index_source(ObsidianSource(tmp_path))

    doc = await ctx.repository.get_by_source_path(str(note.resolve()))
    assert doc.domain == "technology"
    assert doc.category == "bootloaders"  # frontmatter wins over the "Linux" folder name
    assert doc.metadata["frontmatter"]["domain"] == "technology"


async def test_frontmatter_absent_falls_back_to_folder_as_category(ctx, clean_documents, tmp_path):
    (tmp_path / "AWS").mkdir()
    note = tmp_path / "AWS" / "vpc.md"
    note.write_text("# VPC\n\nNo frontmatter here.\n")
    clean_documents.append(str(note.resolve()))

    await ctx.pipeline.index_source(ObsidianSource(tmp_path))

    doc = await ctx.repository.get_by_source_path(str(note.resolve()))
    assert doc.category == "AWS"
    assert doc.domain is None


async def test_frontmatter_is_stripped_from_chunk_content(ctx, clean_documents, tmp_path):
    note = tmp_path / "note.md"
    note.write_text("---\ntags: [test]\n---\n\n# Title\n\nActual body text.\n")
    clean_documents.append(str(note.resolve()))

    await ctx.pipeline.index_source(ObsidianSource(tmp_path))

    doc = await ctx.repository.get_by_source_path(str(note.resolve()))
    results = await ctx.repository.hybrid_search(
        await ctx.embeddings.embed("Actual body text"), "Actual body text", 5
    )
    matching = [r for r in results if r.document_id == doc.id]
    assert matching
    assert "tags:" not in matching[0].content  # raw frontmatter never reached a chunk


async def test_tags_are_stored_and_queryable(ctx, clean_documents, tmp_path):
    note = tmp_path / "note.md"
    note.write_text("---\ntags: [linux, boot, grub]\n---\n\n# GRUB\n\nBody.\n")
    clean_documents.append(str(note.resolve()))

    await ctx.pipeline.index_source(ObsidianSource(tmp_path))

    doc = await ctx.repository.get_by_source_path(str(note.resolve()))
    assert await ctx.repository.get_tags(doc.id) == ["boot", "grub", "linux"]  # alphabetical


async def test_wikilinks_become_queryable_relationships(ctx, clean_documents, tmp_path):
    note = tmp_path / "grub.md"
    note.write_text("# GRUB\n\nSee [[Linux Boot Process]] and [[UEFI]].\n")
    clean_documents.append(str(note.resolve()))

    await ctx.pipeline.index_source(ObsidianSource(tmp_path))

    doc = await ctx.repository.get_by_source_path(str(note.resolve()))
    assert await ctx.repository.get_outgoing_links(doc.id) == ["Linux Boot Process", "UEFI"]


async def test_backlinks_resolve_once_the_target_note_is_indexed(ctx, clean_documents, tmp_path):
    # Link a note to a target that doesn't exist yet - a deliberate, common
    # PKM pattern - then verify the backlink appears the moment the target
    # *is* indexed, with no separate backfill step required.
    source_note = tmp_path / "grub.md"
    source_note.write_text("# GRUB\n\nSee [[Linux Boot Process]].\n")
    clean_documents.append(str(source_note.resolve()))
    await ctx.pipeline.index_source(ObsidianSource(tmp_path))

    assert await ctx.repository.get_backlinks("Linux Boot Process") != []  # resolves by title, pre-existing

    target_note = tmp_path / "Linux Boot Process.md"
    target_note.write_text("# Linux Boot Process\n\nHow Linux boots.\n")
    clean_documents.append(str(target_note.resolve()))
    await ctx.pipeline.index_source(ObsidianSource(tmp_path))

    backlinks = await ctx.repository.get_backlinks("Linux Boot Process")
    assert any(b.source_path == str(source_note.resolve()) for b in backlinks)


async def test_incremental_hash_detects_a_frontmatter_only_change(ctx, clean_documents, tmp_path):
    note = tmp_path / "note.md"
    note.write_text("---\ntags: [draft]\n---\n\n# Title\n\nBody unchanged.\n")
    clean_documents.append(str(note.resolve()))

    first = await ctx.pipeline.index_source(ObsidianSource(tmp_path))
    assert first[0].status == "created"

    # Body text is identical - only the frontmatter tag changes.
    note.write_text("---\ntags: [reviewed]\n---\n\n# Title\n\nBody unchanged.\n")
    second = await ctx.pipeline.index_source(ObsidianSource(tmp_path))
    assert second[0].status == "updated"  # not "unchanged" - the raw file did change

    doc = await ctx.repository.get_by_source_path(str(note.resolve()))
    assert await ctx.repository.get_tags(doc.id) == ["reviewed"]


async def test_deleting_a_note_cascades_its_tags_and_relationships(ctx, clean_documents, tmp_path):
    note = tmp_path / "note.md"
    note.write_text("---\ntags: [temp]\n---\n\n# Title\n\nSee [[Something]].\n")
    clean_documents.append(str(note.resolve()))

    await ctx.pipeline.index_source(ObsidianSource(tmp_path))
    doc = await ctx.repository.get_by_source_path(str(note.resolve()))
    document_id = doc.id

    await ctx.pipeline.sync_vault(ObsidianSource(tmp_path), tmp_path)  # baseline, nothing deleted yet
    note.unlink()
    await ctx.pipeline.sync_vault(ObsidianSource(tmp_path), tmp_path)

    assert await ctx.repository.get_by_source_path(str(note.resolve())) is None
    assert await ctx.repository.get_tags(document_id) == []
    assert await ctx.repository.get_outgoing_links(document_id) == []
