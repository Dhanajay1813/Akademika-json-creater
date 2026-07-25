"""PDF validation, compression, page mapping, and preview helpers."""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from typing import Dict, List, Tuple

import fitz
from PIL import Image


PROFILE_PRESERVE = 'preserve_original_quality'
PROFILE_BALANCED = 'balanced'
PROFILE_HIGH_DETAIL = 'high_detail'

PDF_PROFILES = {
    PROFILE_HIGH_DETAIL: {
        'label': 'High Detail',
        'description': 'Recommended for technical laboratory manuals, circuit diagrams, dense tables, small labels, and observation sheets.',
        'target_dpi': 240,
        'threshold_dpi': 350,
        'jpeg_quality': 90,
        'rewrite_images': True,
    },
    PROFILE_BALANCED: {
        'label': 'Balanced',
        'description': 'General manuals with text, screenshots, and photographs.',
        'target_dpi': 200,
        'threshold_dpi': 300,
        'jpeg_quality': 84,
        'rewrite_images': True,
    },
    PROFILE_PRESERVE: {
        'label': 'Preserve Original Quality',
        'description': 'Vector diagrams, searchable text, fine drawings, and already optimized PDFs. Structural/lossless optimization only.',
        'target_dpi': None,
        'threshold_dpi': None,
        'jpeg_quality': None,
        'rewrite_images': False,
    },
}


@dataclass
class PdfValidation:
    valid: bool
    page_count: int = 0
    encrypted: bool = False
    page_dimensions: List[Tuple[float, float]] | None = None
    blank_pages: List[int] | None = None
    error: str = ''


def human_size(byte_count: int) -> str:
    value = float(byte_count or 0)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if value < 1024 or unit == 'GB':
            return f'{value:.1f} {unit}' if unit != 'B' else f'{int(value)} B'
        value /= 1024
    return f'{byte_count} B'


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_pdf(pdf_bytes: bytes) -> PdfValidation:
    try:
        document = fitz.open(stream=pdf_bytes, filetype='pdf')
    except Exception as exc:
        return PdfValidation(valid=False, error=str(exc), page_dimensions=[], blank_pages=[])
    try:
        if document.needs_pass:
            return PdfValidation(valid=False, encrypted=True, error='Encrypted PDFs must be unlocked before upload.', page_dimensions=[], blank_pages=[])
        dimensions = []
        blank_pages = []
        for index, page in enumerate(document, start=1):
            rect = page.rect
            dimensions.append((round(rect.width, 2), round(rect.height, 2)))
            if rect.width <= 0 or rect.height <= 0:
                return PdfValidation(valid=False, page_count=document.page_count, encrypted=False, error=f'Page {index} has invalid dimensions.', page_dimensions=dimensions, blank_pages=[])
            if not page.get_text('text').strip() and not page.get_images(full=True) and not page.get_drawings():
                blank_pages.append(index)
        return PdfValidation(valid=True, page_count=document.page_count, encrypted=False, page_dimensions=dimensions, blank_pages=blank_pages)
    finally:
        document.close()


def estimate_compressed_size(pdf_bytes: bytes, profile_key: str) -> int:
    profile = PDF_PROFILES.get(profile_key, PDF_PROFILES[PROFILE_HIGH_DETAIL])
    if not profile['rewrite_images']:
        return int(len(pdf_bytes) * 0.96)
    factor = 0.68 if profile_key == PROFILE_BALANCED else 0.78
    return int(len(pdf_bytes) * factor)


def image_dpi_on_page(page: fitz.Page, image_info: Dict) -> float:
    width = image_info.get('width') or 0
    height = image_info.get('height') or 0
    rects = page.get_image_rects(image_info['xref'])
    if not width or not height or not rects:
        return 0
    largest = max(rects, key=lambda rect: rect.width * rect.height)
    dpi_x = width / max(largest.width / 72, 0.01)
    dpi_y = height / max(largest.height / 72, 0.01)
    return max(dpi_x, dpi_y)


def downsample_image_bytes(source: bytes, target_width: int, target_height: int, quality: int) -> bytes:
    with Image.open(io.BytesIO(source)) as image:
        image = image.convert('RGB')
        image.thumbnail((target_width, target_height), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, format='JPEG', quality=quality, optimize=True)
        return output.getvalue()


def rewrite_oversized_images(document: fitz.Document, profile: Dict) -> int:
    rewritten = 0
    target_dpi = profile.get('target_dpi')
    threshold_dpi = profile.get('threshold_dpi')
    quality = profile.get('jpeg_quality')
    if not target_dpi or not threshold_dpi or not quality:
        return rewritten

    seen_xrefs = set()
    for page in document:
        for image_info in page.get_images(full=True):
            xref = image_info[0]
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)
            info = {'xref': xref, 'width': image_info[2], 'height': image_info[3]}
            dpi = image_dpi_on_page(page, info)
            if dpi <= threshold_dpi:
                continue
            extracted = document.extract_image(xref)
            source = extracted.get('image')
            if not source:
                continue
            scale = target_dpi / dpi
            target_width = max(1, int(info['width'] * scale))
            target_height = max(1, int(info['height'] * scale))
            try:
                replacement = downsample_image_bytes(source, target_width, target_height, quality)
                if len(replacement) < len(source):
                    page.replace_image(xref, stream=replacement)
                    rewritten += 1
            except Exception:
                continue
    return rewritten


def optimize_pdf(pdf_bytes: bytes, profile_key: str = PROFILE_HIGH_DETAIL) -> Dict:
    profile = PDF_PROFILES.get(profile_key, PDF_PROFILES[PROFILE_HIGH_DETAIL])
    original_validation = validate_pdf(pdf_bytes)
    if not original_validation.valid:
        raise ValueError(original_validation.error or 'Uploaded PDF is not valid.')

    document = fitz.open(stream=pdf_bytes, filetype='pdf')
    rewritten_images = 0
    try:
        if profile.get('rewrite_images'):
            rewritten_images = rewrite_oversized_images(document, profile)
        output = io.BytesIO()
        document.save(
            output,
            garbage=4,
            clean=True,
            deflate=True,
            deflate_images=True,
            deflate_fonts=True,
            use_objstms=1,
        )
    finally:
        document.close()

    optimized_bytes = output.getvalue()
    optimized_validation = validate_pdf(optimized_bytes)
    if not optimized_validation.valid or optimized_validation.page_count != original_validation.page_count:
        optimized_bytes = pdf_bytes
        optimized_validation = original_validation

    retained_original = False
    if len(optimized_bytes) > len(pdf_bytes):
        optimized_bytes = pdf_bytes
        optimized_validation = original_validation
        retained_original = True

    return {
        'bytes': optimized_bytes,
        'profile': profile_key,
        'profileLabel': profile['label'],
        'originalSize': len(pdf_bytes),
        'compressedSize': len(optimized_bytes),
        'bytesSaved': len(pdf_bytes) - len(optimized_bytes),
        'percentSaved': ((len(pdf_bytes) - len(optimized_bytes)) / len(pdf_bytes) * 100) if pdf_bytes else 0,
        'sha256': sha256_bytes(optimized_bytes),
        'pageCount': optimized_validation.page_count,
        'pageDimensions': optimized_validation.page_dimensions or [],
        'blankPages': optimized_validation.blank_pages or [],
        'rewrittenImages': rewritten_images,
        'retainedOriginal': retained_original,
        'warning': 'No size reduction was achieved; retained the smaller valid version.' if retained_original else '',
    }


def render_page_thumbnail(pdf_bytes: bytes, page_number: int, width: int = 360) -> bytes:
    document = fitz.open(stream=pdf_bytes, filetype='pdf')
    try:
        page = document.load_page(page_number - 1)
        zoom = width / max(page.rect.width, 1)
        pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return pixmap.tobytes('png')
    finally:
        document.close()


def parse_page_ranges(value: str, total_pages: int) -> List[int]:
    text = str(value or '').strip()
    if not text:
        return []
    pages = []
    seen = set()
    for part in text.split(','):
        item = part.strip()
        if not item:
            raise ValueError('Empty page range item.')
        if '-' in item:
            raw_start, raw_end = [piece.strip() for piece in item.split('-', 1)]
            if not raw_start.isdigit() or not raw_end.isdigit():
                raise ValueError(f'Invalid range: {item}')
            start = int(raw_start)
            end = int(raw_end)
            if start <= 0 or end <= 0:
                raise ValueError('Page numbers start at 1. Page 0 and negative pages are not allowed.')
            if start > end:
                raise ValueError(f'Descending range is not allowed: {item}')
            candidates = range(start, end + 1)
        else:
            if not item.isdigit():
                raise ValueError(f'Invalid page number: {item}')
            page = int(item)
            if page <= 0:
                raise ValueError('Page numbers start at 1. Page 0 and negative pages are not allowed.')
            candidates = [page]
        for page in candidates:
            if page > total_pages:
                raise ValueError(f'Page {page} is above the total page count of {total_pages}.')
            if page not in seen:
                seen.add(page)
                pages.append(page)
    return pages
