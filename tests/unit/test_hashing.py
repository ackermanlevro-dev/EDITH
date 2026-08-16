from backend.ingestion.sources import hash_content


def test_hash_is_deterministic():
    assert hash_content("hello") == hash_content("hello")


def test_hash_changes_with_content():
    assert hash_content("hello") != hash_content("hello!")


def test_hash_is_sha256_hex():
    digest = hash_content("hello")
    assert len(digest) == 64
    int(digest, 16)  # raises if not valid hex
