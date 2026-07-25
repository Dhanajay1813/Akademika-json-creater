"""Build mobile-app catalog content from uploaded PDFs."""

from __future__ import annotations

import json
import re
from pathlib import PurePosixPath
from typing import Dict, List, Optional

import fitz
from image_optimizer import image_metadata, optimize_image_bytes, render_pdf_pages, report_json_bytes, summarize_records


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


def render_catalog_pdf_pages(pdf_bytes: bytes) -> List[Dict]:
    pages = []
    for page in render_pdf_pages(pdf_bytes):
        pages.append({
            'pageNumber': page['pageNumber'],
            'filename': f"pages/{page['filename']}",
            'bytes': page['bytes'],
            'width': page['width'],
            'height': page['height'],
            'byteSize': page['byteSize'],
            'sha256': page['sha256'],
            'originalSize': page['originalSize'],
            'optimizedSize': page['optimizedSize'],
            'percentSaved': page['percentSaved'],
            'profile': page['profile'],
            'warning': page.get('warning', ''),
            'textDense': page.get('textDense', False),
            'converted': page.get('converted', True),
        })
    return pages


def convert_cover_image(cover_bytes: Optional[bytes]) -> Optional[Dict]:
    if not cover_bytes:
        return None
    optimized = optimize_image_bytes(cover_bytes, 'cover.png', 'catalog_cover')
    optimized['filename'] = 'cover.webp'
    return optimized

def build_catalog_content(metadata: Dict, pages: List[Dict], cover: Optional[Dict]) -> Dict:
    product_id = metadata['productId']
    content = {
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
        'coverImage': 'cover.webp' if cover else '',
        'pageCount': len(pages),
        'pages': [
            image_metadata(page['filename'], page) | {'pageNumber': page['pageNumber']}
            for page in pages
        ],
    }
    if cover:
        content.update({
            'coverWidth': cover['width'],
            'coverHeight': cover['height'],
            'coverByteSize': cover['byteSize'],
            'coverSha256': cover['sha256'],
        })
    return content


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
    pages = render_catalog_pdf_pages(pdf_bytes)
    cover = convert_cover_image(cover_bytes)
    content = build_catalog_content(metadata, pages, cover)
    entry = build_catalog_index_entry(metadata, len(pages))
    index = build_catalog_index(existing_index, entry)
    product_id = metadata['productId']
    files = {
        catalog_content_path(product_id): json.dumps(content, indent=2, ensure_ascii=False).encode('utf-8'),
        catalog_index_path(): json.dumps(index, indent=2, ensure_ascii=False).encode('utf-8'),
    }
    records = []
    seen_hashes = {}
    for page in pages:
        duplicate_of = seen_hashes.get(page['sha256'])
        if duplicate_of:
            page['duplicateOf'] = duplicate_of
        else:
            seen_hashes[page['sha256']] = page['filename']
            files[page_path(product_id, page['pageNumber'])] = page['bytes']
        records.append({key: value for key, value in page.items() if key != 'bytes'})
    if cover:
        duplicate_of = seen_hashes.get(cover['sha256'])
        if duplicate_of:
            cover['duplicateOf'] = duplicate_of
        else:
            seen_hashes[cover['sha256']] = 'cover.webp'
            files[cover_path(product_id)] = cover['bytes']
        records.append({key: value for key, value in cover.items() if key != 'bytes'})
    files[f'{catalog_root(product_id)}/imageOptimizationReport.json'] = report_json_bytes(records)
    return {
        'files': files,
        'content': content,
        'index': index,
        'pages': pages,
        'coverBytes': cover['bytes'] if cover else None,
        'coverRecord': cover,
        'optimization': summarize_records(records),
    }
