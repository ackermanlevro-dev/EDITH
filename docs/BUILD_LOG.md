# Build Log

Chronological record of what's been done and why. Read this before making
architectural changes - it captures decisions and dead ends that aren't
obvious from the code alone.

## Phase 0 - Machine inspection

- Windows 10 Pro 10.0.19045 (x64)
- CPU: Intel Core i5-6300U, 2 cores / 4 threads, 2.4GHz (2016-era ULV laptop chip)
- RAM: 8,048 MB total, ~445-510 MB free at idle under normal use - **the binding
  constraint on every infrastructure decision below**
- GPU: Intel HD Graphics 520, integrated, no CUDA/ROCm
- Disk: 237.8 GB / 125.9 GB free - not a constraint
- Native PostgreSQL 16 already running as a Windows service on port 5432,
  pre-existing and unrelated to this project - **must not be modified**

## Phase 1 - Ollama + models

- winget unavailable; downloaded the official Windows installer from
  ollama.com and ran it silently.
- Installed Ollama 0.32.13, running natively as a background service.
- Pulled `qwen2.5:1.5b-instruct` (986 MB, chat) and `nomic-embed-text`
  (274 MB, embeddings). Both verified live via the Ollama API.

## Phase 2 - Vector database infrastructure

- pgvector has no official Windows binary - compiling it against the native
  Postgres 16 would need Visual Studio Build Tools (~4-6 GB). Chose Docker
  instead: `pgvector/pgvector:pg16`.
- Docker Desktop's engine wouldn't start (persistent 500 error) - root cause
  was WSL2 not being enabled. `wsl --install` needed **two** reboots: the
  first reboot fired before the install had actually finished, so a second
  `wsl --install` + reboot was needed to complete it.
- Container `second-brain-vectordb` now runs on host port **5433** (5432 was
  already taken by the native Postgres service). pgvector extension version
  **0.8.6**.
- Embedding dimension is **768** - measured empirically from a live call to
  the installed `nomic-embed-text` model, not assumed from documentation.
  If the embedding model ever changes, this number and the `VECTOR(768)`
  column/HNSW index in `database/schema.sql` must be rebuilt together.
- Python 3.12 was *not* actually installed despite `py -0p` listing it (the
  registry entry was stale - the folder it pointed to didn't exist). Backend
  runs on a project-local `.venv` using a freshly, separately installed
  Python 3.12.10 (`AppData\Local\Programs\Python\Python312`), installed
  per-user without touching PATH. System Python 3.14 is untouched.
- Backend kept **native** (not Dockerized) deliberately: Docker Desktop's own
  VM already costs real RAM on this machine, and containerizing the backend
  on top of that would pay the virtualization tax twice for no benefit at
  this scale.
- Added a second logical database, `secondbrain_test`, on the *same*
  container (not a separate container - no extra RAM cost) so automated
  tests never compete against, or get diluted by, real indexed content.

### Schema

`documents` / `document_chunks` / `tags` / `document_tags` - the minimum the
spec asked for, nothing extra. `domain` and `category` are free text, not
enums - the system must stay domain-agnostic without a migration every time
a new kind of knowledge shows up. `documents.metadata` and
`document_chunks.metadata` are JSONB for the same reason.

This database is a **rebuildable search index**, not the source of truth.
Every row must trace back to a `source_path` that still exists on disk
(Obsidian vault, uploaded file). If it's ever wiped, re-running ingestion
over the source files reconstructs it.

`document_chunks.content_tsv` is a generated `tsvector` column (English
config) for keyword search. Vector similarity uses an HNSW index
(`vector_cosine_ops`) rather than ivfflat - no need to pre-tune a `lists`
parameter to corpus size, and this corpus will stay small for a long time.

### Retrieval - a real bug found and fixed during testing

The first hybrid retrieval implementation blended vector cosine similarity
(0-1 scale) with raw `ts_rank` (typically 0.01-0.1 for short documents)
using fixed weights (0.65 / 0.35). This looked reasonable but was wrong:
`ts_rank`'s contribution was consistently ~2 orders of magnitude too small
to move the combined score, silently defeating the entire point of hybrid
search - keyword matches essentially never mattered.

A second bug compounded it: `plainto_tsquery('english', question)` combines
every word in the question with **AND**. A natural-language question like
"What do my notes say about my project?" almost never has every one of
those words in a single chunk, so the keyword search matched *nothing* -
confirmed directly in `psql`, not assumed.

Fixed both:

1. Replaced the fixed-weight blend with **Reciprocal Rank Fusion** (RRF,
   `1/(60+rank)` per list, summed) - combines by rank position, not raw
   magnitude, so the scale mismatch can't recur.
2. Replaced the AND query with an **OR** query, built by exploding the
   question into lexemes and joining with `|` -
   `to_tsquery('english', array_to_string(tsvector_to_array(to_tsvector(...)), ' | '))`
   - a chunk sharing *any* content word with the question is now a
   candidate, not only a chunk containing every word in it.

With RRF, a pure vector-only match sits in a tight ~0.015-0.0164 band
regardless of true relevance (vector search always returns *something* as
"closest" - confirmed with an off-topic "What is Kubernetes?" query against
Linux/AWS/project notes, whose best "match" landed at 0.016 and, before the
fix, got woven into a confused answer by the small model). A match
corroborated by the keyword list too reaches ~0.03+. `RETRIEVAL_SCORE_THRESHOLD
= 0.02` sits in that gap - see the comment in `backend/rag/generation.py`
for the full reasoning and its known limits.

### What's proven working (12/12 tests pass, plus live CLI verification)

1. Index a Markdown document -> stored in PostgreSQL with embeddings in pgvector.
2. Semantic search finds a paraphrased query with no exact word overlap.
3. Keyword search finds an exact technical term (`grub-install`).
4. A general question with no matching personal notes still gets a clean
   general-knowledge answer (`used_personal_knowledge: False`).
5. A personal question retrieves the right document with structured source
   attribution (not a string - a typed `sources` list).
6. A combined question answers from personal notes and extends into general
   knowledge, both clearly attributed.
7. Retrieval correctly distinguishes three unrelated domains (Linux, AWS,
   a project note) in one corpus.
8. Re-indexing an unchanged document is a no-op (hash match, zero re-embeds).
9. Modifying a document replaces its chunks without duplicating rows.

### Known limitations, stated honestly rather than hidden

- The 1.5B chat model occasionally hallucinates on general knowledge
  (e.g. invented a nonexistent bootloader name, "GRISLY", when asked about
  Linux boot concepts). This is a small-model quality ceiling, not a
  retrieval bug - a real tradeoff of running local CPU inference on this
  hardware, not a bug to chase further right now.
- `RETRIEVAL_SCORE_THRESHOLD = 0.02` is a heuristic confirmed against this
  corpus, not a guarantee. A genuinely relevant chunk with zero keyword
  overlap and only middling vector similarity can still fall below it. The
  real remedy is reranking, deferred by design to a later phase.
- The query router (`backend/rag/router.py`) is a fixed keyword-marker
  heuristic. It's known to be approximate; a model-assisted router is a
  reasonable future upgrade if it proves too blunt in practice.

## Phase 3 - Obsidian vault indexing

The hash-based incremental mechanism from Phase 2 already covered
create/update for a vault (`ObsidianSource` + `IngestionPipeline`) - what
Phase 3 actually added was **deletion detection**, which nothing did before:
if a note is removed from the vault, nothing previously noticed, so its
chunks would sit in the index forever, contradicting "the database must be
rebuildable from the source files."

- `IngestionPipeline.sync_vault()`: discovers the vault's current files,
  indexes each (create/update/unchanged as before), then diffs the
  currently-indexed `source_type='obsidian'` paths under that vault's root
  against what was just discovered - anything missing gets deleted
  (`DocumentRepository.list_source_paths` / `delete_by_source_path`, cascading
  to chunks via the FK).
- Scoped by path prefix (`starts_with`, not `LIKE`, to sidestep wildcard
  escaping) so a vault sync can never delete documents indexed from
  elsewhere - e.g. a one-off file upload sitting outside the vault root is
  untouched, verified explicitly in `tests/integration/test_vault_sync.py`.
- `OBSIDIAN_IGNORE_PATTERNS` (comma-separated) is additive to the built-in
  defaults (`.git`, `.venv`, `.env`, `.obsidian`, ...), not a replacement -
  config can't accidentally turn off the secret/VCS protection.
- `python -m backend.cli sync-vault [path]` (defaults to
  `OBSIDIAN_VAULT_PATH`); `POST /documents/index` with
  `"source_type": "obsidian"` does the same reconciling sync through the API,
  returning a `deleted` list alongside the usual results.
- Verified live against a synthetic vault (two notes in different folders,
  proving folder-as-category): create -> edit -> delete -> no-op sync all
  behaved correctly, then cleaned out of the real index afterward so it
  doesn't linger as demo data.

Explicitly **not** done yet, per the spec's own phasing: frontmatter parsing,
backlinks, tags-from-frontmatter, and the Obsidian graph. Those are listed as
"later, optional" in the spec, not Phase 3.

## Phase 4 - Web UI

Chose a vanilla HTML/CSS/JS single-page app served directly by FastAPI's
`StaticFiles`, not a React/Vite toolchain - no Node build step, no second
dev-server process, no npm dependency tree, consistent with every other
RAM-conscious call made so far (native backend, no extra Docker containers).
Same-origin, so no CORS config needed either.

- All API routes moved under `/api/*` (`/health`, `/config`, `/chat`,
  `/knowledge/search`, `/documents/index`, `/documents/upload`) so they can
  never collide with a static file name; `app.mount("/", StaticFiles(...))`
  is registered last so it never shadows them - Starlette matches routes in
  registration order.
- New `GET /api/config`: exposes only what the UI needs to render itself
  (model names, vault path, top_k, rag_enabled) - never the database URL or
  credentials.
- New `POST /api/documents/upload`: the actual drag-and-drop path. Browsers
  send bytes, not a server-side path, so this is genuinely new server logic,
  not a rename of the existing path-based `/api/documents/index`. Markdown/
  text only, matching the "no PDF/DOCX yet" phase boundary. Needed
  `python-multipart` added to `requirements.txt` - FastAPI can't parse
  multipart form data without it.
- Frontend (`frontend/index.html` + `style.css` + `app.js`): two tabs - Chat
  (message history, intent badge per answer, structured source list, not a
  string) and Knowledge (search box, an Obsidian "Sync vault" button that
  reads the configured path from `/api/config` and calls the existing sync
  endpoint, and a file-upload form). Light/dark via `prefers-color-scheme`.

Verified via curl against a live server: static files serve with correct
content-types, `/api/chat` returns proper intent + structured sources,
`/api/knowledge/search` ranks correctly, `/api/documents/upload` actually
indexes an uploaded file (proven then cleaned out of the real index), and
vault sync works through the API path, not just the CLI.

**Honest limitation**: this environment has no browser automation tool
available, so the UI's actual rendering and click-through behavior have
*not* been visually verified - only the API contracts it depends on have
been. The user needs to open it in a real browser and confirm it looks and
behaves as intended.

## Post-Phase-4 - latency fix, UI restyle, and "save as note"

Three follow-up requests handled in one pass:

**Latency.** Measured, not guessed: a plain "hi" took ~5.2s. Broke it down -
raw Ollama generation alone was ~1.9-2.8s (the real hardware floor on this
CPU), but the router defaulted every message to "combined" intent, so even
small talk triggered a full embed + hybrid-search round trip for zero
benefit. Added a whole-message (not substring) greeting/chitchat match in
`backend/rag/router.py` that routes straight to GENERAL, skipping retrieval
entirely. Also fixed `OllamaLLMProvider`/`OllamaEmbeddingProvider` opening a
brand-new `httpx.AsyncClient` (new TCP connection) on every single call
instead of reusing one - real, if smaller, overhead even against localhost.
Net result: "hi" dropped to ~2.4-2.7s, close to the generation floor.
Personal/combined answers are still slower than that floor - expected, they
carry retrieved context into the prompt, which is genuinely more for the
model to process and generate on a CPU with no GPU.

**UI restyle.** Indigo/violet gradient accent, distinct colors per intent
badge, message fade-in, animated three-dot typing indicator instead of
static "Thinking…" text, softer shadows, hover lift on buttons. Both
light/dark themes updated. Still no way to visually verify this myself - no
browser tool available in this environment.

**"Save as note" / vault write-back.** New capability: `backend/notes/writer.py`
(`NoteWriter`) writes a real `.md` file into the configured Obsidian vault -
not just the internal search index, an actual file the user's Obsidian app
will see. Design choices:

- Never overwrites an existing note - appends `(2)`, `(3)`, ... on a
  filename collision (checked against the same "don't modify existing notes
  automatically" principle the whole ingestion side already follows; a new
  file is not a modification).
- Auto-links to related *existing* notes via `[[wikilinks]]` using the same
  hybrid search and the same `RETRIEVAL_SCORE_THRESHOLD` the chat/search
  paths use (imported, not re-guessed, so "relevant" means the same thing
  everywhere) - this is what makes Obsidian's graph view show real edges
  instead of an isolated new node for every saved note.
- **Bug caught before shipping**: the first version searched the *entire*
  index for related notes, which includes documents indexed from outside the
  vault (e.g. `sample/*.md`, uploaded via `/api/documents/upload`). A
  `[[wikilink]]` to one of those would render as a broken/dangling reference
  in Obsidian - the opposite of the "clear connections" this was built for.
  Fixed by scoping related-note candidates to paths under the vault root
  before linking.
- Only ever adds new files, one-directional links - Obsidian computes
  backlinks/graph edges from a single `[[link]]` on its own, so there's no
  need to (and no code that would) edit an existing note to add a reverse
  link.
- Indexes the new note immediately after writing, not on the next manual
  vault sync - "saved" means searchable right away.
- New endpoint `POST /api/notes/create`; frontend gets a "💾 Save as note"
  button on every assistant message, and a client-side phrase match (e.g.
  "save this as a note") that resolves "this" to the most recent assistant
  answer using the message history already sitting in the browser - no new
  server-side conversation-memory system was built just for this.

Verified live against the real configured vault (`C:\Second_Brain\Sepal_Vbrain`),
not just tests: created two related notes, confirmed the second correctly
linked to the first via `[[...]]`, confirmed the file's frontmatter/heading
render as expected. Both are clearly prefixed `[TEST - delete me]` and left
in place for visual confirmation in Obsidian's graph view before deletion.
