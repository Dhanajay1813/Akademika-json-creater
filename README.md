# Akademika Manual Content Builder

A Streamlit app for typists to create Akademika `manualContent.json` files, upload manual images, validate content, preview JSON, download JSON, download ZIP packs, and submit generated content to the private Akademika mobile app repository through a GitHub pull request.

## Run Locally

```bash
cd Akademika-json-creater
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Streamlit Secrets

Configure secrets in Streamlit Cloud or in local `.streamlit/secrets.toml`. Do not commit real secrets. Use `.streamlit/secrets.toml.example` as the template.

```toml
[github]
token = "github_token_with_repo_access"
owner = "Dhanajay1813"
mobile_repo = "Akademika-Learning-App"
base_branch = "main"
dry_run = true

[auth]
editor_password = "configured_in_streamlit"
```

The token is read only from `st.secrets["github"]["token"]`; it is never hardcoded.

## Existing Editor Workflow

The app keeps the existing workflow:

- product and category selection
- custom products
- experiment editor
- text, note, table, and image blocks
- image upload
- validation report
- JSON preview
- JSON download
- ZIP download

## Submit To Akademika App

The final section, **Submit to Akademika App**, reads these settings from Streamlit secrets:

- `st.secrets["github"]["token"]`
- `st.secrets["github"]["owner"]`
- `st.secrets["github"]["mobile_repo"]`
- `st.secrets["github"]["base_branch"]`
- `st.secrets["github"]["dry_run"]`

It shows a submission summary with destination repository, base branch, manual ID, product, experiment count, JSON destination paths, image count, and total upload size. The user must tick the review confirmation checkbox before submission.

## Dry Run Mode

When `dry_run = true`, the app validates the content and lists the exact files that would be committed. It does not create a branch, commit files, or create a pull request. A successful dry run shows `Dry run completed successfully.`

## Real Submission Mode

When `dry_run = false`, the app uses the GitHub REST API to:

1. Read the configured base branch.
2. Create a branch named `content/{manualId}-{timestamp}`.
3. Commit generated JSON and uploaded images to that branch.
4. Create or update `src/content/manualIndex.json`.
5. Open a pull request against `main`.

The app never commits directly to `main` and never merges automatically.

## Destination Paths

```text
src/content/manuals/{manualId}/manualContent.json
src/content/manuals/{manualId}/images/{experimentId}/{sectionPath}/{filename}
src/content/manualIndex.json
```


## Product Catalog Submission

Select a category and product, then choose `Product Catalog` as the content type. Upload a PDF catalog and optional cover image. The app renders each PDF page with PyMuPDF, converts pages to readable WebP images, validates the generated catalog package, and submits a pull request to `Dhanajay1813/Akademika-Learning-App`.

Generated catalog paths:

```text
src/content/catalogs/{productId}/catalogContent.json
src/content/catalogs/{productId}/cover.webp
src/content/catalogs/{productId}/pages/page_001.webp
src/content/catalogIndex.json
```

When `dry_run = true`, Streamlit renders and validates the PDF, shows destination paths and JSON previews, and creates no branch, commit, or pull request.

Configure the maximum catalog PDF size in Streamlit secrets:

```toml
[catalog]
max_pdf_mb = 80
```
