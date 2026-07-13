# Akademika Manual Content Builder

A Streamlit app for typists to create `manualContent.json` files and image ZIP packs for Akademika products. The tool supports every preset Akademika category and product, plus custom products.

## 1. Run Locally

```bash
cd Akademika-json-creater
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Open the local Streamlit URL shown in the terminal.

## 2. Deploy On Streamlit

1. Push this folder to a GitHub repository.
2. Go to Streamlit Community Cloud.
3. Create a new app from the repository.
4. Set the main file path to `app.py`.
5. Streamlit installs packages from `requirements.txt` automatically.

## 3. Select Category And Product

Use the sidebar:

1. Select Category.
2. Select Product.
3. Confirm the auto-filled `categoryId`, `productId`, and `manualId`.
4. Edit those IDs only if the project needs a manual override.

Choose `Add Custom Product` when a product is missing from the preset list. Then type the category name, product name, `categoryId`, `productId`, and `manualId` manually.

## 4. Add Experiments

Use `Add Experiment` in the sidebar. Select the experiment from `Select Experiment`, then fill:

- Experiment ID
- Experiment Number
- Experiment Title

## 5. Add Objective, Theory, And Procedure Text

Open the relevant tab, such as Objective, Theory, Functional Block, or Procedure. Click `Add Text Block`, type the content, and continue adding blocks as needed. Every section also supports image, note, and table blocks.

## 6. Upload Block Diagram And Reference Signal Images

Open `Technical Data`, then select `Block Diagram` or `Reference Signal`. Click `Add Image Block`, upload a `png`, `jpg`, `jpeg`, or `webp` file, and optionally type a caption.

Images are stored in the ZIP under:

```text
images/{manualId}/{experimentId}/{sectionKey}/{imageFile}
```

Technical Data images are stored under:

```text
images/{manualId}/{experimentId}/technicalData/{subsection}/{imageFile}
```

The JSON stores only the relative image path. It does not store base64 image data.

## 7. Download JSON

After validation passes, click `Download JSON Only`. The file name is `manualContent.json`.

## 8. Download ZIP

After validation passes, click `Download Final Content Pack ZIP`. The ZIP file is named:

```text
{manualId}_content_pack.zip
```

The ZIP contains:

```text
manualContent.json
images/
```

## 9. Send ZIP To Akademika

Send the downloaded `{manualId}_content_pack.zip` file to the Akademika app/content team. This ZIP is the final package needed for mobile app integration.

## 10. Important Session Note

Download the ZIP before closing or refreshing the browser. Streamlit session data is temporary, and uploaded images may be lost when the session ends.
