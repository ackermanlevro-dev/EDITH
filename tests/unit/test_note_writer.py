from backend.notes.writer import sanitize_filename


def test_strips_invalid_windows_filename_characters():
    assert sanitize_filename('What is "Docker"? <A/B>') == "What is Docker AB"


def test_blank_title_falls_back_to_untitled():
    assert sanitize_filename("   ") == "Untitled"
    assert sanitize_filename("///") == "Untitled"


def test_trailing_dots_and_spaces_are_stripped():
    assert sanitize_filename("My Note.  ") == "My Note"
