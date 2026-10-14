"""Generate a minimal, valid single-page pitch PDF for the Asset Studio drop-zone.

No third-party dependency: emits raw PDF 1.4 bytes with the pitch text as a
Helvetica content stream. The Asset Studio parse-pitch path reads the text with
pypdf and pre-fills the form from the labelled lines (Title / Genre / Budget /
Synopsis / exclusivity).

Usage:  python make_pitch_pdf.py
Writes: pitch-sample.pdf next to this script.
"""
from __future__ import annotations

import io
from pathlib import Path

# Labelled lines the parser recognizes (labelled fields take priority).
LINES = [
    "CineROI AI - Content Acquisition Pitch",
    "",
    "Title: The Tide Keepers",
    "Genre: sci-fi drama",
    "Budget: $34,000,000 USD",
    "Synopsis: On a drowned coastline, a lighthouse engineer and an exiled climate",
    "scientist race to decode a tidal signal that could save the last floating city.",
    "Talent: Directed by Ava Lindqvist; starring Omar Reyes and Lena Cho.",
    "Territories: US, GB, DE",
    "License: Exclusive SVOD window, 36 months.",
    "Projected Viewing Hours: 180,000,000",
]


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_pdf(lines: list[str]) -> bytes:
    parts = ["BT", "/F1 12 Tf", "16 TL", "72 760 Td"]
    for ln in lines:
        parts.append(f"({_esc(ln)}) Tj")
        parts.append("T*")
    parts.append("ET")
    stream = "\n".join(parts).encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    buf = io.BytesIO()
    buf.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(buf.tell())
        buf.write(f"{i} 0 obj\n".encode() + body + b"\nendobj\n")
    xref_pos = buf.tell()
    size = len(objects) + 1
    buf.write(f"xref\n0 {size}\n".encode())
    buf.write(b"0000000000 65535 f \n")
    for off in offsets:
        buf.write(f"{off:010d} 00000 n \n".encode())
    buf.write(b"trailer\n<< /Size " + str(size).encode() + b" /Root 1 0 R >>\n")
    buf.write(b"startxref\n" + str(xref_pos).encode() + b"\n%%EOF\n")
    return buf.getvalue()


if __name__ == "__main__":
    out = Path(__file__).with_name("pitch-sample.pdf")
    out.write_bytes(build_pdf(LINES))
    print(f"Wrote {out} ({out.stat().st_size} bytes)")