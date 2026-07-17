"""Validation for generated catalog submissions."""

from __future__ import annotations

import base64
import os
from typing import Dict, List

from catalog_builder import catalog_content_path, catalog_index_path, catalog_root
from product_catalog import get_categories


def official_categories_by_id():
    return {category['categoryId'].replace('_', '-'): category for category in get_categories()}


def official_products_by_id():
    products = {}
    for category in get_categories():
        category_id = category['categoryId'].replace('_', '-')
        for product_name in category['products']:
            # productId is already injected into metadata by app.py from get_product_defaults.
            pass
    return products


def has_bad_payload(value) -> bool:
    if isinstance(value, str):
        return os.path.isabs(value) or value.startswith('data:') or 'base64,' in value
    if isinstance(value, dict):
        return any(has_bad_payload(item) for item in value.values())
    if isinstance(value, list):
        return any(has_bad_payload(item) for item in value)
    return False


def validate_catalog_submission(metadata: Dict, generated: Dict) -> List[str]:
    errors = []
    product_id = metadata.get('productId', '')
    category_id = metadata.get('categoryId', '')
    content = generated.get('content') or {}
    files = generated.get('files') or {}
    pages = generated.get('pages') or []

    if not product_id:
        errors.append('Product ID is required.')
    if not category_id:
        errors.append('Category ID is required.')
    if not metadata.get('title'):
        errors.append('Catalog title is required.')
    if not pages:
        errors.append('PDF must have at least one page.')
    if content.get('pageCount') != len(pages):
        errors.append('Generated page count does not match catalogContent.json pageCount.')
    if len(content.get('pages', [])) != len(pages):
        errors.append('Catalog pages list does not match generated page count.')

    expected_content = catalog_content_path(product_id)
    if expected_content not in files:
        errors.append(f'Missing generated catalog JSON: {expected_content}')
    if catalog_index_path() not in files:
        errors.append('Missing generated catalogIndex.json.')

    root = catalog_root(product_id) + '/'
    for path, data in files.items():
        if os.path.isabs(path):
            errors.append(f'Absolute destination path is not allowed: {path}')
        if '..' in path.split('/'):
            errors.append(f'Path traversal is not allowed: {path}')
        if path != catalog_index_path() and not path.startswith(root):
            errors.append(f'Catalog file outside product catalog folder: {path}')
        if not data:
            errors.append(f'Generated file is empty: {path}')

    seen_page_numbers = set()
    for index, page in enumerate(content.get('pages', []), start=1):
        if page.get('pageNumber') != index:
            errors.append('Page numbers must be sequential and ordered.')
        if page.get('pageNumber') in seen_page_numbers:
            errors.append(f'Duplicate page number: {page.get("pageNumber")}')
        seen_page_numbers.add(page.get('pageNumber'))
        image_file = page.get('imageFile', '')
        expected_path = f'{root}{image_file}'
        if expected_path not in files:
            errors.append(f'Missing generated page image: {expected_path}')
        if os.path.isabs(image_file) or '..' in image_file.split('/'):
            errors.append(f'Unsafe image path: {image_file}')

    cover = content.get('coverImage')
    if cover:
        expected_cover = f'{root}{cover}'
        if expected_cover not in files:
            errors.append(f'Missing generated cover image: {expected_cover}')

    index = generated.get('index') or {}
    entry = (index.get('catalogs') or {}).get(product_id)
    if not entry:
        errors.append('catalogIndex.json is missing this product entry.')
    elif entry.get('contentFile') != expected_content:
        errors.append('catalogIndex entry points to the wrong catalogContent.json file.')

    if has_bad_payload(content) or has_bad_payload(index):
        errors.append('Generated JSON contains an absolute path or base64 data.')

    return errors
