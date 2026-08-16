from __future__ import annotations

from dataclasses import dataclass

from backend.ai.embeddings import EmbeddingProvider
from backend.ai.llm import LLMProvider
from backend.documents.models import ChunkSearchResult
from backend.documents.repository import DocumentRepository
from backend.rag.router import QueryIntent, QueryRouter

# RRF's score shape makes this threshold meaningful in a way a raw blended
# score wasn't: vector search always returns *something* as "closest", so a
# vector-only match sits in a tight ~0.015-0.0164 band (1/(60+rank) for small
# rank) regardless of whether it's actually relevant - confirmed live with an
# off-topic query ("What is Kubernetes?" against Linux/AWS/project notes),
# whose best "match" landed at 0.016. A match corroborated by the keyword
# list too - the real relevance signal - reaches ~0.03+. 0.02 sits in the gap
# between "vector says this is the closest thing we have" (weak, unverified)
# and "two independent signals agree" (real evidence). Still a heuristic, not
# a guarantee - a genuinely relevant chunk with zero keyword overlap can fall
# below it. The remedy for that is reranking (deferred by design - see spec),
# not chasing this number further.
RETRIEVAL_SCORE_THRESHOLD = 0.02

_SYSTEM_PROMPT = (
    "You are a personal knowledge assistant. You have two kinds of information: "
    "your own general knowledge, and PERSONAL KNOWLEDGE CONTEXT drawn from the "
    "user's own notes and documents, when it's provided below. Never claim "
    "something came from the user's documents unless it is present in that "
    "context. When you use it, say so explicitly (e.g. 'According to your "
    "notes...'). When you add anything beyond it, make clear that it's general "
    "knowledge, not something the user wrote."
)


@dataclass
class Source:
    document_id: str
    title: str | None
    source_path: str
    heading_path: str | None
    chunk_id: str
    score: float


@dataclass
class ChatAnswer:
    answer: str
    intent: str
    used_personal_knowledge: bool
    sources: list[Source]


class AnswerGenerator:
    def __init__(
        self,
        llm: LLMProvider,
        embeddings: EmbeddingProvider,
        repository: DocumentRepository,
        router: QueryRouter,
        top_k: int = 5,
    ):
        self._llm = llm
        self._embeddings = embeddings
        self._repository = repository
        self._router = router
        self._top_k = top_k

    async def answer(self, question: str) -> ChatAnswer:
        intent = self._router.classify(question)

        results: list[ChunkSearchResult] = []
        if intent in (QueryIntent.PERSONAL, QueryIntent.COMBINED):
            query_embedding = await self._embeddings.embed(question)
            candidates = await self._repository.hybrid_search(query_embedding, question, self._top_k)
            results = [r for r in candidates if r.score >= RETRIEVAL_SCORE_THRESHOLD]

        prompt = self._build_prompt(question, results)
        response = await self._llm.generate(prompt, system=_SYSTEM_PROMPT)

        sources = [
            Source(
                document_id=str(r.document_id),
                title=r.document_title,
                source_path=r.source_path,
                heading_path=r.heading_path,
                chunk_id=str(r.chunk_id),
                score=round(r.score, 4),
            )
            for r in results
        ]

        return ChatAnswer(
            answer=response.text,
            intent=intent.value,
            used_personal_knowledge=bool(results),
            sources=sources,
        )

    @staticmethod
    def _build_prompt(question: str, results: list[ChunkSearchResult]) -> str:
        if not results:
            # No matching personal knowledge (or none was requested) - answer
            # from general knowledge only. This is the path that makes plain
            # questions like "What is Docker?" work with an empty knowledge base.
            return f"GENERAL KNOWLEDGE ONLY - no matching personal notes were found.\n\nQuestion: {question}"

        context = "\n\n---\n\n".join(
            f"[{r.heading_path or r.document_title or r.source_path}]\n{r.content}" for r in results
        )

        return (
            "PERSONAL KNOWLEDGE CONTEXT (from the user's own notes):\n"
            f"{context}\n\n---\n\n"
            f"Question: {question}\n\n"
            "Answer using the personal knowledge context above where it's relevant, "
            "clearly attributed. You may add general knowledge beyond it, but make "
            "clear that it's general knowledge and not something in the user's notes."
        )
