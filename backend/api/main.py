from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles

from backend.api.schemas import (
    ChatRequest,
    ChatResponse,
    ConfigResponse,
    IndexRequest,
    IndexResponse,
    IndexResultItem,
    NoteCreateRequest,
    NoteCreateResponse,
    RelatedNoteItem,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
    SourceItem,
)
from backend.config.settings import get_settings
from backend.container import build_context
from backend.ingestion.sources import FileSource, ObsidianSource, parse_ignore_patterns

UPLOAD_DIR = Path("uploads")  # gitignored - uploaded documents live here, not in git


@asynccontextmanager
async def lifespan(app: FastAPI):
    ctx = await build_context(get_settings())
    app.state.ctx = ctx
    yield
    await ctx.close()


app = FastAPI(title="Second Brain", lifespan=lifespan)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/config", response_model=ConfigResponse)
async def get_config():
    """Only what the UI needs to render itself - never the database URL,
    credentials, or anything else from Settings."""
    s = app.state.ctx.settings
    return ConfigResponse(
        llm_model=s.llm_model,
        embedding_model=s.embedding_model,
        obsidian_vault_path=s.obsidian_vault_path,
        top_k=s.top_k,
        rag_enabled=s.rag_enabled,
    )


@app.post("/api/documents/index", response_model=IndexResponse)
async def index_documents(req: IndexRequest):
    ctx = app.state.ctx
    path = Path(req.path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {req.path}")

    if req.source_type == "obsidian":
        if not path.is_dir():
            raise HTTPException(status_code=400, detail=f"Not a directory: {req.path}")
        ignore = parse_ignore_patterns(ctx.settings.obsidian_ignore_patterns)
        source = ObsidianSource(path, ignore_patterns=ignore)
        sync_result = await ctx.pipeline.sync_vault(source, path)
        return IndexResponse(
            results=[
                IndexResultItem(source_path=r.source_path, status=r.status, chunk_count=r.chunk_count)
                for r in sync_result.indexed
            ],
            deleted=sync_result.deleted,
        )

    files = [path] if path.is_file() else sorted(path.rglob("*.md"))
    source = FileSource(files, domain=req.domain, category=req.category)
    results = await ctx.pipeline.index_source(source)
    return IndexResponse(
        results=[
            IndexResultItem(source_path=r.source_path, status=r.status, chunk_count=r.chunk_count)
            for r in results
        ]
    )


@app.post("/api/documents/upload", response_model=IndexResponse)
async def upload_document(
    file: UploadFile = File(...),
    domain: str | None = Form(None),
    category: str | None = Form(None),
):
    """The drag-and-drop path: browser sends bytes, not a server-side path.
    Markdown/text only for now - PDF/DOCX extraction is a later phase."""
    if not file.filename or not file.filename.lower().endswith((".md", ".txt")):
        raise HTTPException(status_code=400, detail="Only .md and .txt files are supported right now.")

    UPLOAD_DIR.mkdir(exist_ok=True)
    dest = UPLOAD_DIR / file.filename
    dest.write_bytes(await file.read())

    ctx = app.state.ctx
    source = FileSource([dest], domain=domain, category=category)
    results = await ctx.pipeline.index_source(source)
    return IndexResponse(
        results=[
            IndexResultItem(source_path=r.source_path, status=r.status, chunk_count=r.chunk_count)
            for r in results
        ]
    )


@app.post("/api/notes/create", response_model=NoteCreateResponse)
async def create_note(req: NoteCreateRequest):
    ctx = app.state.ctx
    if not ctx.notes:
        raise HTTPException(
            status_code=400,
            detail="OBSIDIAN_VAULT_PATH is not configured - there's nowhere to save a note.",
        )
    result = await ctx.notes.create_note(req.title, req.content, folder=req.folder, tags=req.tags)
    return NoteCreateResponse(
        path=str(result.path),
        related=[
            RelatedNoteItem(title=r.title, source_path=r.source_path, score=round(r.score, 4))
            for r in result.related
        ],
    )


@app.post("/api/knowledge/search", response_model=SearchResponse)
async def search_knowledge(req: SearchRequest):
    ctx = app.state.ctx
    top_k = req.top_k or ctx.settings.top_k
    query_embedding = await ctx.embeddings.embed(req.query)
    results = await ctx.repository.hybrid_search(query_embedding, req.query, top_k)
    return SearchResponse(
        results=[
            SearchResultItem(
                chunk_id=str(r.chunk_id),
                document_id=str(r.document_id),
                document_title=r.document_title,
                source_path=r.source_path,
                heading_path=r.heading_path,
                content=r.content,
                score=round(r.score, 4),
                vector_score=round(r.vector_score, 4),
                keyword_score=round(r.keyword_score, 4),
            )
            for r in results
        ]
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    ctx = app.state.ctx
    result = await ctx.generator.answer(req.question)
    return ChatResponse(
        answer=result.answer,
        intent=result.intent,
        used_personal_knowledge=result.used_personal_knowledge,
        sources=[SourceItem(**vars(s)) for s in result.sources],
    )


# Registered last so it never shadows the /api/* routes above - Starlette
# matches routes in registration order.
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
