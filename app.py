import json

import streamlit as st

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
from github_service import GitHubConfig, GitHubServiceError, submit_pull_request
from validation import human_size, total_upload_size, validate_submission
from product_catalog import clean_id, clean_product_id, get_categories, get_category_names, get_product_defaults, get_products, product_count

st.set_page_config(page_title='Akademika Manual Content Builder', layout='wide')

CUSTOM_PRODUCT = 'Add Custom Product'


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
    category_options = get_category_names() + [CUSTOM_PRODUCT]
    selected_category = st.sidebar.selectbox('Select Category', category_options)

    custom = selected_category == CUSTOM_PRODUCT
    if custom:
        category_name = st.sidebar.text_input('Category name', value=st.session_state.manual.get('categoryName', ''))
        product_name = st.sidebar.text_input('Product name', value=st.session_state.manual.get('productName', ''))
        default_category_id = clean_id(category_name)
        default_product_id = clean_product_id(product_name) if product_name else ''
    else:
        products = get_products(selected_category)
        selected_product = st.sidebar.selectbox('Select Product', products)
        defaults = get_product_defaults(selected_category, selected_product)
        category_name = defaults['categoryName']
        product_name = defaults['productName']
        default_category_id = defaults['categoryId']
        default_product_id = defaults['productId']

    st.sidebar.caption('IDs are auto-filled and can be manually overridden.')
    identity_key = clean_id(f'{category_name}_{product_name}') or 'custom_product'
    category_id = st.sidebar.text_input('categoryId', value=default_category_id, key=f'category_id_{identity_key}')
    product_id = st.sidebar.text_input('productId', value=default_product_id, key=f'product_id_{identity_key}')
    manual_id = st.sidebar.text_input('manualId', value=product_id, key=f'manual_id_{identity_key}')

    sync_manual_identity({
        'categoryName': category_name,
        'productName': product_name,
        'categoryId': category_id,
        'productId': product_id,
        'manualId': manual_id,
    })

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
    st.caption(f'{len(get_categories())} categories and {product_count()} products are available. Custom products are also supported.')

    manual = st.session_state.manual
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
