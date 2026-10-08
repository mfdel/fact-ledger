"""Write nimbus-pdf-2025.pdf, the synthetic 4-page deck that ``extract`` tests run on.

Run: uv run python tests/fixtures/decks/make_nimbus_pdf.py
"""

from pathlib import Path

# (x, y, font size, text). Table cells share one x for each column, so pypdf layout mode keeps
# each row on one line under its header.
PAGES = [
    [
        (60, 420, 40, "Nimbus"),
        (60, 370, 24, "Management presentation"),
        (60, 330, 18, "March 2025"),
        (60, 220, 32, "~€8m ARR (Dec 2024)"),
        (60, 60, 12, "Synthetic data, not a real company."),
    ],
    [
        (60, 460, 32, "Key metrics"),
        (60, 360, 22, "ARR: €8.4m (as of 31 Dec 2024)"),
        (60, 310, 22, "MRR: €700k (as of 31 December 2024)"),
    ],
    [
        (60, 460, 32, "Track record"),
        (60, 360, 22, "Revenue 2023: €4.7m"),
        (60, 310, 22, "Pipeline coverage: 3.2x (as of 31 Dec 2024)"),
    ],
    [
        (60, 460, 32, "Appendix: KPI summary (€k)"),
        (60, 380, 18, "KPI"),
        (300, 380, 18, "31 Dec 2024"),
        (60, 340, 18, "ARR"),
        (300, 340, 18, "7,450"),
        (60, 300, 18, "MRR"),
        (300, 300, 18, "700"),
    ],
]


def content(runs: list[tuple[int, int, int, str]]) -> bytes:
    ops = []
    for x, y, size, text in runs:
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        ops.append(f"BT /F1 {size} Tf {x} {y} Td ({escaped}) Tj ET")
    # WinAnsiEncoding is cp1252, so "€" is the one byte 0x80 of the base-14 font.
    return "\n".join(ops).encode("cp1252")


def build() -> bytes:
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(len(PAGES)))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {len(PAGES)} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    for i, runs in enumerate(PAGES):
        stream = content(runs)
        objects += [
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 960 540] "
            b"/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>" % (5 + 2 * i),
            b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
        ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\n" % (len(objects) + 1)
    return bytes(out + b"startxref\n%d\n%%%%EOF\n" % xref)


if __name__ == "__main__":
    Path(__file__).with_name("nimbus-pdf-2025.pdf").write_bytes(build())
