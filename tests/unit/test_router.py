from backend.rag.router import QueryIntent, QueryRouter

router = QueryRouter()


def test_greetings_skip_retrieval():
    for q in ["hi", "Hi!", "hello", "thanks", "thanks!", "ok", "bye"]:
        assert router.classify(q) == QueryIntent.GENERAL, q


def test_question_containing_a_greeting_word_is_not_misclassified():
    # "ok" and "thanks" only trigger GENERAL as the *whole* trimmed question,
    # not as a substring - otherwise a real question mentioning them mid-sentence
    # would wrongly skip retrieval.
    assert router.classify("ok so what did I write about GRUB?") != QueryIntent.GENERAL


def test_personal_markers_still_route_to_personal():
    assert router.classify("What did I write about Docker?") == QueryIntent.PERSONAL


def test_current_markers_route_to_web():
    assert router.classify("What's the latest Kubernetes version?") == QueryIntent.WEB


def test_unmarked_question_defaults_to_combined():
    assert router.classify("What is Docker?") == QueryIntent.COMBINED
