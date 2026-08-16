from backend.ingestion.chunker import chunk_markdown


def test_chunk_respects_headings():
    text = "# Title\n\nIntro text.\n\n## Section A\n\nContent A.\n\n## Section B\n\nContent B.\n"
    chunks = chunk_markdown(text, title="Doc", chunk_size=1000, chunk_overlap=0)

    headings = [c.heading_path for c in chunks]
    assert "Title > Section A" in headings
    assert "Title > Section B" in headings
    assert not any("Content A" in c.content and "Content B" in c.content for c in chunks)


def test_chunk_size_is_respected_with_hard_wrap_fallback():
    long_para = "word " * 500  # one huge paragraph, no heading, no natural break
    chunks = chunk_markdown(long_para, title="Doc", chunk_size=300, chunk_overlap=50)

    assert len(chunks) > 1
    assert all(len(c.content) <= 300 for c in chunks)


def test_chunk_index_is_sequential():
    text = "# A\n\nfoo\n\n# B\n\nbar\n"
    chunks = chunk_markdown(text, title="Doc")
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_empty_document_produces_no_chunks():
    assert chunk_markdown("   \n\n  ", title="Doc") == []
