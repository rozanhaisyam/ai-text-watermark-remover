"""End-to-end export exercises the offline and model-unavailable paths."""
from pathlib import Path

import pytest

from reweave.cli import main
from reweave.core.types import Document
from reweave.export import export_cleaned
from reweave.fix import run_fix
from reweave.scrub.unicode_scrubber import UnicodeScrubber


DIRTY = ("---\ntitle: Example\ngenerator: ChatGPT\n---\n\n"
         "# Example\n\nA\u200b sentence—with **emphasis** and 40%.\n\n"
         "- one\n  - nested\n\n```\n    indented code\n```\n")


def test_scrub_preserves_meaningful_whitespace():
    text = "  - nested\n    code  \n\tindent\n"
    assert UnicodeScrubber().scrub(Document(text=text)).text == text


def test_export_all_formats_and_preserve_source(tmp_path, capsys):
    pytest.importorskip("markdown_it")
    docx = pytest.importorskip("docx")
    pypdf = pytest.importorskip("pypdf")
    source = tmp_path / "source.md"
    source.write_text(DIRTY, encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()
    assert main(["export", str(source), "-o", str(output)]) == 0
    assert source.read_text(encoding="utf-8") == DIRTY
    md = (output / "source.md").read_text(encoding="utf-8")
    assert "generator:" not in md and "\u200b" not in md and "—" not in md
    assert "  - nested" in md and "    indented code" in md
    paragraphs = "\n".join(p.text for p in docx.Document(output / "source.docx").paragraphs)
    assert "Example" in paragraphs and "nested" in paragraphs and "40%" in paragraphs
    pdf_text = "".join(page.extract_text() for page in pypdf.PdfReader(output / "source.pdf").pages)
    assert "Example" in pdf_text and "nested" in pdf_text and "40%" in pdf_text
    assert "does not remove or verify statistical watermarks" in capsys.readouterr().out


def test_md_only_no_overwrite_and_force(tmp_path):
    source = tmp_path / "input.txt"
    source.write_text(DIRTY, encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    target = out / "input.md"
    target.write_text("old", encoding="utf-8")
    with pytest.raises(FileExistsError):
        export_cleaned(source, out, {"md"})
    assert target.read_text() == "old"
    export_cleaned(source, out, {"md"}, force=True)
    assert "generator:" not in target.read_text()
    assert source.read_text() == DIRTY


def test_input_never_overwritten_even_with_force(tmp_path):
    source = tmp_path / "input.md"
    source.write_text(DIRTY)
    with pytest.raises(ValueError, match="overwrite the input"):
        export_cleaned(source, tmp_path, {"md"}, force=True)
    assert source.read_text() == DIRTY


def test_regeneration_unavailable_does_not_export(tmp_path, monkeypatch):
    from reweave import _ollama
    monkeypatch.setattr(_ollama, "is_up", lambda host: False)
    source = tmp_path / "input.txt"
    source.write_text(DIRTY)
    with pytest.raises(ValueError, match="not reachable"):
        export_cleaned(source, tmp_path, {"md"}, regenerate=True)
    assert not (tmp_path / "input.md").exists()
    assert source.read_text() == DIRTY


def test_binary_fix_rejected_without_modification(tmp_path):
    source = tmp_path / "input.docx"
    source.write_bytes(b"PK\x03\x04test")
    with pytest.raises(ValueError, match="text files"):
        run_fix(str(source))
    assert source.read_bytes() == b"PK\x03\x04test"


def test_render_error_leaves_existing_outputs_intact(tmp_path):
    pytest.importorskip("markdown_it")
    pytest.importorskip("reportlab")
    source = tmp_path / "input.txt"
    source.write_text("hello")
    target = tmp_path / "input.md"
    target.write_text("old")
    with pytest.raises(ValueError, match="font"):
        export_cleaned(source, tmp_path, {"md", "pdf"}, force=True, pdf_font="missing.ttf")
    assert target.read_text() == "old"
    assert not (tmp_path / "input.pdf").exists()


def test_cli_reports_regeneration_unavailable(tmp_path, monkeypatch, capsys):
    from reweave import _ollama
    monkeypatch.setattr(_ollama, "is_up", lambda host: False)
    source = tmp_path / "input.txt"
    source.write_text("A short sentence.")
    assert main(["fix", str(source), "--regenerate"]) == 1
    assert "not reachable" in capsys.readouterr().out


def test_links_and_unicode_are_rendered(tmp_path):
    pytest.importorskip("markdown_it")
    docx = pytest.importorskip("docx")
    pypdf = pytest.importorskip("pypdf")
    source = tmp_path / "input.txt"
    source.write_text("# Café\n\nSee [documentation](https://example.com).\n", encoding="utf-8")
    export_cleaned(source, tmp_path, {"pdf", "docx"})
    docx_text = "\n".join(p.text for p in docx.Document(tmp_path / "input.docx").paragraphs)
    pdf_text = "".join(p.extract_text() for p in pypdf.PdfReader(tmp_path / "input.pdf").pages)
    for text in (docx_text, pdf_text):
        assert "Café" in text and "https://example.com" in text


def test_invalid_parameters_are_rejected_before_changes(tmp_path):
    source = tmp_path / "input.txt"
    source.write_text(DIRTY)
    for kwargs in ({"max_passes": 0}, {"threshold": 1.5}):
        with pytest.raises(ValueError):
            export_cleaned(source, tmp_path, {"md"}, **kwargs)
    assert source.read_text() == DIRTY
    assert not (tmp_path / "input.md").exists()
