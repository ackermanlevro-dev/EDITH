-- Second Brain — search index schema.
--
-- IMPORTANT: this database is a rebuildable SEARCH INDEX, not the source of
-- truth. The source of truth is the original files (Obsidian vault, uploaded
-- documents). Every row here must be derivable by re-running ingestion over
-- those files. Never store anything here that can't be regenerated.
--
-- Domains/categories/tags are free text, not enums — this system must stay
-- domain-agnostic (works for Linux notes today, AWS or a novel unrelated
-- topic tomorrow) without a schema change.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type   TEXT NOT NULL,              -- 'obsidian' | 'file' | future: 'web'
    source_path   TEXT NOT NULL UNIQUE,        -- canonical path/URI back to the source file
    title         TEXT,
    mime_type     TEXT,
    content_hash  TEXT NOT NULL,               -- sha256 of raw source content; drives incremental reindex
    domain        TEXT,                        -- free text: 'technology' | 'work' | 'personal' | ... | anything
    category      TEXT,                        -- free text, finer-grained than domain
    metadata      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_documents_domain ON documents (domain);
CREATE INDEX IF NOT EXISTS idx_documents_source_type ON documents (source_type);
CREATE INDEX IF NOT EXISTS idx_documents_metadata ON documents USING gin (metadata jsonb_path_ops);

-- Embedding dimension is 768, empirically measured from the installed
-- nomic-embed-text model (not assumed) — see docs/BUILD_LOG.md. If the
-- embedding model changes to one with a different output size, this column
-- (and the HNSW index below) must be rebuilt to match.
CREATE TABLE IF NOT EXISTS document_chunks (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id   UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index   INT NOT NULL,
    content       TEXT NOT NULL,
    heading_path  TEXT,                        -- e.g. "Troubleshooting > GRUB rescue"
    embedding     VECTOR(768) NOT NULL,
    metadata      JSONB NOT NULL DEFAULT '{}'::jsonb,
    content_tsv   TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON document_chunks (document_id);

-- HNSW over ivfflat: no need to pre-tune a "lists" parameter to the size of
-- the corpus, and this corpus will be small for a long time — HNSW's build
-- cost is a non-issue here and its recall is better by default.
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw
    ON document_chunks USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_chunks_content_tsv
    ON document_chunks USING gin (content_tsv);

CREATE TABLE IF NOT EXISTS tags (
    id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS document_tags (
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    tag_id      UUID NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (document_id, tag_id)
);
