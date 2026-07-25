"""Helpers for building, validating, and exporting Akademika manual content."""

from __future__ import annotations

import copy
import io
import json
import re
import zipfile
from pathlib import PurePosixPath
from typing import Dict, Iterable, List, Tuple

from image_optimizer import relative_path_is_safe, sha256_bytes, validate_processed_image

SECTION_KEYS = [
    'objective',
    'theory',
    'functionalBlock',
    'procedure',
    'observation',
    'equipments',
    'result',
    'conclusion',
    'references',
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
    'references': 'References',
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
    name = (filename or 'image.webp').strip().lower().replace(' ', '_')
    name = re.sub(r'[^a-z0-9._-]+', '_', name)
    return name or 'image.webp'


def extension_allowed(filename: str) -> bool:
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    return ext in IMAGE_EXTENSIONS


def make_empty_sections() -> Dict:
    return {
        **{key: {'pages': []} for key in SECTION_KEYS},
        'technicalData': {key: {'pages': []} for key in TECHNICAL_DATA_KEYS},
    }


def make_experiment(index: int) -> Dict:
    return {
        'id': f'exp{index}',
        'experimentNumber': f'Experiment {index}',
        'title': '',
        'displayOrder': index,
        'sections': make_empty_sections(),
    }


def make_manual(defaults: Dict) -> Dict:
    return {
        'schemaVersion': 3,
        'contentMode': 'pdfPageMapping',
        'manualId': defaults.get('manualId', ''),
        'productId': defaults.get('productId', ''),
        'categoryId': defaults.get('categoryId', ''),
        'productName': defaults.get('productName', ''),
        'categoryName': defaults.get('categoryName', ''),
        'pdfFile': 'manual.pdf',
        'originalFilename': '',
        'totalPages': 0,
        'compressedByteSize': 0,
        'sha256': '',
        'experiments': [],
    }


def make_content_payload(manual: Dict) -> Dict:
    manual_id = manual.get('manualId', '')
    return {'manuals': {manual_id: copy.deepcopy(manual)}}




def is_pdf_page_mapping(manual: Dict) -> bool:
    return manual.get('contentMode') == 'pdfPageMapping'


def normalize_page_section(value) -> Dict:
    if isinstance(value, dict):
        pages = value.get('pages', [])
    elif isinstance(value, list) and all(isinstance(item, int) for item in value):
        pages = value
    else:
        pages = []
    normalized = []
    seen = set()
    for page in pages:
        try:
            number = int(page)
        except (TypeError, ValueError):
            continue
        if number > 0 and number not in seen:
            seen.add(number)
            normalized.append(number)
    return {'pages': normalized}


def normalize_pdf_manual(manual: Dict) -> Dict:
    manual.setdefault('schemaVersion', 3)
    manual['contentMode'] = 'pdfPageMapping'
    manual.setdefault('pdfFile', 'manual.pdf')
    manual.setdefault('originalFilename', '')
    manual.setdefault('totalPages', 0)
    manual.setdefault('compressedByteSize', 0)
    manual.setdefault('sha256', '')
    for index, experiment in enumerate(manual.setdefault('experiments', []), start=1):
        experiment.setdefault('id', f'exp{index}')
        experiment.setdefault('experimentNumber', f'Experiment {index}')
        experiment.setdefault('title', '')
        experiment.setdefault('displayOrder', index)
        sections = experiment.setdefault('sections', {})
        for key in SECTION_KEYS:
            sections[key] = normalize_page_section(sections.get(key))
        sections.setdefault('technicalData', {})
        for key in TECHNICAL_DATA_KEYS:
            sections['technicalData'][key] = normalize_page_section(sections['technicalData'].get(key))
    return manual

def block_image_items(block: Dict) -> List[Dict]:
    image_files = block.get('imageFiles')
    normalized = []
    if isinstance(image_files, list):
        for item in image_files:
            if isinstance(item, str) and item:
                normalized.append({'imageFile': item})
            elif isinstance(item, dict) and item.get('imageFile'):
                normalized.append(dict(item))
    if normalized:
        return normalized
    image_file = block.get('imageFile')
    return [{'imageFile': image_file}] if image_file else []


def submitted_manual_payload(manual: Dict) -> Dict:
    if is_pdf_page_mapping(manual):
        manual_copy = normalize_pdf_manual(copy.deepcopy(manual))
        manual_copy.pop('_pdfBytes', None)
        return make_content_payload(manual_copy)
    payload = make_content_payload(manual)
    manual_id = manual.get('manualId', '')
    manual_copy = payload['manuals'].get(manual_id, {})
    for _, _, block in iter_blocks(manual_copy):
        if block.get('type') == 'image':
            image_items = block_image_items(block)
            if image_items:
                remapped_items = []
                for item in image_items:
                    next_item = dict(item)
                    next_item['imageFile'] = submission_image_relative_path(manual_id, item['imageFile'])
                    remapped_items.append(next_item)
                block['imageFiles'] = remapped_items
                block['imageFile'] = remapped_items[0]['imageFile']
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
        base['imageFiles'] = kwargs.get('imageFiles', [])
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


def block_image_files(block: Dict) -> List[str]:
    return [item['imageFile'] for item in block_image_items(block)]


def manual_content_destination(manual_id: str) -> str:
    return str(PurePosixPath('src/content/manuals') / manual_id / 'manualContent.json')


def manual_pdf_destination(manual_id: str) -> str:
    return str(PurePosixPath('src/content/manuals') / manual_id / 'manual.pdf')


def manual_index_destination() -> str:
    return 'src/content/manualIndex.json'


def content_registry_destination() -> str:
    return 'src/content/contentRegistry.js'


def submitted_json_bytes(manual: Dict) -> bytes:
    return json.dumps(submitted_manual_payload(manual), indent=2, ensure_ascii=False).encode('utf-8')



def js_identifier(value: str) -> str:
    cleaned = re.sub(r'[^A-Za-z0-9_$]+', '_', value or 'manual')
    if not cleaned or cleaned[0].isdigit():
        cleaned = f'manual_{cleaned}'
    return cleaned


def build_content_registry(manual: Dict, image_files: Dict[str, bytes]) -> bytes:
    manual_id = manual.get('manualId') or 'manual'
    manual_var = f'{js_identifier(manual_id)}ManualContent'
    lines = [
        "import manualIndex from './manualIndex.json';",
        f"import {manual_var} from './manuals/{manual_id}/manualContent.json';",
        '',
        'export const submittedManualIndex = manualIndex;',
        '',
        'export const submittedManuals = {',
        f"  '{manual_id}': {manual_var}.manuals['{manual_id}'],",
        '};',
        '',
        'export const submittedManualAssets = {',
    ]
    for image_file in sorted(image_files):
        relative = submission_image_relative_path(manual_id, image_file)
        lines.append(f"  '{manual_id}/{relative}': require('./manuals/{manual_id}/{relative}'),")
    lines.extend([
        '};',
        '',
        'export const getSubmittedManualImageSource = (manualId, imageFile) => (',
        '  submittedManualAssets[`${manualId}/${imageFile}`] || null',
        ');',
        '',
    ])
    return '\n'.join(lines).encode('utf-8')

def build_submission_files(manual: Dict, image_files: Dict[str, bytes]) -> Dict[str, bytes]:
    manual_id = manual.get('manualId') or 'manual'
    if is_pdf_page_mapping(manual):
        pdf_bytes = manual.get('_pdfBytes')
        if not pdf_bytes:
            raise ValueError('Compressed manual PDF is missing.')
        return {
            manual_content_destination(manual_id): submitted_json_bytes(manual),
            manual_pdf_destination(manual_id): pdf_bytes,
        }
    files = {
        manual_content_destination(manual_id): submitted_json_bytes(manual),
        content_registry_destination(): build_content_registry(manual, image_files),
    }
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
        'contentMode': manual.get('contentMode', 'blocks') if manual.get('contentMode') else 'blocks',
        'contentFile': manual_content_destination(manual_id),
        'path': manual_content_destination(manual_id),
        'experimentCount': len(manual.get('experiments', [])),
    }
    if is_pdf_page_mapping(manual):
        entry['pdfFile'] = manual_pdf_destination(manual_id)

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
    if is_pdf_page_mapping(manual):
        total = 0
        for experiment in manual.get('experiments', []):
            sections = experiment.get('sections', {})
            for key in SECTION_KEYS:
                total += len(normalize_page_section(sections.get(key)).get('pages', []))
            for key in TECHNICAL_DATA_KEYS:
                total += len(normalize_page_section(sections.get('technicalData', {}).get(key)).get('pages', []))
        return total
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

    if is_pdf_page_mapping(manual):
        total_pages = int(manual.get('totalPages') or 0)
        if manual.get('pdfFile') != 'manual.pdf':
            errors.append('PDF page-mapped manuals must use pdfFile: manual.pdf.')
        if total_pages <= 0:
            errors.append('Total page count is required.')
        if not manual.get('compressedByteSize'):
            errors.append('Compressed PDF size is required.')
        if not manual.get('sha256'):
            errors.append('Compressed PDF SHA-256 is required.')
        seen_pages = False
        for experiment in experiments:
            sections = experiment.get('sections', {})
            experiment_page_count = 0
            missing_core = []
            for key in SECTION_KEYS:
                pages = normalize_page_section(sections.get(key)).get('pages', [])
                seen_pages = seen_pages or bool(pages)
                experiment_page_count += len(pages)
                if key in ('objective', 'theory', 'procedure') and not pages:
                    missing_core.append(SECTION_LABELS[key])
                for page in pages:
                    if page <= 0:
                        errors.append(f'{experiment.get("id")}.{key} contains page 0 or a negative page.')
                    if total_pages and page > total_pages:
                        errors.append(f'{experiment.get("id")}.{key} page {page} exceeds total pages {total_pages}.')
            for key in TECHNICAL_DATA_KEYS:
                pages = normalize_page_section(sections.get('technicalData', {}).get(key)).get('pages', [])
                seen_pages = seen_pages or bool(pages)
                experiment_page_count += len(pages)
                for page in pages:
                    if page <= 0:
                        errors.append(f'{experiment.get("id")}.technicalData.{key} contains page 0 or a negative page.')
                    if total_pages and page > total_pages:
                        errors.append(f'{experiment.get("id")}.technicalData.{key} page {page} exceeds total pages {total_pages}.')
            if experiment_page_count == 0:
                errors.append(f'{experiment.get("experimentNumber") or experiment.get("id")}: map at least one PDF page before submission.')
            elif missing_core:
                warnings.append(f'{experiment.get("experimentNumber") or experiment.get("id")}: missing core mappings for {", ".join(missing_core)}.')
        if not seen_pages:
            errors.append('At least one mapped PDF page is required.')
        return errors, warnings

    if count_blocks(manual) == 0:
        errors.append('At least one content block is required.')

    seen_hashes = {}
    for _, _, block in iter_blocks(manual):
        if block.get('type') == 'image':
            image_items = block_image_items(block)
            if not image_items:
                errors.append(f"Image block {block.get('id')} has no imageFile path.")
            for item in image_items:
                image_file = item['imageFile']
                if not relative_path_is_safe(image_file):
                    errors.append(f'Unsafe image path in JSON: {image_file}')
                if image_file not in image_files:
                    errors.append(f"Image referenced in JSON is missing from ZIP: {image_file}")
                if item.get('width') is not None and int(item.get('width') or 0) <= 0:
                    errors.append(f'Invalid width metadata for image: {image_file}')
                if item.get('height') is not None and int(item.get('height') or 0) <= 0:
                    errors.append(f'Invalid height metadata for image: {image_file}')
                if item.get('sha256') and image_file in image_files and sha256_bytes(image_files[image_file]) != item.get('sha256'):
                    errors.append(f'SHA-256 metadata does not match image bytes: {image_file}')

    for image_file, content in image_files.items():
        if not image_file.startswith('images/'):
            warnings.append(f'Unexpected image path outside images folder: {image_file}')
        if not relative_path_is_safe(image_file):
            errors.append(f'Unsafe image path: {image_file}')
        digest = sha256_bytes(content)
        if digest in seen_hashes:
            warnings.append(f'Duplicate image bytes detected: {image_file} duplicates {seen_hashes[digest]}')
        else:
            seen_hashes[digest] = image_file
        processed_errors = validate_processed_image({
            'bytes': content,
            'sha256': digest,
            'width': 1,
            'height': 1,
            'optimizedSize': len(content),
            'originalSize': len(content),
            'profile': 'manual_image',
        })
        if processed_errors and content:
            # Dimension metadata is checked per JSON item above; this validates decodability and hash.
            for error in processed_errors:
                if 'dimensions' not in error:
                    errors.append(f'{image_file}: {error}')

    return errors, warnings


def json_bytes(manual: Dict) -> bytes:
    if is_pdf_page_mapping(manual):
        return json.dumps(submitted_manual_payload(manual), indent=2, ensure_ascii=False).encode('utf-8')
    return json.dumps(make_content_payload(manual), indent=2, ensure_ascii=False).encode('utf-8')


def zip_bytes(manual: Dict, image_files: Dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    manual_id = manual.get('manualId') or 'manual'
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('manualContent.json', json_bytes(manual))
        if is_pdf_page_mapping(manual):
            pdf_bytes = manual.get('_pdfBytes')
            if pdf_bytes:
                archive.writestr('manual.pdf', pdf_bytes)
            buffer.seek(0)
            return buffer.getvalue()
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
    if manual.get('contentMode') == 'pdfPageMapping':
        return normalize_pdf_manual(manual)
    for experiment in manual['experiments']:
        experiment.setdefault('sections', make_empty_sections())
        sections = experiment['sections']
        for key in SECTION_KEYS:
            sections.setdefault(key, [])
        sections.setdefault('technicalData', {})
        for key in TECHNICAL_DATA_KEYS:
            sections['technicalData'].setdefault(key, [])
    return manual
