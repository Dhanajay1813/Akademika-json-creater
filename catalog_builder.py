"""Build mobile-app catalog content from uploaded PDFs."""

from __future__ import annotations

import io
import json
import re
from pathlib import PurePosixPath
from typing import Dict, List, Optional

import fitz
from PIL import Image

MAX_RENDER_WIDTH = 1600
WEBP_QUALITY = 82


def safe_text(value: str) -> str:
    return (value or '').strip()


def safe_filename(value: str, fallback: str = 'file') -> str:
    name = safe_text(value).replace(' ', '_')
    name = re.sub(r'[^A-Za-z0-9._-]+', '_', name).strip('._')
    return name or fallback


def bytes_size(value: bytes) -> int:
    return len(value or b'')


def human_size(size: int) -> str:
    units = ['B', 'KB', 'MB', 'GB']
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f'{value:.1f} {unit}' if unit != 'B' else f'{int(value)} B'
        value /= 1024
    return f'{size} B'


def catalog_root(product_id: str) -> str:
    return f'src/content/catalogs/{product_id}'


def catalog_content_path(product_id: str) -> str:
    return f'{catalog_root(product_id)}/catalogContent.json'


def catalog_index_path() -> str:
    return 'src/content/catalogIndex.json'


def cover_path(product_id: str) -> str:
    return f'{catalog_root(product_id)}/cover.webp'


def page_path(product_id: str, page_number: int) -> str:
    return f'{catalog_root(product_id)}/pages/page_{page_number:03d}.webp'


def open_pdf(pdf_bytes: bytes):
    return fitz.open(stream=pdf_bytes, filetype='pdf')


def pdf_page_count(pdf_bytes: bytes) -> int:
    with open_pdf(pdf_bytes) as document:
        return document.page_count


def render_pdf_pages(pdf_bytes: bytes, max_width: int = MAX_RENDER_WIDTH, quality: int = WEBP_QUALITY) -> List[Dict]:
    pages = []
    with open_pdf(pdf_bytes) as document:
        for index, page in enumerate(document, start=1):
            rect = page.rect
            zoom = min(max_width / rect.width, 3.0) if rect.width else 1.0
            matrix = fitz.Matrix(zoom, zoom)
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            image = Image.open(io.BytesIO(pixmap.tobytes('png'))).convert('RGB')
            buffer = io.BytesIO()
            image.save(buffer, format='WEBP', quality=quality, method=6)
            pages.append({
                'pageNumber': index,
                'filename': f'pages/page_{index:03d}.webp',
                'bytes': buffer.getvalue(),
                'width': image.width,
                'height': image.height,
            })
    return pages


def convert_cover_image(cover_bytes: Optional[bytes]) -> Optional[bytes]:
    if not cover_bytes:
        return None
    image = Image.open(io.BytesIO(cover_bytes)).convert('RGB')
    if image.width > MAX_RENDER_WIDTH:
        ratio = MAX_RENDER_WIDTH / image.width
        image = image.resize((MAX_RENDER_WIDTH, int(image.height * ratio)))
    buffer = io.BytesIO()
    image.save(buffer, format='WEBP', quality=WEBP_QUALITY, method=6)
    return buffer.getvalue()


def build_catalog_content(metadata: Dict, pages: List[Dict], has_cover: bool) -> Dict:
    product_id = metadata['productId']
    return {
        'schemaVersion': 1,
        'catalogId': product_id,
        'productId': product_id,
        'categoryId': metadata['categoryId'],
        'productName': metadata['productName'],
        'categoryName': metadata['categoryName'],
        'title': metadata['title'],
        'version': metadata.get('version', ''),
        'revisionDate': metadata.get('revisionDate', ''),
        'description': metadata.get('description', ''),
        'coverImage': 'cover.webp' if has_cover else '',
        'pageCount': len(pages),
        'pages': [
            {'pageNumber': page['pageNumber'], 'imageFile': page['filename']}
            for page in pages
        ],
    }


def build_catalog_index_entry(metadata: Dict, page_count: int) -> Dict:
    product_id = metadata['productId']
    return {
        'catalogId': product_id,
        'productId': product_id,
        'categoryId': metadata['categoryId'],
        'title': metadata['title'],
        'contentFile': catalog_content_path(product_id),
        'pageCount': page_count,
    }


def build_catalog_index(existing_index, entry: Dict) -> Dict:
    index = existing_index.copy() if isinstance(existing_index, dict) else {'schemaVersion': 1, 'catalogs': {}}
    index['schemaVersion'] = index.get('schemaVersion', 1)
    catalogs = index.get('catalogs') if isinstance(index.get('catalogs'), dict) else {}
    catalogs[entry['catalogId']] = entry
    index['catalogs'] = dict(sorted(catalogs.items()))
    return index


def build_catalog_files(metadata: Dict, pdf_bytes: bytes, cover_bytes: Optional[bytes] = None, existing_index=None) -> Dict:
    pages = render_pdf_pages(pdf_bytes)
    cover = convert_cover_image(cover_bytes)
    content = build_catalog_content(metadata, pages, bool(cover))
    entry = build_catalog_index_entry(metadata, len(pages))
    index = build_catalog_index(existing_index, entry)
    product_id = metadata['productId']
    files = {
        catalog_content_path(product_id): json.dumps(content, indent=2, ensure_ascii=False).encode('utf-8'),
        catalog_index_path(): json.dumps(index, indent=2, ensure_ascii=False).encode('utf-8'),
    }
    for page in pages:
        files[page_path(product_id, page['pageNumber'])] = page['bytes']
    if cover:
        files[cover_path(product_id)] = cover
    return {'files': files, 'content': content, 'index': index, 'pages': pages, 'coverBytes': cover}
