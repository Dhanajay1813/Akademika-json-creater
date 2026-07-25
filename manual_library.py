"""Manual-library scanning helpers for the Streamlit assignment workflow."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List


REPO_MANUAL_LIBRARY_PATH = Path(__file__).resolve().parent / 'manual_library'
LOCAL_MANUAL_LIBRARY_PATH = '/media/akademika4675/013B-BBD5/AKADEMIKA MAUAL_VER24.0'
DEFAULT_MANUAL_LIBRARY_PATH = os.environ.get(
    'AKADEMIKA_MANUAL_LIBRARY',
    str(REPO_MANUAL_LIBRARY_PATH if REPO_MANUAL_LIBRARY_PATH.exists() else LOCAL_MANUAL_LIBRARY_PATH),
)

MOBILE_MANUAL_TARGET_BYTES = 850 * 1024 * 1024
MOBILE_MANUAL_WARNING_BYTES = 900 * 1024 * 1024
MOBILE_MANUAL_BLOCK_BYTES = 950 * 1024 * 1024


def normalize_tokens(value: str) -> List[str]:
    normalized = re.sub(r'[^a-z0-9]+', ' ', str(value or '').lower())
    return [token for token in normalized.split() if len(token) > 1]


def scan_manual_library(root_path: str) -> List[Dict]:
    root = Path(root_path).expanduser()
    if not root.exists() or not root.is_dir():
        return []
    records = []
    for path in sorted(root.rglob('*')):
        if not path.is_file() or path.suffix.lower() != '.pdf':
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        relative = path.relative_to(root)
        parts = relative.parts
        records.append({
            'path': str(path),
            'relativePath': relative.as_posix(),
            'filename': path.name,
            'categoryFolder': parts[0] if len(parts) > 1 else '',
            'productFolder': parts[-2] if len(parts) > 1 else '',
            'byteSize': stat.st_size,
            'mtime': stat.st_mtime,
        })
    return records


def library_summary(records: List[Dict]) -> Dict:
    sizes = [record.get('byteSize', 0) for record in records]
    total = sum(sizes)
    return {
        'pdfCount': len(records),
        'totalBytes': total,
        'averageBytes': int(total / len(records)) if records else 0,
        'largest': sorted(records, key=lambda item: item.get('byteSize', 0), reverse=True)[:10],
    }


def estimated_library_size(records: List[Dict], profile_key: str) -> int:
    if profile_key == 'balanced':
        factor = 0.68
    elif profile_key == 'preserve_original_quality':
        factor = 0.96
    else:
        factor = 0.78
    return int(sum(record.get('byteSize', 0) for record in records) * factor)


def score_record_for_product(record: Dict, defaults: Dict) -> int:
    haystack = ' '.join([
        record.get('relativePath', ''),
        record.get('filename', ''),
        record.get('productFolder', ''),
    ]).lower()
    score = 0
    product_id = str(defaults.get('productId') or '').lower()
    if product_id and product_id.replace('-', '') in re.sub(r'[^a-z0-9]+', '', haystack):
        score += 50
    for token in normalize_tokens(defaults.get('productId', '')):
        if token in haystack:
            score += 12
    for token in normalize_tokens(defaults.get('productName', '')):
        if token in haystack:
            score += 6
    for token in normalize_tokens(defaults.get('categoryName', '')):
        if token in haystack:
            score += 2
    return score


def candidate_manuals(records: List[Dict], defaults: Dict) -> List[Dict]:
    scored = []
    for record in records:
        score = score_record_for_product(record, defaults)
        if score > 0:
            scored.append({**record, 'score': score})
    return sorted(scored, key=lambda item: (-item['score'], item['byteSize'], item['relativePath']))
