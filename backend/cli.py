"""Usage:
    python -m backend.cli index <path> [--domain X] [--category Y]
    python -m backend.cli sync-vault [path]   (defaults to OBSIDIAN_VAULT_PATH)
    python -m backend.cli search "<query>"
    python -m backend.cli chat "<question>"
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from backend.config.settings import get_settings
from backend.container import build_context
from backend.ingestion.loaders import supported_extensions
from backend.ingestion.sources import FileSource, ObsidianSource, parse_ignore_patterns


async def _index(args: argparse.Namespace) -> None:
    ctx = await build_context(get_settings())
    try:
        path = Path(args.path)
        files = [path] if path.is_file() else sorted(
            p for ext in supported_extensions() for p in path.rglob(f"*{ext}")
        )
        source = FileSource(files, domain=args.domain, category=args.category)

        for r in await ctx.pipeline.index_source(source):
            print(f"[{r.status:9}] {r.source_path}  ({r.chunk_count} chunks)")
    finally:
        await ctx.close()


async def _sync_vault(args: argparse.Namespace) -> None:
    ctx = await build_context(get_settings())
    try:
        raw_path = args.path or ctx.settings.obsidian_vault_path
        if not raw_path:
            print("No vault path given and OBSIDIAN_VAULT_PATH is not set in .env.")
            return

        vault_path = Path(raw_path)
        if not vault_path.is_dir():
            print(f"Not a directory: {vault_path}")
            return

        ignore = parse_ignore_patterns(ctx.settings.obsidian_ignore_patterns)
        source = ObsidianSource(vault_path, ignore_patterns=ignore)

        result = await ctx.pipeline.sync_vault(source, vault_path)

        counts = {"created": 0, "updated": 0, "unchanged": 0}
        for r in result.indexed:
            counts[r.status] += 1
            if r.status != "unchanged":
                print(f"[{r.status:9}] {r.source_path}  ({r.chunk_count} chunks)")
        for p in result.deleted:
            print(f"[deleted  ] {p}")

        print(
            f"\n{counts['created']} created, {counts['updated']} updated, "
            f"{counts['unchanged']} unchanged, {len(result.deleted)} deleted."
        )
    finally:
        await ctx.close()


async def _search(args: argparse.Namespace) -> None:
    ctx = await build_context(get_settings())
    try:
        query_embedding = await ctx.embeddings.embed(args.query)
        results = await ctx.repository.hybrid_search(query_embedding, args.query, ctx.settings.top_k)
        if not results:
            print("No results.")
        for r in results:
            snippet = r.content[:160].replace("\n", " ")
            print(f"{r.score:.3f}  {r.source_path}  [{r.heading_path or '-'}]")
            print(f"         {snippet}...")
    finally:
        await ctx.close()


async def _chat(args: argparse.Namespace) -> None:
    ctx = await build_context(get_settings())
    try:
        result = await ctx.generator.answer(args.question)
        print(f"\n[intent: {result.intent} | used personal knowledge: {result.used_personal_knowledge}]\n")
        print(result.answer)
        if result.sources:
            print("\nSources:")
            for s in result.sources:
                print(f"  - {s.title or s.source_path} ({s.heading_path or 'top'})  score={s.score}")
    finally:
        await ctx.close()


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m backend.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    p_index = sub.add_parser("index", help="Index a file or a directory of markdown files")
    p_index.add_argument("path")
    p_index.add_argument("--domain")
    p_index.add_argument("--category")
    p_index.set_defaults(func=_index)

    p_sync = sub.add_parser(
        "sync-vault",
        help="Sync an Obsidian vault - creates/updates changed notes, removes deleted ones",
    )
    p_sync.add_argument("path", nargs="?", help="Vault root; defaults to OBSIDIAN_VAULT_PATH")
    p_sync.set_defaults(func=_sync_vault)

    p_search = sub.add_parser("search", help="Hybrid search over the knowledge index")
    p_search.add_argument("query")
    p_search.set_defaults(func=_search)

    p_chat = sub.add_parser("chat", help="Ask the assistant a question")
    p_chat.add_argument("question")
    p_chat.set_defaults(func=_chat)

    args = parser.parse_args()
    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
