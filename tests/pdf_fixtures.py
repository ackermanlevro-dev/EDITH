"""Not a test module (no test_ prefix, so pytest won't try to collect it) -
just a shared fixture builder used by both the loader unit tests and the
PDF ingestion integration tests."""


def make_test_pdf(text: str) -> bytes:
    """A minimal single-page PDF containing one text string - built by hand,
    with byte offsets computed as it's assembled (not guessed), so tests
    don't need a PDF-authoring dependency just to produce a fixture."""

    def obj(n: int, body: bytes) -> bytes:
        return f"{n} 0 obj\n".encode() + body + b"\nendobj\n"

    content_stream = f"BT /F1 24 Tf 10 100 Td ({text}) Tj ET".encode()

    objects = [
        obj(1, b"<< /Type /Catalog /Pages 2 0 R >>"),
        obj(2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
        obj(
            3,
            b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> "
            b"/MediaBox [0 0 200 200] /Contents 5 0 R >>",
        ),
        obj(4, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"),
        obj(5, f"<< /Length {len(content_stream)} >>\nstream\n".encode() + content_stream + b"\nendstream"),
    ]

    body = b"%PDF-1.4\n"
    offsets = [0]
    for o in objects:
        offsets.append(len(body))
        body += o

    xref_start = len(body)
    xref = f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets[1:]:
        xref += f"{off:010d} 00000 n \n".encode()

    trailer = (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_start}\n%%EOF"
    ).encode()

    return body + xref + trailer
