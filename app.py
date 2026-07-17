import json

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
)
from github_service import GitHubConfig, GitHubServiceError, submit_catalog_pull_request, submit_pull_request
from validation import human_size, total_upload_size, validate_submission
from product_catalog import clean_id, clean_product_id, get_categories, get_category_names, get_product_defaults, get_products, product_count

st.set_page_config(page_title='Akademika Manual Content Builder', layout='wide')

CONTENT_TYPE_MANUAL = 'Experiment Manual'
CONTENT_TYPE_CATALOG = 'Product Catalog'


def init_state():
    if 'manual' not in st.session_state:
        defaults = get_product_defaults('Analog Communication', 'ACS: Analog Communication Training System')
        st.session_state.manual = make_manual(defaults)
    if 'image_files' not in st.session_state:
        st.session_state.image_files = {}
    if 'selected_experiment_index' not in st.session_state:
        st.session_state.selected_experiment_index = 0


def sync_manual_identity(defaults):
    manual = st.session_state.manual
    manual['categoryName'] = defaults['categoryName']
    manual['productName'] = defaults['productName']
    manual['categoryId'] = defaults['categoryId']
    manual['productId'] = defaults['productId']
    manual['manualId'] = defaults['manualId']




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
    col2.write(f'**Image count:** `{image_count}`')
    col2.write(f'**Total upload size:** `{human_size(total_upload_size(files))}`')
    st.write('**JSON destination paths:**')
    st.code('\n'.join([manual_content_destination(manual_id), manual_index_destination()]), language='text')


def submit_panel():
    st.header('Submit to Akademika App')
    manual = st.session_state.manual
    config = github_config()
    files = build_submission_files(manual, st.session_state.image_files)
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

    if st.button('Submit Pull Request', disabled=bool(errors)):
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
                block['tableData'] = st.text_area('Table data (CSV or simple table text)', value=block.get('tableData', ''), key=f'table_{experiment["id"]}_{section_key}_{technical}_{index}', height=160)
            elif block['type'] == 'image':
                uploaded = st.file_uploader('Upload image', type=['png', 'jpg', 'jpeg', 'webp'], key=f'image_{experiment["id"]}_{section_key}_{technical}_{index}')
                if uploaded is not None:
                    if extension_allowed(uploaded.name):
                        relative_path = image_path(manual_id, experiment['id'], section_key, uploaded.name, technical=technical)
                        st.session_state.image_files[relative_path] = uploaded.getvalue()
                        block['imageFile'] = relative_path
                    else:
                        st.error('Only png, jpg, jpeg, and webp images are allowed.')
                block['caption'] = st.text_input('Optional caption', value=block.get('caption', ''), key=f'caption_{experiment["id"]}_{section_key}_{technical}_{index}')
                if block.get('imageFile'):
                    image_bytes = st.session_state.image_files.get(block['imageFile'])
                    st.caption(block['imageFile'])
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
            st.session_state.selected_experiment_index = 0
            st.sidebar.success('JSON loaded. Re-upload image files before ZIP export if this JSON contains image blocks.')
            st.rerun()
        except Exception as exc:
            st.sidebar.error(f'Could not load JSON: {exc}')




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
    zip_payload = zip_bytes(st.session_state.manual, st.session_state.image_files)
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
        disabled=bool(errors),
    )

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
    summary_cols[3].metric('Content Blocks', count_blocks(manual))

    experiment = current_experiment()
    if experiment is None:
        st.info('Use Add Experiment in the sidebar to begin.')
        export_panel()
        submit_panel()
        return

    st.header('Experiment')
    exp_cols = st.columns(3)
    experiment['id'] = exp_cols[0].text_input('Experiment ID', value=experiment.get('id') or clean_slug(experiment.get('experimentNumber', ''), 'exp1'))
    experiment['experimentNumber'] = exp_cols[1].text_input('Experiment Number', value=experiment.get('experimentNumber', ''))
    experiment['title'] = exp_cols[2].text_input('Experiment Title', value=experiment.get('title', ''))
    experiment.setdefault('sections', make_empty_sections())

    section_tabs = st.tabs([SECTION_LABELS[key] for key in SECTION_KEYS] + ['Technical Data'])
    for tab, section_key in zip(section_tabs[:len(SECTION_KEYS)], SECTION_KEYS):
        with tab:
            section_editor(experiment, section_key, SECTION_LABELS[section_key])

    with section_tabs[-1]:
        tech_tabs = st.tabs([TECHNICAL_DATA_LABELS[key] for key in TECHNICAL_DATA_KEYS])
        experiment['sections'].setdefault('technicalData', {})
        for tab, subsection_key in zip(tech_tabs, TECHNICAL_DATA_KEYS):
            with tab:
                section_editor(experiment, subsection_key, TECHNICAL_DATA_LABELS[subsection_key], technical=True)

    export_panel()
    submit_panel()


if __name__ == '__main__':
    main()
