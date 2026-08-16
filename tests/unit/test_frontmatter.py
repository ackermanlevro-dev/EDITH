from backend.ingestion.frontmatter import extract_wikilinks, normalize_tags, parse_frontmatter


def test_parses_valid_frontmatter_and_strips_it_from_the_body():
    text = "---\ndomain: technology\ntags: [linux, boot]\n---\n\n# GRUB\n\nBody text.\n"
    fm, body = parse_frontmatter(text)
    assert fm == {"domain": "technology", "tags": ["linux", "boot"]}
    assert body == "\n# GRUB\n\nBody text.\n"
    assert "---" not in body


def test_note_with_no_frontmatter_is_returned_unchanged():
    text = "# Just a note\n\nNo frontmatter here.\n"
    fm, body = parse_frontmatter(text)
    assert fm == {}
    assert body == text


def test_malformed_yaml_does_not_raise_and_falls_back_to_original_text():
    text = "---\nthis: [is: not: valid: yaml\n---\n\n# Note\n"
    fm, body = parse_frontmatter(text)
    assert fm == {}
    assert body == text


def test_frontmatter_that_is_not_a_mapping_is_ignored():
    text = "---\n- just\n- a\n- list\n---\n\n# Note\n"
    fm, body = parse_frontmatter(text)
    assert fm == {}
    assert body == text


def test_extract_wikilinks_handles_plain_alias_and_heading_forms():
    body = "See [[GRUB]] and [[Linux Boot Process|boot process]] and [[UEFI#Secure Boot]]."
    assert extract_wikilinks(body) == ["GRUB", "Linux Boot Process", "UEFI"]


def test_extract_wikilinks_deduplicates_while_preserving_order():
    body = "[[Docker]] then [[Kubernetes]] then [[Docker]] again."
    assert extract_wikilinks(body) == ["Docker", "Kubernetes"]


def test_extract_wikilinks_returns_empty_for_no_links():
    assert extract_wikilinks("Just plain text, no links.") == []


def test_normalize_tags_accepts_yaml_list():
    assert normalize_tags(["linux", "aws", ""]) == ["linux", "aws"]


def test_normalize_tags_accepts_comma_separated_string():
    assert normalize_tags("linux, aws,  docker ") == ["linux", "aws", "docker"]


def test_normalize_tags_handles_none_and_other_types():
    assert normalize_tags(None) == []
    assert normalize_tags(42) == []
