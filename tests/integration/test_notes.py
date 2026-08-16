"""Requires the real pgvector container and Ollama running. Always writes into
tmp_path, never the configured real vault - see conftest.ctx for why."""

from backend.ingestion.sources import FileSource, ObsidianSource
from backend.notes.writer import NoteWriter


def make_writer(ctx, vault_path):
    return NoteWriter(vault_path, ctx.repository, ctx.embeddings, ctx.pipeline)


async def test_create_note_writes_file_with_frontmatter_and_heading(ctx, clean_documents, tmp_path):
    writer = make_writer(ctx, tmp_path)
    result = await writer.create_note("My New Note", "Some content about testing.")

    clean_documents.append(str(result.path.resolve()))

    assert result.path.exists()
    text = result.path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "source: second-brain" in text
    assert "# My New Note" in text
    assert "Some content about testing." in text


async def test_create_note_is_indexed_immediately(ctx, clean_documents, tmp_path):
    writer = make_writer(ctx, tmp_path)
    result = await writer.create_note("Searchable Note", "Unique phrase: zxqwplotchi.")
    clean_documents.append(str(result.path.resolve()))

    doc = await ctx.repository.get_by_source_path(str(result.path.resolve()))
    assert doc is not None  # indexed without a separate manual sync step


async def test_create_note_never_overwrites_an_existing_note(ctx, clean_documents, tmp_path):
    writer = make_writer(ctx, tmp_path)

    first = await writer.create_note("Duplicate Title", "First version.")
    clean_documents.append(str(first.path.resolve()))
    second = await writer.create_note("Duplicate Title", "Second version.")
    clean_documents.append(str(second.path.resolve()))

    assert first.path != second.path
    assert first.path.read_text(encoding="utf-8").__contains__("First version.")
    assert second.path.name == "Duplicate Title (2).md"


async def test_create_note_links_to_related_existing_notes(ctx, clean_documents, tmp_path):
    writer = make_writer(ctx, tmp_path)

    existing = await writer.create_note(
        "GRUB Bootloader Basics",
        "GRUB is a bootloader that loads the Linux kernel. grub-install writes "
        "the boot sector; update-grub regenerates grub.cfg.",
    )
    clean_documents.append(str(existing.path.resolve()))

    new_note = await writer.create_note(
        "GRUB Rescue Mode Notes",
        "When GRUB drops to a rescue prompt, run grub-install to fix the boot sector.",
    )
    clean_documents.append(str(new_note.path.resolve()))

    assert any(r.title == "GRUB Bootloader Basics" for r in new_note.related)

    text = new_note.path.read_text(encoding="utf-8")
    assert "## Related" in text
    assert "[[GRUB Bootloader Basics]]" in text


async def test_unrelated_note_gets_no_forced_links(ctx, clean_documents, tmp_path):
    writer = make_writer(ctx, tmp_path)

    unrelated = await writer.create_note(
        "Grocery List", "Milk, eggs, bread, and coffee for the week."
    )
    clean_documents.append(str(unrelated.path.resolve()))

    text = unrelated.path.read_text(encoding="utf-8")
    # No fabricated relationships just to fill the section - real personal
    # docs about Linux/AWS/projects exist in the shared corpus and must not
    # be force-linked to a grocery list.
    assert "## Related" not in text


async def test_created_notes_are_cleaned_up_by_a_later_vault_sync(ctx, clean_documents, tmp_path):
    # A note created through NoteWriter is a real file inside the vault, so
    # deleting it from disk (as the user would in Obsidian) must make a
    # later vault sync notice and remove it - not leave an orphaned row
    # behind because it was indexed as source_type="file" instead of
    # "obsidian". Regression test for exactly that bug.
    writer = make_writer(ctx, tmp_path)
    created = await writer.create_note("Throwaway Note", "Temporary content.")
    clean_documents.append(str(created.path.resolve()))

    doc = await ctx.repository.get_by_source_path(str(created.path.resolve()))
    assert doc.source_type == "obsidian"

    created.path.unlink()
    sync_result = await ctx.pipeline.sync_vault(ObsidianSource(tmp_path), tmp_path)

    assert str(created.path.resolve()) in sync_result.deleted
    assert await ctx.repository.get_by_source_path(str(created.path.resolve())) is None
