"""Submission validation helpers."""

from __future__ import annotations

from typing import Dict, List, Tuple

from content_builder import validate_manual


def validate_submission(manual: Dict, image_files: Dict[str, bytes], confirmed: bool) -> Tuple[List[str], List[str]]:
    errors, warnings = validate_manual(manual, image_files)
    if not confirmed:
        errors.append('Confirm the content is ready for Akademika review before submitting.')
    return errors, warnings


def total_upload_size(files: Dict[str, bytes]) -> int:
    return sum(len(content) for content in files.values())


def human_size(size: int) -> str:
    units = ['B', 'KB', 'MB', 'GB']
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f'{value:.1f} {unit}' if unit != 'B' else f'{int(value)} B'
        value /= 1024
    return f'{size} B'
