"""API integration tests for the UnicodeGuard web workspace."""
from io import BytesIO

import pytest

fitz = pytest.importorskip("fitz")
pytest.importorskip("fastapi")
pytest.importorskip("multipart")
pytest.importorskip("reportlab")
pytest.importorskip("regex")
pytest.importorskip("httpx")
Document = pytest.importorskip("docx").Document
from fastapi.testclient import TestClient

from app import app, engine

client = TestClient(app)


def test_reference_and_frontend():
    assert client.get('/').status_code == 200
    assert client.get('/script.js').status_code == 200
    assert client.get('/vendor/chart.umd.js').status_code == 200
    ref = client.get('/api/reference').json()
    assert len(ref['hidden']) == 8 and len(ref['visible']) == 14
    assert {v['unicode_code'] for v in ref['hidden']} >= {'U+200B', 'U+202E'}


def test_analysis_uses_codepoint_offsets_and_honest_notice():
    data = client.post('/api/analyze', json={'text': '😀a\u200b Ö\ufe0f\u200b'}).json()
    by_code = {item['unicode_code']: item for item in data['detected_characters']}
    assert by_code['U+200B']['positions'] == [2, 6]
    assert by_code['U+FE0F']['count'] == 1
    assert by_code['U+00D6']['category_group'] == 'visible_unicode'
    assert data['stats']['total_findings'] == 4
    assert 'not proof' in data['notice']


def test_modes_exclusions_emoji_and_mandatory_rlo():
    text = '👩🏽\u200d💻 X\u200b\u202e Ö\u00a0\n☐ task\n- ☑ done'
    safe = client.post('/api/clean', json={'text': text, 'mode': 'safe', 'custom_exclusions':['U+200B', 'U+202E']}).json()
    assert '👩🏽\u200d💻' in safe['cleaned_text']
    assert '\u200b' in safe['cleaned_text'] and '\u202e' not in safe['cleaned_text']
    assert 'Ö ' in safe['cleaned_text']
    strict = client.post('/api/clean', json={'text': text, 'mode':'strict'}).json()
    assert '- [ ] task\n- [x] done' in strict['cleaned_text']
    assert 'O ' in strict['cleaned_text'] and '\u200b' not in strict['cleaned_text']
    aggressive = client.post('/api/clean', json={'text': 'café 漢字', 'mode':'aggressive'}).json()
    assert aggressive['cleaned_text'] == 'cafe '
    assert aggressive['summary']['removed'] == 2
    assert client.post('/api/clean', json={'text':'abc', 'mode':'invalid'}).status_code == 422
    assert client.post('/api/clean', json={'text':'abc', 'custom_exclusions':['bad']}).status_code == 400


def test_upload_utf8_including_bom_and_pdf():
    response = client.post('/api/upload-analyze', files={'file': ('hello.md', '\ufeffHello\u200b'.encode(), 'text/markdown')})
    assert response.status_code == 200
    assert response.json()['text'].startswith('\ufeff')
    assert {x['unicode_code'] for x in response.json()['analysis']['detected_characters']} == {'U+FEFF', 'U+200B'}
    pdf = fitz.open()
    pdf.new_page().insert_text((72, 72), 'Hello PDF')
    data = pdf.tobytes()
    pdf.close()
    result = client.post('/api/upload-analyze', files={'file': ('hello.pdf', data, 'application/pdf')})
    assert result.status_code == 200 and 'Hello PDF' in result.json()['text']
    assert result.json()['pages'] == 1
    assert client.post('/api/upload-analyze', files={'file':('bad.pdf', b'not a pdf', 'application/pdf')}).status_code == 400
    assert client.post('/api/upload-analyze', files={'file':('bad.exe', b'bad', 'text/plain')}).status_code == 400
    assert client.post('/api/upload-analyze', files={'file':('bad.txt', b'\xff', 'text/plain')}).status_code == 400


def test_export_pdf_md_docx_and_filename():
    text = 'Hello Café\nSecond line'
    for fmt in ('md', 'txt', 'pdf', 'docx'):
        response = client.post('/api/export-file', json={'text':text, 'format':fmt, 'filename':'../../hello'})
        assert response.status_code == 200, response.text
        assert f'filename="hello.{fmt}"' in response.headers['content-disposition']
        if fmt == 'pdf':
            with fitz.open(stream=response.content, filetype='pdf') as pdf:
                assert 'Café' in ''.join(p.get_text() for p in pdf)
        elif fmt == 'docx':
            assert 'Café' in '\n'.join(p.text for p in Document(BytesIO(response.content)).paragraphs)
        else:
            assert response.content.decode() == text


def test_pdf_unsupported_glyph_is_reported_not_silently_lost():
    # DejaVu Sans does not contain this supplementary-plane ideograph.
    result = client.post('/api/export-file', json={'text':'\U00020000', 'format':'pdf'})
    assert result.status_code == 422
    assert 'does not support' in result.json()['detail']


def test_no_text_or_files_stored_between_requests():
    engine.analyze_text('secret\u200b')
    assert client.post('/api/analyze', json={'text':'plain'}).json()['stats']['total_findings'] == 0
