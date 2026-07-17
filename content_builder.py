"""Helpers for building, validating, and exporting Akademika manual content."""

from __future__ import annotations

import copy
import io
import json
import re
import zipfile
from pathlib import PurePosixPath
from typing import Dict, Iterable, List, Tuple

SECTION_KEYS = [
    'objective',
    'theory',
    'functionalBlock',
    'procedure',
    'observation',
    'equipments',
    'result',
    'conclusion',
]

SECTION_LABELS = {
    'objective': 'Objective',
    'theory': 'Theory',
    'functionalBlock': 'Functional Block',
    'procedure': 'Procedure',
    'observation': 'Observation',
    'equipments': 'Equipments',
    'result': 'Result',
    'conclusion': 'Conclusion',
}

TECHNICAL_DATA_KEYS = ['datasheet', 'blockDiagram', 'circuitDiagram', 'referenceSignal']

TECHNICAL_DATA_LABELS = {
    'datasheet': 'Datasheet',
    'blockDiagram': 'Block Diagram',
    'circuitDiagram': 'Circuit Diagram',
    'referenceSignal': 'Reference Signal',
}

IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}


def clean_slug(value: str, fallback: str = 'item') -> str:
    value = (value or '').strip().lower()
    value = re.sub(r'[^a-z0-9]+', '_', value)
    value = re.sub(r'_+', '_', value).strip('_')
    return value or fallback


def sanitize_filename(filename: str) -> str:
    name = (filename or 'image.png').strip().replace(' ', '_')
    name = re.sub(r'[^A-Za-z0-9._-]+', '_', name)
    return name or 'image.png'


def extension_allowed(filename: str) -> bool:
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    return ext in IMAGE_EXTENSIONS


def make_empty_sections() -> Dict:
    return {
        **{key: [] for key in SECTION_KEYS},
        'technicalData': {key: [] for key in TECHNICAL_DATA_KEYS},
    }


def make_experiment(index: int) -> Dict:
    return {
        'id': f'exp{index}',
        'experimentNumber': f'Experiment {index}',
        'title': '',
        'sections': make_empty_sections(),
    }


def make_manual(defaults: Dict) -> Dict:
    return {
        'manualId': defaults.get('manualId', ''),
        'productId': defaults.get('productId', ''),
        'categoryId': defaults.get('categoryId', ''),
        'productName': defaults.get('productName', ''),
        'categoryName': defaults.get('categoryName', ''),
        'experiments': [],
    }


def make_content_payload(manual: Dict) -> Dict:
    manual_id = manual.get('manualId', '')
    return {'manuals': {manual_id: copy.deepcopy(manual)}}


def submitted_manual_payload(manual: Dict) -> Dict:
    payload = make_content_payload(manual)
    manual_id = manual.get('manualId', '')
    manual_copy = payload['manuals'].get(manual_id, {})
    for _, _, block in iter_blocks(manual_copy):
        if block.get('type') == 'image' and block.get('imageFile'):
            block['imageFile'] = submission_image_relative_path(manual_id, block['imageFile'])
    return payload


def block_id(section_key: str, block_type: str, order: int) -> str:
    prefix = 'note' if block_type == 'note' else 'table' if block_type == 'table' else section_key
    return f'{prefix}_{order:03d}'


def make_block(block_type: str, section_key: str, order: int, **kwargs) -> Dict:
    base = {'id': block_id(section_key, block_type, order), 'type': block_type, 'order': order}
    if block_type == 'text':
        base['text'] = kwargs.get('text', '')
    elif block_type == 'note':
        base['text'] = kwargs.get('text', '')
    elif block_type == 'table':
        base['tableData'] = kwargs.get('tableData', '')
    elif block_type == 'image':
        base['imageFile'] = kwargs.get('imageFile', '')
        base['caption'] = kwargs.get('caption', '')
    else:
        raise ValueError(f'Unsupported block type: {block_type}')
    return base


def image_path(manual_id: str, experiment_id: str, section_key: str, filename: str, technical: bool = False) -> str:
    safe_file = sanitize_filename(filename)
    if technical:
        return f'images/{manual_id}/{experiment_id}/technicalData/{section_key}/{safe_file}'
    return f'images/{manual_id}/{experiment_id}/{section_key}/{safe_file}'


def submission_image_relative_path(manual_id: str, image_file: str) -> str:
    prefix = f'images/{manual_id}/'
    if image_file.startswith(prefix):
        return f'images/{image_file[len(prefix):]}'
    if image_file.startswith('images/'):
        return image_file
    return f'images/{image_file.lstrip(chr(47))}'


def submission_image_destination(manual_id: str, image_file: str) -> str:
    relative = submission_image_relative_path(manual_id, image_file)
    return str(PurePosixPath('src/content/manuals') / manual_id / relative)


def manual_content_destination(manual_id: str) -> str:
    return str(PurePosixPath('src/content/manuals') / manual_id / 'manualContent.json')


def manual_index_destination() -> str:
    return 'src/content/manualIndex.json'


def submitted_json_bytes(manual: Dict) -> bytes:
    return json.dumps(submitted_manual_payload(manual), indent=2, ensure_ascii=False).encode('utf-8')


def build_submission_files(manual: Dict, image_files: Dict[str, bytes]) -> Dict[str, bytes]:
    manual_id = manual.get('manualId') or 'manual'
    files = {manual_content_destination(manual_id): submitted_json_bytes(manual)}
    for image_file, content in sorted(image_files.items()):
        files[submission_image_destination(manual_id, image_file)] = content
    return files


def build_manual_index(existing_index, manual: Dict) -> Dict:
    manual_id = manual.get('manualId', '')
    entry = {
        'manualId': manual_id,
        'productId': manual.get('productId', ''),
        'categoryId': manual.get('categoryId', ''),
        'productName': manual.get('productName', ''),
        'categoryName': manual.get('categoryName', ''),
        'path': manual_content_destination(manual_id),
        'experimentCount': len(manual.get('experiments', [])),
    }

    if isinstance(existing_index, dict):
        index = copy.deepcopy(existing_index)
        manuals = index.get('manuals', [])
        if isinstance(manuals, dict):
            manuals[manual_id] = entry
        else:
            manuals = [item for item in manuals if isinstance(item, dict) and item.get('manualId') != manual_id]
            manuals.append(entry)
            manuals.sort(key=lambda item: item.get('manualId', ''))
        index['manuals'] = manuals
        return index

    manuals = []
    if isinstance(existing_index, list):
        manuals = [item for item in existing_index if isinstance(item, dict) and item.get('manualId') != manual_id]
    manuals.append(entry)
    manuals.sort(key=lambda item: item.get('manualId', ''))
    return {'manuals': manuals}


def iter_blocks(manual: Dict) -> Iterable[Tuple[str, str, Dict]]:
    for experiment in manual.get('experiments', []):
        exp_id = experiment.get('id', '')
        sections = experiment.get('sections', {})
        for section_key in SECTION_KEYS:
            for block in sections.get(section_key, []):
                yield exp_id, section_key, block
        for subsection_key in TECHNICAL_DATA_KEYS:
            for block in sections.get('technicalData', {}).get(subsection_key, []):
                yield exp_id, f'technicalData/{subsection_key}', block


def count_blocks(manual: Dict) -> int:
    return sum(1 for _ in iter_blocks(manual))


def validate_manual(manual: Dict, image_files: Dict[str, bytes]) -> Tuple[List[str], List[str]]:
    errors = []
    warnings = []

    if not manual.get('categoryName'):
        errors.append('Category is required.')
    if not manual.get('productName'):
        errors.append('Product is required.')
    if not manual.get('categoryId'):
        errors.append('categoryId is required.')
    if not manual.get('productId'):
        errors.append('productId is required.')
    if not manual.get('manualId'):
        errors.append('manualId is required.')

    experiments = manual.get('experiments', [])
    if not experiments:
        errors.append('At least one experiment is required.')
    for experiment in experiments:
        if not experiment.get('title'):
            errors.append(f"{experiment.get('experimentNumber') or experiment.get('id')}: experiment title is required.")

    if count_blocks(manual) == 0:
        errors.append('At least one content block is required.')

    for _, _, block in iter_blocks(manual):
        if block.get('type') == 'image':
            image_file = block.get('imageFile')
            if not image_file:
                errors.append(f"Image block {block.get('id')} has no imageFile path.")
            elif image_file not in image_files:
                errors.append(f"Image referenced in JSON is missing from ZIP: {image_file}")

    for image_file in image_files:
        if not image_file.startswith('images/'):
            warnings.append(f'Unexpected image path outside images folder: {image_file}')

    return errors, warnings


def json_bytes(manual: Dict) -> bytes:
    return json.dumps(make_content_payload(manual), indent=2, ensure_ascii=False).encode('utf-8')


def zip_bytes(manual: Dict, image_files: Dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    manual_id = manual.get('manualId') or 'manual'
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('manualContent.json', json_bytes(manual))
        archive.writestr('images/', b'')
        for experiment in manual.get('experiments', []):
            experiment_id = experiment.get('id') or 'exp'
            for section_key in SECTION_KEYS:
                archive.writestr(f'images/{manual_id}/{experiment_id}/{section_key}/', b'')
            for subsection_key in TECHNICAL_DATA_KEYS:
                archive.writestr(f'images/{manual_id}/{experiment_id}/technicalData/{subsection_key}/', b'')
        for path, content in sorted(image_files.items()):
            archive.writestr(path, content)
    buffer.seek(0)
    return buffer.getvalue()


def load_manual_payload(payload: Dict) -> Dict:
    manuals = payload.get('manuals', {}) if isinstance(payload, dict) else {}
    if not manuals:
        raise ValueError('Uploaded JSON does not contain a manuals object.')
    manual = next(iter(manuals.values()))
    manual.setdefault('experiments', [])
    manual.setdefault('categoryName', '')
    manual.setdefault('productName', '')
    manual.setdefault('categoryId', '')
    manual.setdefault('productId', '')
    manual.setdefault('manualId', next(iter(manuals.keys()), ''))
    for experiment in manual['experiments']:
        experiment.setdefault('sections', make_empty_sections())
        sections = experiment['sections']
        for key in SECTION_KEYS:
            sections.setdefault(key, [])
        sections.setdefault('technicalData', {})
        for key in TECHNICAL_DATA_KEYS:
            sections['technicalData'].setdefault(key, [])
    return manual
