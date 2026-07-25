"""Central image optimization helpers for Akademika Streamlit submissions."""

from __future__ import annotations

import hashlib
import io
import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Dict, Iterable, List, Optional

import fitz
from PIL import Image, ImageOps


@dataclass(frozen=True)
class ImageProfile:
    name: str
    max_width: int
    max_height: int
    quality: int
    lossless: bool = False
    preserve_alpha: bool = False
    warning_bytes: Optional[int] = None


PROFILES: Dict[str, ImageProfile] = {
    'product_thumbnail': ImageProfile('product_thumbnail', 512, 512, 78, warning_bytes=300 * 1024),
    'catalog_cover': ImageProfile('catalog_cover', 1200, 1600, 82, warning_bytes=500 * 1024),
    'manual_image': ImageProfile('manual_image', 1600, 1600, 82, warning_bytes=500 * 1024),
    'technical_diagram': ImageProfile('technical_diagram', 2200, 2200, 88, lossless=True, warning_bytes=800 * 1024),
    'catalog_page': ImageProfile('catalog_page', 1800, 2400, 82, warning_bytes=700 * 1024),
    'catalog_page_technical': ImageProfile('catalog_page_technical', 2200, 3000, 86, warning_bytes=700 * 1024),
    'logo_transparent': ImageProfile('logo_transparent', 1200, 1200, 100, lossless=True, preserve_alpha=True, warning_bytes=300 * 1024),
}

TECHNICAL_CONTEXTS = {'functionalBlock', 'blockDiagram', 'circuitDiagram', 'datasheet', 'referenceSignal'}
SUPPORTED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}


def human_size(size: int) -> str:
    units = ['B', 'KB', 'MB', 'GB']
    value = float(size or 0)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f'{value:.1f} {unit}' if unit != 'B' else f'{int(value)} B'
        value /= 1024
    return f'{size} B'


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data or b'').hexdigest()


def safe_stem(filename: str, fallback: str = 'image') -> str:
    name = (filename or fallback).rsplit('/', 1)[-1].rsplit('\\', 1)[-1]
    stem = name.rsplit('.', 1)[0].strip().lower()
    stem = re.sub(r'[^a-z0-9._-]+', '_', stem)
    stem = re.sub(r'_+', '_', stem).strip('._-')
    return stem or fallback


def safe_webp_filename(filename: str, fallback: str = 'image') -> str:
    return f'{safe_stem(filename, fallback)}.webp'


def supported_upload(filename: str) -> bool:
    extension = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    return extension in SUPPORTED_IMAGE_EXTENSIONS


def profile_for_context(section_key: str = '', technical: bool = False, purpose: str = '') -> str:
    if purpose in PROFILES:
        return purpose
    if section_key in TECHNICAL_CONTEXTS or technical:
        return 'technical_diagram'
    return 'manual_image'


def _has_alpha(image: Image.Image) -> bool:
    return image.mode in ('RGBA', 'LA') or (image.mode == 'P' and 'transparency' in image.info)


def _resize_no_upscale(image: Image.Image, profile: ImageProfile) -> Image.Image:
    image = ImageOps.exif_transpose(image)
    width, height = image.size
    scale = min(profile.max_width / width, profile.max_height / height, 1.0) if width and height else 1.0
    if scale >= 1.0:
        return image.copy()
    return image.resize((max(1, round(width * scale)), max(1, round(height * scale))), Image.Resampling.LANCZOS)


def _save_webp(image: Image.Image, profile: ImageProfile) -> bytes:
    buffer = io.BytesIO()
    alpha = _has_alpha(image)
    output = image.convert('RGBA') if alpha or profile.preserve_alpha else image.convert('RGB')
    output.save(
        buffer,
        format='WEBP',
        quality=profile.quality,
        method=6,
        lossless=profile.lossless or (alpha and profile.preserve_alpha),
        exact=alpha,
    )
    return buffer.getvalue()


def optimize_image_bytes(data: bytes, filename: str, profile_name: str) -> Dict:
    profile = PROFILES[profile_name]
    original_size = len(data or b'')
    with Image.open(io.BytesIO(data)) as opened:
        original_width, original_height = opened.size
        resized = _resize_no_upscale(opened, profile)
        optimized = _save_webp(resized, profile)
        width, height = resized.size

    digest = sha256_bytes(optimized)
    saved = original_size - len(optimized)
    percent_saved = (saved / original_size * 100) if original_size else 0
    warning = ''
    if profile.warning_bytes and len(optimized) > profile.warning_bytes:
        warning = f'{profile.name} output exceeds warning threshold: {human_size(len(optimized))}'
    return {
        'filename': safe_webp_filename(filename),
        'bytes': optimized,
        'width': width,
        'height': height,
        'byteSize': len(optimized),
        'sha256': digest,
        'originalSize': original_size,
        'originalWidth': original_width,
        'originalHeight': original_height,
        'optimizedSize': len(optimized),
        'percentSaved': percent_saved,
        'profile': profile.name,
        'warning': warning,
        'converted': True,
    }


def image_metadata(relative_path: str, optimized: Dict) -> Dict:
    return {
        'imageFile': relative_path,
        'width': optimized['width'],
        'height': optimized['height'],
        'byteSize': optimized['byteSize'],
        'sha256': optimized['sha256'],
    }


def summarize_records(records: Iterable[Dict]) -> Dict:
    rows = list(records or [])
    original_total = sum(row.get('originalSize', 0) for row in rows)
    optimized_total = sum(row.get('optimizedSize', 0) for row in rows)
    return {
        'originalTotalSize': original_total,
        'optimizedTotalSize': optimized_total,
        'bytesSaved': original_total - optimized_total,
        'percentSaved': ((original_total - optimized_total) / original_total * 100) if original_total else 0,
        'imagesConverted': sum(1 for row in rows if row.get('converted')),
        'imagesLeftUnchanged': sum(1 for row in rows if not row.get('converted')),
        'duplicatesDetected': sum(1 for row in rows if row.get('duplicateOf')),
        'records': rows,
    }


def report_json_bytes(records: Iterable[Dict]) -> bytes:
    return json.dumps(summarize_records(records), indent=2, ensure_ascii=False).encode('utf-8')


def is_text_dense_pdf_page(page: fitz.Page) -> bool:
    text = page.get_text('text') or ''
    drawings = page.get_drawings() or []
    return len(text.strip()) > 1200 or len(drawings) > 80


def render_pdf_page(page: fitz.Page, page_number: int, technical: bool = False) -> Dict:
    profile_name = 'catalog_page_technical' if technical else 'catalog_page'
    profile = PROFILES[profile_name]
    rect = page.rect
    scale = profile.max_width / rect.width if rect.width else 1.0
    matrix = fitz.Matrix(scale, scale)
    pixmap = page.get_pixmap(matrix=matrix, alpha=False)
    original_png = pixmap.tobytes('png')
    optimized = optimize_image_bytes(original_png, f'page_{page_number:03d}.png', profile_name)
    optimized['filename'] = f'page_{page_number:03d}.webp'
    optimized['pageNumber'] = page_number
    optimized['textDense'] = technical
    return optimized


def render_pdf_pages(pdf_bytes: bytes) -> List[Dict]:
    pages: List[Dict] = []
    with fitz.open(stream=pdf_bytes, filetype='pdf') as document:
        for index, page in enumerate(document, start=1):
            pages.append(render_pdf_page(page, index, is_text_dense_pdf_page(page)))
    return pages


def validate_processed_image(record: Dict) -> List[str]:
    errors: List[str] = []
    if not record.get('bytes'):
        errors.append('Processed image is empty.')
        return errors
    try:
        with Image.open(io.BytesIO(record['bytes'])) as image:
            image.verify()
        with Image.open(io.BytesIO(record['bytes'])) as image:
            width, height = image.size
            if width != record.get('width') or height != record.get('height'):
                errors.append('Processed image dimensions do not match metadata.')
    except Exception as exc:
        errors.append(f'Processed image cannot be opened: {exc}')
    if sha256_bytes(record['bytes']) != record.get('sha256'):
        errors.append('Processed image SHA-256 does not match metadata.')
    if record.get('width', 0) <= 0 or record.get('height', 0) <= 0:
        errors.append('Processed image width/height must be positive.')
    if record.get('optimizedSize', 0) > record.get('originalSize', 0) and record.get('profile') != 'logo_transparent':
        errors.append('Processed image is larger than original without a valid reason.')
    return errors


def relative_path_is_safe(path: str) -> bool:
    posix = str(PurePosixPath(path or ''))
    return bool(path) and not posix.startswith('/') and '..' not in PurePosixPath(posix).parts and 'base64,' not in path and not path.startswith('data:')
