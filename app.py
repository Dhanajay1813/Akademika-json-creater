import json
import io

import pandas as pd

import streamlit as st

from catalog_builder import build_catalog_files, build_catalog_index_entry, human_size as catalog_human_size, pdf_page_count
from catalog_validation import validate_catalog_submission
from content_builder import (
    SECTION_KEYS,
    SECTION_LABELS,
    TECHNICAL_DATA_KEYS,
    TECHNICAL_DATA_LABELS,
    clean_slug,
    count_blocks,
    extension_allowed,
    image_path,
    json_bytes,
    load_manual_payload,
    make_block,
    make_empty_sections,
    make_experiment,
    make_manual,
    validate_manual,
    zip_bytes,
    build_submission_files,
    manual_content_destination,
    manual_index_destination,
    manual_pdf_destination,
    normalize_pdf_manual,
)
from pdf_optimizer import (
    PDF_PROFILES,
    PROFILE_HIGH_DETAIL,
    estimate_compressed_size,
    human_size as pdf_human_size,
    optimize_pdf,
    parse_page_ranges,
    render_page_thumbnail,
    validate_pdf,
)
from github_service import GitHubConfig, GitHubServiceError, submit_catalog_pull_request, submit_pull_request
from validation import human_size, total_upload_size, validate_submission
from image_optimizer import (
    PROFILES,
    human_size as image_human_size,
    image_metadata,
    optimize_image_bytes,
    profile_for_context,
    summarize_records,
)
from product_catalog import clean_id, clean_product_id, get_categories, get_category_names, get_product_defaults, get_products, product_count
from manual_library import (
    DEFAULT_MANUAL_LIBRARY_PATH,
    MOBILE_MANUAL_BLOCK_BYTES,
    MOBILE_MANUAL_TARGET_BYTES,
    MOBILE_MANUAL_WARNING_BYTES,
    candidate_manuals,
    estimated_library_size,
    library_summary,
    scan_manual_library,
)

st.set_page_config(page_title='Akademika Manual Content Builder', layout='wide')

CONTENT_TYPE_MANUAL = 'Experiment Manual'
CONTENT_TYPE_CATALOG = 'Product Catalog'


def init_state():
    if 'manual' not in st.session_state:
        defaults = get_product_defaults('Analog Communication', 'ACS: Analog Communication Training System')
        st.session_state.manual = make_manual(defaults)
    if 'image_files' not in st.session_state:
        st.session_state.image_files = {}
    if 'image_metadata' not in st.session_state:
        st.session_state.image_metadata = {}
    if 'image_optimization_records' not in st.session_state:
        st.session_state.image_optimization_records = []
    if 'selected_experiment_index' not in st.session_state:
        st.session_state.selected_experiment_index = 0
    if 'manual_pdf_original' not in st.session_state:
        st.session_state.manual_pdf_original = None
    if 'manual_pdf_optimized' not in st.session_state:
        st.session_state.manual_pdf_optimized = None
    if 'manual_pdf_profile' not in st.session_state:
        st.session_state.manual_pdf_profile = PROFILE_HIGH_DETAIL
    if 'manual_pdf_signature' not in st.session_state:
        st.session_state.manual_pdf_signature = ''
    if 'manual_source_mode' not in st.session_state:
        st.session_state.manual_source_mode = 'Manual Library'


def sync_manual_identity(defaults):
    manual = st.session_state.manual
    manual['categoryName'] = defaults['categoryName']
    manual['productName'] = defaults['productName']
    manual['categoryId'] = defaults['categoryId']
    manual['productId'] = defaults['productId']
    manual['manualId'] = defaults['manualId']




def table_file_signature(uploaded_file):
    if uploaded_file is None:
        return ""
    return f"{uploaded_file.name}:{getattr(uploaded_file, 'size', 0)}"


def image_files_signature(uploaded_files):
    if not uploaded_files:
        return ""
    return "|".join(f"{uploaded.name}:{getattr(uploaded, 'size', 0)}" for uploaded in uploaded_files)


def indexed_image_filename(filename, index, total):
    if total <= 1:
        return filename
    return f"{index + 1:02d}_{filename}"


def block_image_files(block):
    image_files = block.get('imageFiles')
    if isinstance(image_files, list):
        normalized = []
        for item in image_files:
            if isinstance(item, str) and item:
                normalized.append(item)
            elif isinstance(item, dict) and item.get('imageFile'):
                normalized.append(item['imageFile'])
        if normalized:
            return normalized
    image_file = block.get('imageFile')
    return [image_file] if image_file else []


def set_block_image_files(block, image_items):
    block['imageFiles'] = image_items
    first = image_items[0] if image_items else ''
    block['imageFile'] = first.get('imageFile') if isinstance(first, dict) else first


def existing_image_by_sha(manual_id, sha256):
    for path, metadata in st.session_state.image_metadata.items():
        if metadata.get('sha256') == sha256 and path.startswith(f'images/{manual_id}/'):
            return path
    return None


def unique_relative_path(base_path):
    if base_path not in st.session_state.image_files:
        return base_path
    stem, dot, ext = base_path.rpartition('.')
    for index in range(2, 1000):
        candidate = f'{stem}_{index}.{ext}' if dot else f'{base_path}_{index}'
        if candidate not in st.session_state.image_files:
            return candidate
    raise RuntimeError(f'Could not create a unique image path for {base_path}')


def optimization_summary(records=None):
    summary = summarize_records(records if records is not None else st.session_state.image_optimization_records)
    st.write(
        f"Original: `{image_human_size(summary['originalTotalSize'])}` | "
        f"Optimized: `{image_human_size(summary['optimizedTotalSize'])}` | "
        f"Saved: `{image_human_size(summary['bytesSaved'])}` ({summary['percentSaved']:.1f}%)"
    )
    st.write(
        f"Converted: `{summary['imagesConverted']}` | "
        f"Left unchanged: `{summary['imagesLeftUnchanged']}` | "
        f"Duplicates: `{summary['duplicatesDetected']}`"
    )
    warnings = [record.get('warning') for record in summary['records'] if record.get('warning')]
    for warning in warnings:
        st.warning(warning)


def read_table_file(uploaded_file):
    data = io.BytesIO(uploaded_file.getvalue())
    extension = uploaded_file.name.rsplit('.', 1)[-1].lower() if '.' in uploaded_file.name else ''
    if extension == 'csv':
        return pd.read_csv(data, dtype=str, keep_default_na=False)
    return pd.read_excel(data, dtype=str, keep_default_na=False)


def clean_table_cell(value):
    return str(value or "").replace("\n", " ").replace("|", "\\|").strip()


def dataframe_to_table_text(dataframe):
    columns = [clean_table_cell(column) or f"Column {index + 1}" for index, column in enumerate(dataframe.columns)]
    rows = dataframe.fillna("").values.tolist()
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join(["---"] * len(columns)) + " |"
    body = ["| " + " | ".join(clean_table_cell(cell) for cell in row) + " |" for row in rows]
    return "\n".join([header, separator, *body])


def parse_bool(value):
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'on'}
    return bool(value)


def github_config():
    github = st.secrets.get('github', {})
    return GitHubConfig(
        token=github.get('token', ''),
        owner=github.get('owner', ''),
        repo=github.get('mobile_repo', ''),
        base_branch=github.get('base_branch', 'main'),
        dry_run=parse_bool(github.get('dry_run', True)),
    )


def submission_summary(config, manual, files):
    manual_id = manual.get('manualId') or 'manual'
    image_count = len(st.session_state.image_files)
    st.subheader('Submission Summary')
    col1, col2 = st.columns(2)
    col1.write(f'**Destination repository:** `{config.owner}/{config.repo}`')
    col1.write(f'**Base branch:** `{config.base_branch}`')
    col1.write(f'**Manual ID:** `{manual_id}`')
    col1.write(f'**Product:** `{manual.get("productName") or "-"}`')
    col2.write(f'**Experiment count:** `{len(manual.get("experiments", []))}`')
    if manual.get('contentMode') == 'pdfPageMapping':
        col2.write(f'**Content mode:** `pdfPageMapping`')
        col2.write(f'**PDF size:** `{pdf_human_size(manual.get("compressedByteSize") or 0)}`')
    else:
        col2.write(f'**Image count:** `{image_count}`')
    col2.write(f'**Total upload size:** `{human_size(total_upload_size(files))}`')
    if st.session_state.image_optimization_records:
        st.write('**Image optimization:**')
        optimization_summary()
    st.write('**JSON destination paths:**')
    paths = [manual_content_destination(manual_id), manual_index_destination()]
    if manual.get('contentMode') == 'pdfPageMapping':
        paths.insert(1, manual_pdf_destination(manual_id))
    st.code('\n'.join(paths), language='text')


def submit_panel():
    st.header('Submit to Akademika App')
    manual = st.session_state.manual
    config = github_config()
    files = {}
    files_ready = True
    try:
        files = build_submission_files(manual, st.session_state.image_files)
    except Exception as exc:
        files_ready = False
        if manual.get('contentMode') == 'pdfPageMapping':
            st.info('Select a manual PDF from the library or upload one above so Streamlit can create the compressed manual.pdf for this submission.')
        else:
            st.warning(str(exc))
    submission_summary(config, manual, files)

    if config.dry_run:
        st.info('Dry-run mode is enabled. No branch, commit, or pull request will be created.')
    else:
        st.warning('Real submission mode is enabled. A branch and pull request will be created; main will not be changed directly.')

    confirmed = st.checkbox('I confirm this content is ready for Akademika review.')
    errors, warnings = validate_submission(manual, st.session_state.image_files, confirmed)
    if warnings:
        with st.expander('Submission Warnings'):
            for warning in warnings:
                st.write(f'- {warning}')

    if st.button('Submit Pull Request', disabled=bool(errors) or not files_ready):
        if errors:
            for error in errors:
                st.error(error)
            return
        missing = []
        if not config.token:
            missing.append('github.token')
        if not config.owner:
            missing.append('github.owner')
        if not config.repo:
            missing.append('github.mobile_repo')
        if not config.base_branch:
            missing.append('github.base_branch')
        if missing:
            st.error(f'Missing Streamlit secrets: {", ".join(missing)}')
            return
        try:
            result = submit_pull_request(config, manual, files)
        except GitHubServiceError as exc:
            st.error(str(exc))
            return

        st.write('**Files:**')
        st.code('\n'.join(result['files']), language='text')
        if result['dry_run']:
            st.success('Dry run completed successfully.')
            st.caption('No branch, commit, or pull request was created.')
        else:
            st.success('Pull request created.')
            st.write(f'Branch: `{result["branch"]}`')
            st.link_button('Open Pull Request', result['pull_request_url'])
    elif errors:
        with st.expander('Submission Requirements'):
            for error in errors:
                st.write(f'- {error}')

def current_experiment():
    experiments = st.session_state.manual.get('experiments', [])
    if not experiments:
        return None
    index = min(st.session_state.selected_experiment_index, len(experiments) - 1)
    st.session_state.selected_experiment_index = index
    return experiments[index]


def add_experiment():
    experiments = st.session_state.manual.setdefault('experiments', [])
    experiments.append(make_experiment(len(experiments) + 1))
    st.session_state.selected_experiment_index = len(experiments) - 1


def add_block_ui(experiment, section_key, blocks, technical=False):
    manual_id = st.session_state.manual.get('manualId', '')
    order = len(blocks) + 1
    cols = st.columns(4)
    if cols[0].button('Add Text Block', key=f'add_text_{experiment["id"]}_{section_key}_{technical}'):
        blocks.append(make_block('text', section_key, order))
        st.rerun()
    if cols[1].button('Add Image Block', key=f'add_image_{experiment["id"]}_{section_key}_{technical}'):
        blocks.append(make_block('image', section_key, order))
        st.rerun()
    if cols[2].button('Add Note Block', key=f'add_note_{experiment["id"]}_{section_key}_{technical}'):
        blocks.append(make_block('note', section_key, order))
        st.rerun()
    if cols[3].button('Add Table Block', key=f'add_table_{experiment["id"]}_{section_key}_{technical}'):
        blocks.append(make_block('table', section_key, order))
        st.rerun()

    for index, block in enumerate(list(blocks)):
        block.setdefault('order', index + 1)
        block.setdefault('id', f'{section_key}_{index + 1:03d}')
        with st.container(border=True):
            title_cols = st.columns([3, 1])
            title_cols[0].markdown(f'**{block["type"].title()} Block {index + 1}**  `{block["id"]}`')
            if title_cols[1].button('Delete', key=f'delete_{experiment["id"]}_{section_key}_{technical}_{index}'):
                blocks.pop(index)
                st.rerun()

            if block['type'] in ('text', 'note'):
                label = 'Note text' if block['type'] == 'note' else 'Text'
                block['text'] = st.text_area(label, value=block.get('text', ''), key=f'text_{experiment["id"]}_{section_key}_{technical}_{index}', height=160)
            elif block['type'] == 'table':
                table_key = f'table_{experiment["id"]}_{section_key}_{technical}_{index}'
                upload_key = f'upload_table_{experiment["id"]}_{section_key}_{technical}_{index}'
                upload_state_key = f'{upload_key}_loaded'
                if table_key not in st.session_state:
                    st.session_state[table_key] = block.get('tableData', '')
                uploaded_table = st.file_uploader('Upload CSV or Excel table', type=['csv', 'xlsx', 'xlsm', 'xls'], key=upload_key)
                if uploaded_table is not None:
                    try:
                        uploaded_dataframe = read_table_file(uploaded_table)
                    except Exception as exc:
                        st.error(f'Could not read table file: {exc}')
                    else:
                        signature = table_file_signature(uploaded_table)
                        if uploaded_dataframe.empty and len(uploaded_dataframe.columns) == 0:
                            st.error('Table file is empty.')
                        elif st.session_state.get(upload_state_key) != signature:
                            imported_table = dataframe_to_table_text(uploaded_dataframe)
                            block['tableData'] = imported_table
                            st.session_state[table_key] = imported_table
                            st.session_state[upload_state_key] = signature
                            st.success(f'Imported {len(uploaded_dataframe)} rows into the table block.')
                            st.rerun()
                        else:
                            block['tableData'] = st.session_state.get(table_key, block.get('tableData', ''))
                        st.dataframe(uploaded_dataframe, use_container_width=True, hide_index=True)
                block['tableData'] = st.text_area('Table data', key=table_key, height=160)
            elif block['type'] == 'image':
                upload_key = f'image_{experiment["id"]}_{section_key}_{technical}_{index}'
                upload_state_key = f'{upload_key}_loaded'
                uploaded_files = st.file_uploader(
                    'Upload images',
                    type=['png', 'jpg', 'jpeg', 'webp'],
                    accept_multiple_files=True,
                    key=upload_key,
                )
                default_profile = profile_for_context(section_key, technical)
                profile = st.selectbox(
                    'Advanced image type',
                    list(PROFILES.keys()),
                    index=list(PROFILES.keys()).index(default_profile),
                    key=f'profile_{experiment["id"]}_{section_key}_{technical}_{index}',
                )
                if uploaded_files:
                    invalid_files = [uploaded.name for uploaded in uploaded_files if not extension_allowed(uploaded.name)]
                    if invalid_files:
                        st.error('Only png, jpg, jpeg, and webp images are allowed.')
                    else:
                        signature = image_files_signature(uploaded_files) + f'|{profile}'
                        if st.session_state.get(upload_state_key) != signature:
                            for old_image_file in block_image_files(block):
                                st.session_state.image_files.pop(old_image_file, None)
                                st.session_state.image_metadata.pop(old_image_file, None)
                            image_items = []
                            records = []
                            total_files = len(uploaded_files)
                            for upload_index, uploaded in enumerate(uploaded_files):
                                original_name = indexed_image_filename(uploaded.name, upload_index, total_files)
                                try:
                                    optimized = optimize_image_bytes(uploaded.getvalue(), original_name, profile)
                                except Exception as exc:
                                    st.error(f'Could not optimize {uploaded.name}: {exc}')
                                    continue
                                duplicate_path = existing_image_by_sha(manual_id, optimized['sha256'])
                                if duplicate_path:
                                    relative_path = duplicate_path
                                    optimized['duplicateOf'] = duplicate_path
                                else:
                                    relative_path = unique_relative_path(image_path(manual_id, experiment['id'], section_key, optimized['filename'], technical=technical))
                                    st.session_state.image_files[relative_path] = optimized['bytes']
                                metadata = image_metadata(relative_path, optimized)
                                st.session_state.image_metadata[relative_path] = metadata
                                image_items.append(metadata)
                                record = {key: value for key, value in optimized.items() if key != 'bytes'}
                                record['imageFile'] = relative_path
                                records.append(record)
                                st.session_state.image_optimization_records.append(record)
                            set_block_image_files(block, image_items)
                            st.session_state[upload_state_key] = signature
                            st.success(f'Added {len(image_items)} optimized image(s) to this image block.')
                            optimization_summary(records)
                            st.rerun()

                block['caption'] = st.text_input('Optional caption for all images', value=block.get('caption', ''), key=f'caption_{experiment["id"]}_{section_key}_{technical}_{index}')
                image_files = block_image_files(block)
                if image_files:
                    st.caption(f'{len(image_files)} image(s) in this block')
                    for image_file in image_files:
                        image_bytes = st.session_state.image_files.get(image_file)
                        st.caption(image_file)
                        if image_bytes:
                            st.image(image_bytes, caption=block.get('caption') or None, use_container_width=True)
                        else:
                            st.warning('This image path is in JSON, but the image bytes are not loaded in the current Streamlit session.')


def section_editor(experiment, section_key, label, technical=False):
    st.subheader(label)
    if technical:
        blocks = experiment['sections']['technicalData'].setdefault(section_key, [])
    else:
        blocks = experiment['sections'].setdefault(section_key, [])
    add_block_ui(experiment, section_key, blocks, technical=technical)


def sidebar():
    st.sidebar.header('Product')
    selected_category = st.sidebar.selectbox('Select Category', get_category_names())
    products = get_products(selected_category)
    selected_product = st.sidebar.selectbox('Select Product', products)
    defaults = get_product_defaults(selected_category, selected_product)
    category_name = defaults['categoryName']
    product_name = defaults['productName']
    category_id = defaults['categoryId']
    product_id = defaults['productId']
    manual_id = defaults['manualId']

    st.sidebar.caption('IDs are official mobile-app IDs and cannot be edited here.')
    st.sidebar.text_input('categoryId', value=category_id, disabled=True)
    st.sidebar.text_input('productId', value=product_id, disabled=True)
    st.sidebar.text_input('manualId', value=manual_id, disabled=True)
    st.session_state.content_type = st.sidebar.radio('Content Type', [CONTENT_TYPE_MANUAL, CONTENT_TYPE_CATALOG])

    sync_manual_identity({
        'categoryName': category_name,
        'productName': product_name,
        'categoryId': category_id,
        'productId': product_id,
        'manualId': manual_id,
    })

    if st.session_state.content_type == CONTENT_TYPE_CATALOG:
        return

    st.sidebar.divider()
    st.sidebar.header('Experiments')
    if st.sidebar.button('Add Experiment'):
        add_experiment()
        st.rerun()

    experiments = st.session_state.manual.get('experiments', [])
    if experiments:
        labels = [f"{exp.get('experimentNumber') or exp.get('id')} - {exp.get('title') or 'Untitled'}" for exp in experiments]
        st.session_state.selected_experiment_index = st.sidebar.selectbox('Select Experiment', range(len(labels)), format_func=lambda i: labels[i], index=st.session_state.selected_experiment_index)
    else:
        st.sidebar.info('Add an experiment to start typing content.')

    st.sidebar.divider()
    st.sidebar.header('Import')
    uploaded_json = st.sidebar.file_uploader('Upload Existing manualContent.json', type=['json'])
    if uploaded_json is not None and st.sidebar.button('Load Uploaded JSON'):
        try:
            payload = json.loads(uploaded_json.getvalue().decode('utf-8'))
            st.session_state.manual = load_manual_payload(payload)
            st.session_state.image_files = {}
            st.session_state.image_metadata = {}
            st.session_state.image_optimization_records = []
            st.session_state.manual_pdf_original = None
            st.session_state.manual_pdf_optimized = None
            st.session_state.selected_experiment_index = 0
            st.sidebar.success('JSON loaded. Upload the compressed manual PDF before submission if this is a PDF page-mapped manual.')
            st.rerun()
        except Exception as exc:
            st.sidebar.error(f'Could not load JSON: {exc}')






def compress_selected_pdf(source_bytes, source_name, source_signature, profile_key, manual):
    if st.session_state.manual_pdf_signature == source_signature and st.session_state.manual_pdf_optimized:
        optimized = st.session_state.manual_pdf_optimized
        manual['_pdfBytes'] = optimized['bytes']
        return optimized

    validation = validate_pdf(source_bytes)
    st.subheader('PDF Source')
    col1, col2 = st.columns(2)
    col1.write(f'**Filename:** `{source_name}`')
    col1.write(f'**Original size:** `{pdf_human_size(len(source_bytes))}`')
    col1.write(f'**Estimated compressed size:** `{pdf_human_size(estimate_compressed_size(source_bytes, profile_key))}`')
    col2.write(f'**Total pages:** `{validation.page_count}`')
    col2.write(f'**Encrypted:** `{validation.encrypted}`')
    col2.write(f'**PDF validity:** `{"Valid" if validation.valid else "Invalid"}`')
    if not validation.valid:
        st.error(validation.error or 'PDF could not be validated.')
        return None
    try:
        optimized = optimize_pdf(source_bytes, profile_key)
    except Exception as exc:
        st.error(f'Could not compress PDF: {exc}')
        return None
    st.session_state.manual_pdf_original = source_bytes
    st.session_state.manual_pdf_optimized = optimized
    st.session_state.manual_pdf_signature = source_signature
    manual['originalFilename'] = source_name
    manual['totalPages'] = optimized['pageCount']
    manual['compressedByteSize'] = optimized['compressedSize']
    manual['sha256'] = optimized['sha256']
    manual['pdfFile'] = 'manual.pdf'
    manual['_pdfBytes'] = optimized['bytes']
    return optimized


def render_library_size_dashboard(records, profile_key):
    summary = library_summary(records)
    estimated = estimated_library_size(records, profile_key)
    st.subheader('Manual Library Size')
    cols = st.columns(4)
    cols[0].metric('PDF manuals found', summary['pdfCount'])
    cols[1].metric('Current source total', pdf_human_size(summary['totalBytes']))
    cols[2].metric('Estimated compressed total', pdf_human_size(estimated))
    cols[3].metric('Target', pdf_human_size(MOBILE_MANUAL_TARGET_BYTES))
    if estimated > MOBILE_MANUAL_BLOCK_BYTES:
        st.error(f'Estimated bundled manual size is above {pdf_human_size(MOBILE_MANUAL_BLOCK_BYTES)}. Use stronger per-manual compression before app integration.')
    elif estimated > MOBILE_MANUAL_WARNING_BYTES:
        st.warning(f'Estimated bundled manual size is above {pdf_human_size(MOBILE_MANUAL_WARNING_BYTES)}. Review largest manuals before final app integration.')
    elif estimated > MOBILE_MANUAL_TARGET_BYTES:
        st.warning(f'Estimated bundled manual size is above the {pdf_human_size(MOBILE_MANUAL_TARGET_BYTES)} target but still below the hard guardrail.')
    else:
        st.success('Estimated bundled manual library is within the target size budget.')
    if summary['largest']:
        with st.expander('Largest source manuals'):
            for record in summary['largest']:
                st.write(f"{pdf_human_size(record['byteSize'])} - `{record['relativePath']}`")


def selected_library_pdf(defaults, profile_key):
    root_path = st.text_input('Manual library folder', value=DEFAULT_MANUAL_LIBRARY_PATH)
    records = scan_manual_library(root_path)
    if not records:
        st.warning('No PDF manuals were found in the selected library folder.')
        return None
    render_library_size_dashboard(records, profile_key)
    candidates = candidate_manuals(records, defaults)
    options = candidates if candidates else records
    if not candidates:
        st.warning('No confident PDF match was found for this product. Select from all library PDFs.')
    def format_candidate_manual(record):
        match_type = record.get('matchType')
        prefix = f"[{match_type}] " if match_type else ''
        return f"{prefix}{record['relativePath']} ({pdf_human_size(record['byteSize'])})"

    selected = st.selectbox(
        'Product manual PDF',
        options,
        format_func=format_candidate_manual,
    )
    return selected


def section_content_total(section):
    if isinstance(section, dict):
        return len(section.get('pages', [])) + len(section.get('blocks', []))
    if isinstance(section, list):
        return len(section)
    return 0


def experiment_page_count(experiment):
    sections = experiment.get('sections', {})
    total = 0
    for key in SECTION_KEYS:
        total += section_content_total(sections.get(key, {}))
    for key in TECHNICAL_DATA_KEYS:
        total += section_content_total(sections.get('technicalData', {}).get(key, {}))
    return total


def experiment_coverage_panel():
    manual = st.session_state.manual
    experiments = manual.setdefault('experiments', [])
    st.subheader('Experiment Setup')
    target_count = st.number_input('Experiments in this manual', min_value=1, max_value=80, step=1, value=max(1, len(experiments) or 1))
    cols = st.columns(2)
    if cols[0].button('Create / Open Experiment Rows'):
        while len(experiments) < int(target_count):
            experiments.append(make_experiment(len(experiments) + 1))
        if not experiments:
            experiments.append(make_experiment(1))
        if st.session_state.selected_experiment_index >= len(experiments):
            st.session_state.selected_experiment_index = max(0, len(experiments) - 1)
        st.rerun()
    if cols[1].button('Add One More Experiment'):
        experiments.append(make_experiment(len(experiments) + 1))
        st.session_state.selected_experiment_index = len(experiments) - 1
        st.rerun()
    if not experiments:
        experiments.append(make_experiment(1))
        st.session_state.selected_experiment_index = 0

    labels = [f"{exp.get('experimentNumber') or exp.get('id')} - {exp.get('title') or 'Untitled'}" for exp in experiments]
    current_index = min(st.session_state.selected_experiment_index, len(labels) - 1)
    st.session_state.selected_experiment_index = st.selectbox(
        'Open experiment for page assignment',
        range(len(labels)),
        format_func=lambda i: labels[i],
        index=current_index,
        key='main_experiment_selector',
    )

    rows = []
    for experiment in experiments:
        mapped = experiment_page_count(experiment)
        missing_core = [SECTION_LABELS[key] for key in ('objective', 'theory', 'procedure') if section_content_total(experiment.get('sections', {}).get(key, {})) == 0]
        rows.append({
            'Experiment': experiment.get('experimentNumber') or experiment.get('id'),
            'Title': experiment.get('title') or 'Untitled',
            'Section content': mapped,
            'Status': 'Ready' if mapped else 'Needs content',
            'Core gaps': ', '.join(missing_core),
        })
    st.dataframe(rows, use_container_width=True, hide_index=True)


def render_page_preview_grid(pdf_bytes, pages, label, limit=12):
    if not pdf_bytes or not pages:
        return
    st.caption(f'Previewing {label}: {", ".join(str(page) for page in pages)}')
    if len(pages) > limit:
        st.warning(f'Showing first {limit} mapped pages only. {len(pages) - limit} more page(s) are mapped.')
    for row_start in range(0, min(len(pages), limit), 3):
        columns = st.columns(3)
        for column, page_number in zip(columns, pages[row_start:row_start + 3]):
            with column:
                try:
                    st.image(render_page_thumbnail(pdf_bytes, page_number), caption=f'Manual page {page_number}', use_container_width=True)
                except Exception as exc:
                    st.warning(f'Could not render page {page_number}: {exc}')


def mapped_section_rows(experiment):
    sections = experiment.get('sections', {})
    rows = []
    for key in SECTION_KEYS:
        section = sections.get(key, {})
        pages = section.get('pages', []) if isinstance(section, dict) else []
        blocks = section.get('blocks', []) if isinstance(section, dict) else section if isinstance(section, list) else []
        rows.append({'Section': SECTION_LABELS[key], 'PDF pages': ', '.join(str(page) for page in pages) or '-', 'Custom blocks': len(blocks)})
    for key in TECHNICAL_DATA_KEYS:
        section = sections.get('technicalData', {}).get(key, {})
        pages = section.get('pages', []) if isinstance(section, dict) else []
        blocks = section.get('blocks', []) if isinstance(section, dict) else section if isinstance(section, list) else []
        rows.append({'Section': f'Technical Data - {TECHNICAL_DATA_LABELS[key]}', 'PDF pages': ', '.join(str(page) for page in pages) or '-', 'Custom blocks': len(blocks)})
    return rows

def section_pages_editor(experiment, section_key, label, total_pages, technical=False):
    sections = experiment.setdefault('sections', make_empty_sections())
    container = sections.setdefault('technicalData', {}) if technical else sections
    current = container.setdefault(section_key, {'pages': [], 'blocks': []})
    if isinstance(current, list):
        current = {'pages': [], 'blocks': current}
        container[section_key] = current
    current.setdefault('pages', [])
    current.setdefault('blocks', [])
    default_value = ', '.join(str(page) for page in current.get('pages', []))
    st.caption('Enter PDF page numbers from the selected manual, for example: 4, 7-9, 12')
    pdf_ready = bool(total_pages and st.session_state.manual.get('_pdfBytes'))
    if not pdf_ready:
        st.info('Load a manual PDF above to enable page-number assignment and previews.')
    value = st.text_input(f'{label} PDF page numbers', value=default_value, key=f'pages_{experiment["id"]}_{section_key}_{technical}', disabled=not pdf_ready)
    try:
        pages = parse_page_ranges(value, total_pages) if total_pages else []
        current['pages'] = pages
        if pages:
            st.caption(f'Mapped pages: {", ".join(str(page) for page in pages)}')
            render_page_preview_grid(st.session_state.manual.get('_pdfBytes'), pages, label)
    except ValueError as exc:
        st.error(str(exc))

    with st.expander(f'Add custom {label} content', expanded=not current.get('pages') and bool(current.get('blocks'))):
        st.caption('Use this when a section should be text, images, notes, or tables instead of repeating the same PDF page in multiple sections.')
        add_block_ui(experiment, section_key, current.setdefault('blocks', []), technical=technical)


def preview_selected_pages(pdf_bytes, experiments):
    pages = []
    for experiment in experiments:
        sections = experiment.get('sections', {})
        for key in SECTION_KEYS:
            pages.extend(sections.get(key, {}).get('pages', []))
        for key in TECHNICAL_DATA_KEYS:
            pages.extend(sections.get('technicalData', {}).get(key, {}).get('pages', []))
    unique_pages = []
    seen = set()
    for page in pages:
        if page not in seen:
            seen.add(page)
            unique_pages.append(page)
    if not unique_pages or not pdf_bytes:
        return
    st.subheader('Temporary Selected-Page Preview')
    st.caption('These low-resolution previews are not committed, stored in JSON, or sent to the mobile app.')
    for page_number in unique_pages[:8]:
        try:
            st.image(render_page_thumbnail(pdf_bytes, page_number), caption=f'Manual page {page_number}', use_container_width=True)
        except Exception as exc:
            st.warning(f'Could not render page {page_number}: {exc}')


def manual_pdf_panel():
    manual = normalize_pdf_manual(st.session_state.manual)
    st.session_state.manual = manual
    profile_keys = list(PDF_PROFILES.keys())
    profile_key = st.selectbox(
        'PDF compression profile',
        profile_keys,
        index=profile_keys.index(st.session_state.manual_pdf_profile if st.session_state.manual_pdf_profile in profile_keys else PROFILE_HIGH_DETAIL),
        format_func=lambda key: PDF_PROFILES[key]['label'],
    )
    st.session_state.manual_pdf_profile = profile_key
    st.caption(PDF_PROFILES[profile_key]['description'])

    source_mode = st.radio('Manual source', ['Manual Library', 'Upload PDF'], horizontal=True, key='manual_source_mode')
    source_bytes = None
    source_name = ''
    source_signature = ''

    if source_mode == 'Manual Library':
        selected = selected_library_pdf(manual, profile_key)
        if selected:
            try:
                with open(selected['path'], 'rb') as source:
                    source_bytes = source.read()
                source_name = selected['filename']
                source_signature = f"library:{selected['relativePath']}:{selected['byteSize']}:{selected['mtime']}:{profile_key}"
                st.caption(f"Selected library PDF: `{selected['relativePath']}`")
            except OSError as exc:
                st.error(f'Could not read selected library PDF: {exc}')
                return False
        else:
            st.info('The library folder is not available here. Upload the selected product manual below to continue mapping.')
            uploaded_pdf = st.file_uploader('Upload product manual PDF for mapping', type=['pdf'], key='library_fallback_pdf')
            if uploaded_pdf is not None:
                source_bytes = uploaded_pdf.getvalue()
                source_name = uploaded_pdf.name
                source_signature = f"fallback-upload:{uploaded_pdf.name}:{getattr(uploaded_pdf, 'size', len(source_bytes))}:{profile_key}"
    else:
        uploaded_pdf = st.file_uploader('Complete manual PDF upload', type=['pdf'])
        if uploaded_pdf is not None:
            source_bytes = uploaded_pdf.getvalue()
            source_name = uploaded_pdf.name
            source_signature = f"upload:{uploaded_pdf.name}:{getattr(uploaded_pdf, 'size', len(source_bytes))}:{profile_key}"

    if source_bytes is None:
        st.info('Select a product manual from the library or upload one complete source PDF. You can still set up experiments below; page fields unlock after the PDF is loaded.')
        return False

    optimized = compress_selected_pdf(source_bytes, source_name, source_signature, profile_key, manual)
    if not optimized:
        return False

    manual['_pdfBytes'] = optimized['bytes']
    st.subheader('Compression Summary')
    cols = st.columns(3)
    cols[0].metric('Original PDF size', pdf_human_size(optimized['originalSize']))
    cols[1].metric('Compressed PDF size', pdf_human_size(optimized['compressedSize']))
    cols[2].metric('Reduction', f"{pdf_human_size(optimized['bytesSaved'])} ({optimized['percentSaved']:.1f}%)")
    st.write(f"**Profile:** `{optimized['profileLabel']}` | **Page count:** `{optimized['pageCount']}` | **SHA-256:** `{optimized['sha256']}`")
    st.write(f"**Oversized raster images rewritten:** `{optimized['rewrittenImages']}`")
    if optimized.get('warning'):
        st.warning(optimized['warning'])
    if optimized['compressedSize'] > 40 * 1024 * 1024:
        st.warning('Compressed PDF remains unusually large for a bundled mobile asset.')
    if optimized.get('blankPages'):
        st.warning(f"Blank pages detected: {', '.join(str(page) for page in optimized['blankPages'])}")
    return True


def pdf_mapping_editor():
    manual = st.session_state.manual
    total_pages = int(manual.get('totalPages') or 0)
    experiment_coverage_panel()
    experiment = current_experiment()
    if experiment is None:
        st.info('Add an experiment to map PDF pages.')
        return
    st.header('Assign Pages for Selected Experiment')
    cols = st.columns(4)
    experiment['id'] = cols[0].text_input('Experiment ID', value=experiment.get('id') or clean_slug(experiment.get('experimentNumber', ''), 'exp1'))
    experiment['experimentNumber'] = cols[1].text_input('Experiment Number', value=experiment.get('experimentNumber', ''))
    experiment['title'] = cols[2].text_input('Experiment Title', value=experiment.get('title', ''))
    experiment['displayOrder'] = cols[3].number_input('Display Order', min_value=1, step=1, value=int(experiment.get('displayOrder') or 1))
    st.caption('Use these tabs to choose section content. Each section can use mapped PDF pages, custom text/images/tables, or both.')
    with st.expander('Selected experiment mapping review', expanded=True):
        st.dataframe(mapped_section_rows(experiment), use_container_width=True, hide_index=True)
    tabs = st.tabs([SECTION_LABELS[key] for key in SECTION_KEYS] + ['Technical Data'])
    for tab, section_key in zip(tabs[:len(SECTION_KEYS)], SECTION_KEYS):
        with tab:
            section_pages_editor(experiment, section_key, SECTION_LABELS[section_key], total_pages)
    with tabs[-1]:
        tech_tabs = st.tabs([TECHNICAL_DATA_LABELS[key] for key in TECHNICAL_DATA_KEYS])
        for tab, key in zip(tech_tabs, TECHNICAL_DATA_KEYS):
            with tab:
                section_pages_editor(experiment, key, TECHNICAL_DATA_LABELS[key], total_pages, technical=True)
    with st.expander('Preview all mapped pages in this manual'):
        preview_selected_pages(manual.get('_pdfBytes'), manual.get('experiments', []))

def catalog_max_pdf_bytes():
    catalog = st.secrets.get('catalog', {})
    max_mb = catalog.get('max_pdf_mb', 80)
    try:
        return int(max_mb) * 1024 * 1024
    except (TypeError, ValueError):
        return 80 * 1024 * 1024


def catalog_panel():
    st.header('Product Catalog')
    manual = st.session_state.manual
    config = github_config()
    max_pdf_bytes = catalog_max_pdf_bytes()

    title = st.text_input('Catalog title', value=f"{manual.get('productName', 'Product')} Catalog")
    cols = st.columns(2)
    cols[0].text_input('Product name', value=manual.get('productName', ''), disabled=True)
    cols[1].text_input('Product ID', value=manual.get('productId', ''), disabled=True)
    cols = st.columns(2)
    cols[0].text_input('Category name', value=manual.get('categoryName', ''), disabled=True)
    cols[1].text_input('Category ID', value=manual.get('categoryId', ''), disabled=True)
    version = st.text_input('Catalog version (optional)', value='')
    revision_date = st.text_input('Revision date (optional)', value='')
    description = st.text_area('Short description (optional)', value='', height=100)
    pdf_file = st.file_uploader('Catalog PDF upload', type=['pdf'])
    cover_file = st.file_uploader('Cover image upload (optional)', type=['png', 'jpg', 'jpeg', 'webp'])

    if pdf_file is None:
        st.info('Upload a catalog PDF to continue.')
        return

    pdf_bytes = pdf_file.getvalue()
    if len(pdf_bytes) > max_pdf_bytes:
        st.error(f'PDF exceeds the configured maximum size of {catalog_human_size(max_pdf_bytes)}.')
        return

    try:
        page_count = pdf_page_count(pdf_bytes)
    except Exception as exc:
        st.error(f'Could not open PDF: {exc}')
        return

    metadata = {
        'productId': manual.get('productId', ''),
        'categoryId': manual.get('categoryId', ''),
        'productName': manual.get('productName', ''),
        'categoryName': manual.get('categoryName', ''),
        'title': title.strip(),
        'version': version.strip(),
        'revisionDate': revision_date.strip(),
        'description': description.strip(),
    }

    with st.spinner('Rendering PDF pages...'):
        try:
            generated = build_catalog_files(metadata, pdf_bytes, cover_file.getvalue() if cover_file else None)
        except Exception as exc:
            st.error(f'Could not render catalog PDF: {exc}')
            return

    errors = validate_catalog_submission(metadata, generated)
    files = generated['files']
    total_size = sum(len(value) for value in files.values())
    is_update = False

    st.subheader('Catalog Submission Summary')
    col1, col2 = st.columns(2)
    col1.write(f'**Destination repository:** `{config.owner}/{config.repo}`')
    col1.write(f'**Category:** `{metadata["categoryName"]}`')
    col1.write(f'**Product:** `{metadata["productName"]}`')
    col1.write(f'**Product ID:** `{metadata["productId"]}`')
    col1.write(f'**Catalog title:** `{metadata["title"]}`')
    col2.write(f'**PDF filename:** `{pdf_file.name}`')
    col2.write(f'**Original PDF size:** `{catalog_human_size(len(pdf_bytes))}`')
    col2.write(f'**Page count:** `{page_count}`')
    col2.write(f'**Generated image count:** `{len(generated["pages"])}`')
    col2.write(f'**Total generated size:** `{catalog_human_size(total_size)}`')
    col2.write(f'**Submission type:** `{"Update" if is_update else "New catalog or update check on submit"}`')
    st.write('**Image optimization:**')
    optimization_summary(generated.get('optimization', {}).get('records', []))

    st.write('**Destination paths:**')
    st.code('\n'.join(sorted(files)), language='text')
    if generated['pages']:
        st.image(generated['pages'][0]['bytes'], caption='Page 1 preview', use_container_width=True)
    st.write('**catalogContent.json preview:**')
    st.json(generated['content'])
    st.write('**catalogIndex.json preview:**')
    st.json(generated['index'])

    if errors:
        st.error('Fix these catalog validation errors before submitting:')
        for error in errors:
            st.write(f'- {error}')

    if config.dry_run:
        st.info('Dry-run mode is enabled. No branch, commit, or pull request will be created.')
    else:
        st.warning('Real mode is enabled. A catalog branch and pull request will be created; main will not be changed directly.')

    confirmed = st.checkbox('I confirm this catalog is ready for Akademika review.')
    if st.button('Submit Catalog Pull Request', disabled=bool(errors) or not confirmed):
        if not config.token or not config.owner or not config.repo or not config.base_branch:
            st.error('Missing GitHub Streamlit secrets.')
            return
        entry = build_catalog_index_entry(metadata, len(generated['pages']))
        try:
            result = submit_catalog_pull_request(config, metadata, files, entry)
        except GitHubServiceError as exc:
            st.error(str(exc))
            return
        st.write('**Files:**')
        st.code('\n'.join(result['files']), language='text')
        if result['dry_run']:
            st.success('Catalog dry run completed successfully.')
            st.caption('No branch, commit, or pull request was created.')
        else:
            st.success('Catalog pull request created.')
            if result.get('is_update'):
                st.info('This submission updates an existing catalog.')
            st.write(f'Branch: `{result["branch"]}`')
            st.link_button('Open Pull Request', result['pull_request_url'])

def export_panel():
    st.header('Preview and Export')
    errors, warnings = validate_manual(st.session_state.manual, st.session_state.image_files)
    with st.expander('Validation Report', expanded=True):
        if errors:
            st.error('Fix these items before sending the content pack:')
            for error in errors:
                st.write(f'- {error}')
        else:
            st.success('Validation passed.')
        if warnings:
            st.warning('Warnings:')
            for warning in warnings:
                st.write(f'- {warning}')

    payload_bytes = json_bytes(st.session_state.manual)
    zip_payload = b''
    export_ready = True
    try:
        zip_payload = zip_bytes(st.session_state.manual, st.session_state.image_files)
    except Exception:
        export_ready = False
    manual_id = st.session_state.manual.get('manualId') or 'manual'
    cols = st.columns(2)
    cols[0].download_button(
        'Download JSON Only',
        data=payload_bytes,
        file_name='manualContent.json',
        mime='application/json',
        disabled=bool(errors),
    )
    cols[1].download_button(
        'Download Final Content Pack ZIP',
        data=zip_payload,
        file_name=f'{manual_id}_content_pack.zip',
        mime='application/zip',
        disabled=bool(errors) or not export_ready,
    )
    if not export_ready:
        st.info('Load and compress a manual PDF before downloading the final ZIP.')

    with st.expander('JSON Preview'):
        st.json(json.loads(payload_bytes.decode('utf-8')))


def main():
    init_state()
    sidebar()

    st.title('Akademika Manual Content Builder')
    st.caption(f'{len(get_categories())} categories and {product_count()} official mobile products are available.')

    manual = st.session_state.manual
    if st.session_state.get('content_type') == CONTENT_TYPE_CATALOG:
        catalog_panel()
        return

    summary_cols = st.columns(4)
    summary_cols[0].metric('Category', manual.get('categoryName') or '-')
    summary_cols[1].metric('Product ID', manual.get('productId') or '-')
    summary_cols[2].metric('Manual ID', manual.get('manualId') or '-')
    summary_cols[3].metric('Mapped Pages', count_blocks(manual))

    manual_pdf_panel()
    pdf_mapping_editor()

    export_panel()
    submit_panel()


if __name__ == '__main__':
    main()
