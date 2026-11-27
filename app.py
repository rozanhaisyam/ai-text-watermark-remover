"""Unwatermark: a local document-inspection API and static web application.

Unicode findings are character observations, not proof of AI authorship or a
watermark.  Nothing is stored by the application between requests.
"""
from __future__ import annotations

import io
import os
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Literal

import fitz
import regex
from docx import Document
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, Field
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer
from html import escape

ROOT = Path(__file__).resolve().parent
MAX_TEXT = 500_000
MAX_UPLOAD = 10 * 1024 * 1024
MAX_PAGES = 100

# These are characters to review, not a database of proven AI watermarks.
HIDDEN = {
    "\u200b": ("ZWSP", "Invisible word separator; may also be legitimate typography."),
    "\u200c": ("ZWNJ", "Can be important for shaping in Persian and other languages."),
    "\u200d": ("ZWJ", "Joins emoji and can be important in several scripts."),
    "\u2060": ("WJ", "Prevents a line break; can be intentional."),
    "\ufeff": ("BOM", "May be a byte-order mark or an invisible separator."),
    "\u00a0": ("NBSP", "A non-breaking space often used in normal typography."),
    "\u2009": ("THIN", "A narrow typographic space."),
    "\u202e": ("RLO", "Overrides text direction and can obscure displayed text."),
}
VISIBLE = {
    "–": "-", "•": "-", "—": "-", "ı": "i", "☐": "[ ]", "š": "s", "Ö": "O",
    "☑": "[x]", "Ç": "C", "ğ": "g", "ć": "c", "Ü": "U", "Ş": "S", "č": "c",
}
HOMOGLYPHS = {
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y",
    "і": "i", "ј": "j", "Α": "A", "Β": "B", "Ε": "E", "Ο": "O", "А": "A",
}
MAPPINGS = {**VISIBLE, **HOMOGLYPHS}
# Keep ZWJ only when it joins extended pictographic sequences. This is a
# conservative heuristic, not a full grapheme/emoji or linguistic parser.
EMOJI_JOIN = regex.compile(r"\p{Extended_Pictographic}(?:\p{Grapheme_Extend}|\p{Emoji_Modifier}|\ufe0f)*\u200d(?=\p{Extended_Pictographic})")


def code(ch: str) -> str:
    return f"U+{ord(ch):04X}"


def is_variation(ch: str) -> bool:
    n = ord(ch)
    return 0xFE00 <= n <= 0xFE0F or 0xE0100 <= n <= 0xE01EF


def kind(ch: str) -> str | None:
    cat = unicodedata.category(ch)
    if cat == "Cf":
        return "format"
    if cat == "Zs" and ch != " ":
        return "separator"
    if is_variation(ch) or ch in {"\u034f", "\u2800"}:
        return "other_invisible"
    if ch in MAPPINGS:
        return "visible"
    return None


def clean_action(ch: str) -> str:
    group = kind(ch)
    if ch == "\u200d":
        return "Safe: remove outside emoji sequences (heuristic)"
    if ch == "\u202e":
        return "Always remove (direction override)"
    if group == "format":
        return "Safe: remove; may affect text shaping"
    if group == "separator":
        return "Safe: normalize to space"
    if group == "other_invisible":
        return "Safe/strict: keep; aggressive may remove"
    return f"Strict: transliterate to {MAPPINGS[ch]}"


class WatermarkEngine:
    def analyze_text(self, text: str) -> dict:
        positions: dict[str, list[int]] = defaultdict(list)
        for index, ch in enumerate(text):
            if kind(ch):
                positions[ch].append(index)
        findings = []
        counts = Counter()
        weighted = 0
        for ch, pos in positions.items():
            group = kind(ch)
            counts[group] += len(pos)
            weighted += len(pos) * (4 if ch == "\u202e" else 2 if group == "format" else 1)
            cat = unicodedata.category(ch)
            name = unicodedata.name(ch, "UNKNOWN")
            findings.append({
                "char": ch if group == "visible" else f"[{HIDDEN.get(ch, (code(ch),))[0]}]",
                "original_char": ch, "unicode_code": code(ch), "name": name,
                "name_type": f"{name} · {cat}", "unicode_category": cat,
                "count": len(pos), "positions": pos, "clean_action": clean_action(ch),
                "category_group": "visible_unicode" if group == "visible" else "invisible_watermark",
                "kind": group,
            })
        findings.sort(key=lambda x: (-x["count"], x["unicode_code"]))
        invisible = sum(counts[x] for x in ("format", "separator", "other_invisible"))
        total = invisible + counts["visible"]
        # This is a UI prioritization heuristic, not a calibrated probability.
        attention = min(100, round(weighted / max(len(text), 1) * 1000))
        return {
            "stats": {"total_chars": len(text), "total_words": len(text.split()),
                      "total_findings": total, "total_watermarks_detected": total,
                      "invisible_count": invisible, "visible_count": counts["visible"],
                      "format_count": counts["format"], "separator_count": counts["separator"],
                      "other_invisible_count": counts["other_invisible"],
                      "watermark_density": round(total / max(len(text), 1) * 1000, 2),
                      "attention_index": attention, "ai_watermark_risk_score": attention},
            "detected_characters": findings,
            "notice": "Findings and attention index are heuristics, not proof of AI authorship or watermarking. Positions are zero-based Unicode code-point offsets.",
        }

    def clean_text(self, text: str, mode: str, custom_exclusions: list[str] | None = None) -> dict:
        exclusions = {x.upper() for x in (custom_exclusions or [])}
        emoji_joiners = {m.end() - 1 for m in EMOJI_JOIN.finditer(text)}
        output = []
        changes: dict[str, dict] = {}
        line_prefix = ""
        for i, ch in enumerate(text):
            replacement = ch
            excluded = code(ch) in exclusions and ch != "\u202e"
            if not excluded:
                k = kind(ch)
                if ch == "\u202e":
                    replacement = ""
                elif k == "format" and not (mode != "aggressive" and ch == "\u200d" and i in emoji_joiners):
                    replacement = ""
                elif k == "separator":
                    replacement = " "
                elif mode in ("strict", "aggressive") and ch in MAPPINGS:
                    replacement = MAPPINGS[ch]
                    if ch in {"☐", "☑"} and not line_prefix.strip():
                        replacement = "- " + replacement
                if mode == "aggressive" and replacement and ch != "\u200d":
                    replacement = unicodedata.normalize("NFKD", replacement).encode("ascii", "ignore").decode("ascii")
            output.append(replacement)
            if replacement != ch:
                key = code(ch)
                item = changes.setdefault(key, {"unicode_code": key, "name": unicodedata.name(ch, "UNKNOWN"),
                                                "count": 0, "removed": 0, "transliterated": 0})
                item["count"] += 1
                item["removed" if replacement == "" else "transliterated"] += 1
            line_prefix = "" if ch == "\n" else (line_prefix + ch)[-1000:]
        cleaned = "".join(output)
        return {"cleaned_text": cleaned, "mode": mode, "changes": list(changes.values()),
                "summary": {"changed": sum(c["count"] for c in changes.values()),
                            "removed": sum(c["removed"] for c in changes.values()),
                            "transliterated": sum(c["transliterated"] for c in changes.values())},
                "before": self.analyze_text(text), "after": self.analyze_text(cleaned),
                "notice": "Review changes carefully: cleanup can change meaning, scripts, emoji, code, or formatting. It cannot verify statistical watermarks."}


engine = WatermarkEngine()
app = FastAPI(title="Unwatermark API")
app.mount("/assets", StaticFiles(directory=ROOT / "static"), name="assets")
templates = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=select_autoescape(["html", "xml"]))
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])


class TextRequest(BaseModel):
    text: str = Field(max_length=MAX_TEXT)


class CleanRequest(TextRequest):
    mode: Literal["safe", "strict", "aggressive"] = "safe"
    custom_exclusions: list[str] = Field(default_factory=list, max_length=256)


class ExportRequest(TextRequest):
    format: Literal["pdf", "md", "txt", "docx"]
    filename: str = Field(default="unwatermark-clean", max_length=100)


def validate_text(text: str) -> None:
    if any(0xD800 <= ord(c) <= 0xDFFF for c in text):
        raise HTTPException(400, "Invalid Unicode surrogate in text")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/reference")
def reference():
    hidden = [{"unicode_code": code(ch), "name": unicodedata.name(ch), "type": unicodedata.category(ch),
               "why_it_matters": detail, "clean_action": clean_action(ch)} for ch, (_, detail) in HIDDEN.items()]
    visible = [{"char": ch, "unicode_code": code(ch), "name": unicodedata.name(ch),
                "type": unicodedata.category(ch), "replacement": replacement} for ch, replacement in VISIBLE.items()]
    return {"hidden": hidden, "visible": visible}


@app.post("/api/analyze")
def analyze(body: TextRequest):
    validate_text(body.text)
    return engine.analyze_text(body.text)


@app.post("/api/clean")
def clean(body: CleanRequest):
    validate_text(body.text)
    if any(not re.fullmatch(r"U\+[0-9A-Fa-f]{4,6}", item, re.I) for item in body.custom_exclusions):
        raise HTTPException(400, "Exclusions must be Unicode codes such as U+200D")
    return engine.clean_text(body.text, body.mode, body.custom_exclusions)


@app.post("/api/upload-analyze")
async def upload_analyze(file: UploadFile = File(...)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in {".md", ".txt", ".pdf"}:
        raise HTTPException(400, "Only .pdf, .md and .txt files are supported")
    content = await file.read(MAX_UPLOAD + 1)
    if len(content) > MAX_UPLOAD:
        raise HTTPException(413, "File exceeds 10 MB")
    pages = None
    try:
        if ext == ".pdf":
            with fitz.open(stream=content, filetype="pdf") as pdf:
                if pdf.needs_pass:
                    raise HTTPException(400, "Password-protected PDFs are not supported")
                if len(pdf) > MAX_PAGES:
                    raise HTTPException(413, "PDF exceeds 100 pages")
                pages = len(pdf)
                parts = []
                total = 0
                for page in pdf:
                    page_text = page.get_text(sort=True)
                    total += len(page_text) + 3
                    if total > MAX_TEXT:
                        raise HTTPException(413, "Extracted text exceeds 500,000 characters")
                    parts.append(page_text)
                text = "\n\f\n".join(parts)
        else:
            text = content.decode("utf-8")
    except HTTPException:
        raise
    except (ValueError, UnicodeDecodeError, RuntimeError) as exc:
        raise HTTPException(400, "Could not read this file. Use a valid PDF or UTF-8 text.") from exc
    if len(text) > MAX_TEXT:
        raise HTTPException(413, "Extracted text exceeds 500,000 characters")
    return {"filename": Path(file.filename or "document").name, "text": text, "pages": pages,
            "analysis": engine.analyze_text(text),
            "notice": "PDF extraction is text-only; images, layout and metadata are not preserved. Scanned PDFs require OCR." if ext == ".pdf" else "UTF-8 text loaded."}


def pdf_bytes(text: str) -> bytes:
    from html import escape
    font_candidates = [os.environ.get("UNWATERMARK_PDF_FONT", ""),
                       os.environ.get("UNICODEGUARD_PDF_FONT", ""),
                       "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                       "/Library/Fonts/Arial Unicode.ttf", "/Library/Fonts/Arial.ttf", "C:/Windows/Fonts/arial.ttf"]
    font_path = next((p for p in font_candidates if p and Path(p).is_file()), None)
    if not font_path:
        raise HTTPException(422, "No PDF TTF font found. Set UNWATERMARK_PDF_FONT.")
    font = TTFont("UnwatermarkFont", font_path)
    missing = {c for c in text if not c.isspace() and ord(c) not in font.face.charWidths}
    if missing:
        codes = ", ".join(code(c) for c in sorted(missing)[:8])
        raise HTTPException(422, f"PDF font does not support {codes}. Choose a suitable TTF with UNWATERMARK_PDF_FONT.")
    pdfmetrics.registerFont(font)
    result = io.BytesIO()
    doc = SimpleDocTemplate(result, title="", author="", leftMargin=54, rightMargin=54)
    style = ParagraphStyle("plain", fontName="UnwatermarkFont", fontSize=10, leading=15, spaceAfter=4, splitLongWords=True)
    story = []
    if any(ord(ch) < 32 and ch not in "\n\r\t\f" for ch in text):
        raise HTTPException(422, "PDF cannot represent control characters; clean or remove them first.")
    for page_number, page in enumerate(text.split("\f")):
        if page_number:
            story.append(PageBreak())
        for line in page.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            if line:
                # Explicit spaces and indentation survive ReportLab's XML whitespace handling.
                body = escape(line.expandtabs(4)).replace(" ", "&nbsp;")
                story.append(Paragraph(body, style))
            else:
                story.append(Spacer(1, 12))
    if not story:
        story = [Spacer(1, 1)]
    doc.build(story)
    return result.getvalue()


@app.post("/api/export-file")
def export_file(body: ExportRequest):
    validate_text(body.text)
    name = re.sub(r"[^A-Za-z0-9_-]", "-", Path(body.filename).stem).strip("-_") or "unwatermark-clean"
    ext = body.format
    if ext == "pdf":
        data, media = pdf_bytes(body.text), "application/pdf"
    elif ext == "docx":
        doc = Document()
        doc.core_properties.author = ""
        doc.core_properties.last_modified_by = ""
        for line in body.text.split("\n"):
            doc.add_paragraph(line)
        out = io.BytesIO()
        doc.save(out)
        data, media = out.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        data = body.text.encode("utf-8")
        media = "text/markdown; charset=utf-8" if ext == "md" else "text/plain; charset=utf-8"
    return Response(content=data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}.{ext}"'})


@app.get("/")
def index():
    return HTMLResponse(templates.get_template("index.html").render())


@app.get("/styles.css")
def styles():
    return FileResponse(ROOT / "styles.css", media_type="text/css")


@app.get("/script.js")
def script():
    return FileResponse(ROOT / "script.js", media_type="application/javascript")


@app.get("/vendor/chart.umd.js")
def chart():
    return FileResponse(ROOT / "static/vendor/chart.umd.js", media_type="application/javascript")
