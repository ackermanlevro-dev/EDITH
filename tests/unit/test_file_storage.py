from backend.storage.file_storage import LocalFileStorage


def test_local_file_storage_writes_bytes_and_returns_the_path(tmp_path):
    storage = LocalFileStorage(tmp_path / "uploads")
    dest = storage.save("note.md", b"# Hello\n")

    assert dest.exists()
    assert dest.read_bytes() == b"# Hello\n"
    assert dest.parent == tmp_path / "uploads"


def test_local_file_storage_creates_the_base_directory_if_missing(tmp_path):
    base = tmp_path / "does" / "not" / "exist" / "yet"
    storage = LocalFileStorage(base)
    storage.save("a.txt", b"content")
    assert base.exists()
