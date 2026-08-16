from __future__ import annotations

from enum import Enum


class QueryIntent(str, Enum):
    GENERAL = "general"
    PERSONAL = "personal"
    COMBINED = "combined"
    WEB = "web"  # not implemented - Phase 6


_PERSONAL_MARKERS = (
    "my notes", "my note", "i wrote", "i learned", "did i", "what did i",
    "my document", "my documents", "my vault", "my project",
    "have i", "i have written", "according to my", "in my",
)

_COMBINED_MARKERS = (
    "based on what i", "using what i", "compare my", "what should i learn next",
    "relate to", "how does this relate", "connect",
)

_CURRENT_MARKERS = (
    "latest", "current version", "newest", "up to date", "up-to-date",
    "recent version", "right now", "as of today",
)

# Retrieval (embed + hybrid search) costs real time on this hardware - live
# measurement on a warm model showed it adding ~2s on top of generation for
# a plain "hi", for zero benefit (nothing relevant exists for small talk).
# Matched as a whole trimmed question, not a substring, so it can't misfire
# on a real question that happens to contain "ok" or "thanks" mid-sentence.
_GREETINGS = {
    "hi", "hello", "hey", "hiya", "yo", "sup", "hi there", "hello there",
    "thanks", "thank you", "thx", "ta",
    "ok", "okay", "cool", "nice", "great", "got it",
    "bye", "goodbye", "see you", "later", "cya",
    "how are you", "how's it going", "hows it going", "what's up", "whats up",
}


class QueryRouter:
    """Deterministic heuristic for v1 - swap for a model-assisted router later
    without touching retrieval or generation. Defaults to COMBINED rather than
    GENERAL so unmarked questions still get a chance at personal context; if
    nothing relevant is retrieved, generation falls back to general knowledge
    on its own, so this default never blocks a plain question from working."""

    def classify(self, question: str) -> QueryIntent:
        q = question.lower().strip().rstrip("!.?")

        if q in _GREETINGS:
            return QueryIntent.GENERAL
        if any(m in q for m in _CURRENT_MARKERS):
            return QueryIntent.WEB
        if any(m in q for m in _COMBINED_MARKERS):
            return QueryIntent.COMBINED
        if any(m in q for m in _PERSONAL_MARKERS):
            return QueryIntent.PERSONAL
        return QueryIntent.COMBINED
