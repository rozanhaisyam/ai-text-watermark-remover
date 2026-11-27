"""Non-destructive cleanup and export of UTF-8 text and Markdown documents."""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .fix import FixResult, run_fix


@dataclass
class ExportResult:
    files: list[Path]
    fix: FixResult


def _require_export_libraries(formats: set[str]) -> None:
    try:
        if formats & {"pdf", "docx"}:
            import markdown_it  # noqa: F401
        if "pdf" in formats:
            import reportlab  # noqa: F401
        if "docx" in formats:
            import docx  # noqa: F401
    except ImportError as exc:
        raise ValueError("PDF/DOCX export requires the export extra: "
                         "pip install 'ai-text-watermark-remover[export]'") from exc


def _blocks(text: str):
    """Convert CommonMark tokens into simple blocks and inline runs."""
    from markdown_it import MarkdownIt

    tokens = MarkdownIt().parse(text)
    blocks = []
    list_stack: list[tuple[str, int]] = []
    prefix = ""
    heading = 0
    for token in tokens:
        if token.type in ("bullet_list_open", "ordered_list_open"):
            start = int(token.attrGet("start") or 1)
            list_stack.append(("bullet" if token.type.startswith("bullet") else "ordered", start))
        elif token.type in ("bullet_list_close", "ordered_list_close"):
            list_stack.pop()
        elif token.type == "list_item_open":
            kind, number = list_stack[-1]
            prefix = "  " * (len(list_stack) - 1) + ("• " if kind == "bullet" else f"{number}. ")
            if kind == "ordered":
                list_stack[-1] = (kind, number + 1)
        elif token.type == "heading_open":
            heading = int(token.tag[1:])
        elif token.type == "heading_close":
            heading = 0
        elif token.type == "inline":
            runs = []
            bold = italic = False
            links = []
            for child in token.children or []:
                if child.type == "strong_open":
                    bold = True
                elif child.type == "strong_close":
                    bold = False
                elif child.type == "em_open":
                    italic = True
                elif child.type == "em_close":
                    italic = False
                elif child.type in ("text", "code_inline", "html_inline"):
                    runs.append((child.content, bold, italic))
                elif child.type in ("softbreak", "hardbreak"):
                    runs.append(("\n" if child.type == "hardbreak" else " ", bold, italic))
                elif child.type == "link_open":
                    links.append(child.attrGet("href") or "")
                elif child.type == "link_close":
                    url = links.pop()
                    if url:
                        runs.append((f" ({url})", False, False))
                elif child.type == "image":
                    url = child.attrGet("src") or ""
                    runs.append((f"{child.content} ({url})" if url else child.content, bold, italic))
            blocks.append((heading, prefix, runs))
            prefix = ""
        elif token.type in ("fence", "code_block", "html_block"):
            blocks.append((0, "", [(token.content, False, False)]))
        elif token.type == "hr":
            blocks.append((0, "", [("---", False, False)]))
    return blocks


def _write_docx(text: str, target: Path) -> None:
    from docx import Document

    doc = Document()
    doc.core_properties.author = ""
    doc.core_properties.last_modified_by = ""
    doc.core_properties.title = ""
    for heading, prefix, runs in _blocks(text):
        paragraph = doc.add_heading(level=heading) if heading else doc.add_paragraph()
        if prefix:
            paragraph.add_run(prefix)
        for value, bold, italic in runs:
            run = paragraph.add_run(value)
            run.bold, run.italic = bold, italic
    doc.save(str(target))


def _pdf_font(path: str | None, text: str) -> str:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    candidates = ([path] if path else [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/Library/Fonts/Arial Unicode.ttf", "/Library/Fonts/Arial.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ])
    font_path = next((p for p in candidates if p and Path(p).is_file()), None)
    if not font_path:
        raise ValueError("No PDF TrueType font found. Provide --pdf-font with a Unicode TTF font.")
    try:
        font = TTFont("ReweaveExport", font_path)
    except Exception as exc:
        raise ValueError(f"Cannot load PDF TrueType font {font_path}: {exc}") from exc
    # ReportLab silently substitutes missing glyphs; refuse instead of losing text.
    missing = sorted({ch for ch in text if not ch.isspace() and ord(ch) not in font.face.charWidths})
    if missing:
        example = " ".join(f"U+{ord(ch):04X}" for ch in missing[:8])
        raise ValueError(f"PDF font lacks characters {example}; choose another --pdf-font")
    pdfmetrics.registerFont(font)
    return "ReweaveExport"


def _write_pdf(text: str, target: Path, font_path: str | None) -> None:
    from html import escape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

    blocks = _blocks(text)
    printable = "".join(prefix + "".join(r[0] for r in runs) for _, prefix, runs in blocks)
    font = _pdf_font(font_path, printable)
    doc = SimpleDocTemplate(str(target), title="", author="", leftMargin=54, rightMargin=54)
    story = []
    for heading, prefix, runs in blocks:
        size = 18 - min(heading, 5) * 1.5 if heading else 10.5
        style = ParagraphStyle("block", fontName=font, fontSize=size, leading=size * 1.45,
                               alignment=TA_LEFT, spaceAfter=8)
        # Use a single embedded font; Markdown emphasis is not preserved in PDF.
        content = prefix + "".join(value for value, _, _ in runs)
        content = escape(content).replace("\n", "<br/>")
        story.append(Paragraph(content or " ", style))
    if not story:
        story.append(Spacer(1, 1))
    doc.build(story)


def export_cleaned(source: str | Path, output_dir: str | Path, formats: set[str], *,
                   force: bool = False, regenerate: bool = False, model: str = "gemma3:4b",
                   allow_unlisted: bool = False, threshold: float = 0.70,
                   max_passes: int = 3, pdf_font: str | None = None) -> ExportResult:
    source, output_dir = Path(source), Path(output_dir)
    if source.suffix.lower() not in {".md", ".markdown", ".txt"}:
        raise ValueError("Input must be a UTF-8 .txt, .md or .markdown file; PDF/DOCX input is not supported")
    if not formats or not formats <= {"md", "pdf", "docx"}:
        raise ValueError("Choose at least one of md, pdf, docx")
    if max_passes < 1 or not 0 <= threshold <= 1:
        raise ValueError("max-passes must be positive and threshold must be between 0 and 1")
    _require_export_libraries(formats)
    # Decode before creating any output. Never copy the source's filesystem metadata.
    text = source.read_text(encoding="utf-8")
    if not output_dir.is_dir():
        raise ValueError(f"Output directory does not exist: {output_dir}")
    targets = [output_dir / f"{source.stem}.{fmt}" for fmt in sorted(formats)]
    for target in targets:
        if target.resolve() == source.resolve():
            raise ValueError(f"Output would overwrite the input: {target}; choose another output directory")
        if target.exists() and not force:
            raise FileExistsError(f"Output already exists: {target}; use --force to replace it")
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise ValueError(f"Output is not a regular file: {target}")
    # Generate everything in a private staging directory, so rendering errors do
    # not leave incomplete exports. The source is never modified.
    with tempfile.TemporaryDirectory(prefix=".reweave-", dir=output_dir) as tmp:
        temp = Path(tmp)
        working = temp / ("input" + source.suffix.lower())
        working.write_text(text, encoding="utf-8")
        result = run_fix(str(working), regenerate=regenerate, model=model,
                         allow_unlisted=allow_unlisted, threshold=threshold, max_passes=max_passes)
        if not result.converged or (regenerate and (not result.regenerate or result.final_score < threshold)):
            raise ValueError("Cleanup did not complete: " + "; ".join(result.residual or ["pass budget exhausted"]))
        cleaned = working.read_text(encoding="utf-8")
        for target in targets:
            staged = temp / target.name
            if target.suffix == ".md":
                staged.write_text(cleaned, encoding="utf-8")
            elif target.suffix == ".docx":
                _write_docx(cleaned, staged)
            else:
                _write_pdf(cleaned, staged, pdf_font)
        for target in targets:
            staged = temp / target.name
            if force:
                os.replace(staged, target)
            else:
                # Exclusive creation avoids silently overwriting a concurrent file.
                with target.open("xb") as out, staged.open("rb") as src:
                    import shutil
                    shutil.copyfileobj(src, out)
    return ExportResult(targets, result)
