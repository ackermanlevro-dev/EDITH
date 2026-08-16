"""Requires the real pgvector container and Ollama running."""

from backend.ingestion.sources import FileSource


async def test_general_question_answers_without_any_indexed_documents(ctx):
    result = await ctx.generator.answer("What is Docker?")
    assert result.answer.strip()


async def test_personal_question_uses_indexed_document(ctx, clean_documents, tmp_path):
    doc_path = tmp_path / "grub-test.md"
    doc_path.write_text(
        "# GRUB rescue\n\nI learned that GRUB loads in two stages, and "
        "grub-install must be re-run after a disk layout change.\n"
    )
    clean_documents.append(str(doc_path.resolve()))
    await ctx.pipeline.index_source(FileSource([doc_path]))

    result = await ctx.generator.answer("What did I write about GRUB?")
    assert result.used_personal_knowledge
    assert any("grub-test.md" in s.source_path for s in result.sources)


async def test_domain_agnostic_retrieval_across_three_unrelated_domains(ctx, clean_documents, tmp_path):
    linux_doc = tmp_path / "linux-note.md"
    linux_doc.write_text("# Linux\n\nsystemctl restarts services; journalctl reads their logs.\n")
    aws_doc = tmp_path / "aws-note.md"
    aws_doc.write_text("# AWS\n\nEC2 instances get permissions via IAM instance profiles.\n")
    project_doc = tmp_path / "project-note.md"
    project_doc.write_text(
        "# My Project\n\nI decided to use FastAPI for the backend of my personal "
        "project, a knowledge management tool. FastAPI's async support made it a "
        "better fit than Flask for talking to Ollama and Postgres concurrently.\n"
    )

    for d in (linux_doc, aws_doc, project_doc):
        clean_documents.append(str(d.resolve()))
        await ctx.pipeline.index_source(FileSource([d]))

    aws_result = await ctx.generator.answer("What do my notes say about AWS IAM?")
    assert any("aws-note.md" in s.source_path for s in aws_result.sources)

    project_result = await ctx.generator.answer("What do my notes say about my project?")
    assert any("project-note.md" in s.source_path for s in project_result.sources)
