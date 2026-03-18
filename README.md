# 🛠 Product Data Crawler (MSDS & PDS)

A Python tool to automatically download **Safety Data Sheets (MSDS/SDS)** and **Product Data Sheets (PDS/TDS)** for roofing and construction materials.

It supports:

* **Known manufacturer products** via a JSON lookup (dynamic URL concatenation)
* **Fallback search** using DuckDuckGo for unknown or new products
* Generates organized output folders and index files in **CSV and XML**

---

## ⚡ Features

* Automatic creation of folders:

```
MSDS/
  ├─ MSDS/       # downloaded MSDS PDFs
  ├─ PDS/        # downloaded PDS PDFs
  └─ lists/      # CSV and XML indexes
```

* Supports **manual or file input** of product names
* Normalizes product names for better search results
* Records download status in **indexes**

---

## 📋 Usage

### 1. File input (recommended)

Create a text file with **one product per line**, e.g. `materials.txt`:

```
soprastar gr
soprasmart board
duotack
```

Then run:

```bash
python msds-crawler.py materials.txt
```

### 2. Manual input

If no file is provided, the script prompts you:

```
> soprasmart board
> duotack
> done
```

---

## ⚙️ JSON Manufacturer Lookup

Edit `manufacturer_pdfs.json` to add or update manufacturers and base URLs. Example:

```json
{
    "Soprema": {
        "base": "https://www.soprema.ca/en/products/",
        "products": []
    }
}
```

* The crawler will first try to generate URLs from this base
* Falls back to DuckDuckGo search if no PDF is found

---

## 📌 Notes

* Uses Python libraries: `requests`, `beautifulsoup4`, `pandas`, `tqdm`, `lxml`
* Can be extended with **Selenium** for JS-heavy portals in the future
* Designed for roofing and construction material products, but easily adaptable
