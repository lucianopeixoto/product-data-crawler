import os
import sys
import requests
from bs4 import BeautifulSoup
import pandas as pd
import xml.etree.ElementTree as ET
import json
import re
import urllib.parse
import time
from tqdm import tqdm

BASE_FOLDER = "MSDS"
MSDS_FOLDER = os.path.join(BASE_FOLDER, "MSDS")
PDS_FOLDER = os.path.join(BASE_FOLDER, "PDS")
LIST_FOLDER = os.path.join(BASE_FOLDER, "lists")
HEADERS = {"User-Agent": "Mozilla/5.0"}

MANUFACTURER_JSON = "manufacturer_pdfs.json"


# -----------------------------
# UTILITIES
# -----------------------------
def clean_name(name):
    """Normalize product name for search."""
    return re.sub(r'[\\/*?:"<>|]', "", name.lower().strip())


def load_json(filename):
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def export(records, prefix):
    os.makedirs(LIST_FOLDER, exist_ok=True)
    df = pd.DataFrame(records)
    df.to_csv(os.path.join(LIST_FOLDER, f"{prefix}.csv"), index=False)

    root = ET.Element("Materials")
    for r in records:
        item = ET.SubElement(root, "Material")
        for k, v in r.items():
            child = ET.SubElement(item, k)
            child.text = str(v)
    tree = ET.ElementTree(root)
    tree.write(os.path.join(LIST_FOLDER, f"{prefix}.xml"), encoding="utf-8", xml_declaration=True)
    print(f"Saved {prefix} CSV and XML")


def download_pdf(url, path):
    try:
        r = requests.get(url, headers=HEADERS, stream=True, timeout=15)
        if r.status_code == 200:
            with open(path, "wb") as f:
                for chunk in r.iter_content(1024):
                    f.write(chunk)
            return True
    except Exception as e:
        print(f"Download error: {e}")
    return False


# -----------------------------
# SEARCH ENGINE FALLBACK
# -----------------------------
def search_pdf(product, doc_type):
    queries = []
    if doc_type == "MSDS":
        queries = [f"{product} SDS PDF", f"{product} MSDS PDF"]
    else:
        queries = [f"{product} PDS PDF", f"{product} TDS PDF", f"{product} technical data sheet PDF"]

    for q in queries:
        try:
            url = "https://duckduckgo.com/html/"
            resp = requests.get(url, headers=HEADERS, params={"q": q}, timeout=10)
            soup = BeautifulSoup(resp.text, "html.parser")
            links = soup.find_all("a", class_="result__a")
            for link in links:
                href = link.get("href")
                if href and "uddg=" in href:
                    parsed = urllib.parse.urlparse(href)
                    qs = urllib.parse.parse_qs(parsed.query)
                    real_url = qs.get("uddg", [None])[0]
                    if real_url and real_url.lower().endswith(".pdf"):
                        return real_url
        except Exception as e:
            print(f"Search error: {e}")
        time.sleep(1)
    return None


# -----------------------------
# MAIN PROCESS
# -----------------------------
def process_materials(materials, manufacturer_data):
    os.makedirs(MSDS_FOLDER, exist_ok=True)
    os.makedirs(PDS_FOLDER, exist_ok=True)

    msds_records = []
    pds_records = []

    for i, product in enumerate(tqdm(materials), start=1):
        index = f"{i:02d}"
        clean_product = clean_name(product)

        # ---------------------
        # Try manufacturer base URLs first
        # ---------------------
        msds_url = None
        pds_url = None
        for manu, data in manufacturer_data.items():
            base_url = data.get("base")
            if base_url:
                msds_url_candidate = f"{base_url}{clean_product}-msds.pdf"
                pds_url_candidate = f"{base_url}{clean_product}-tds.pdf"
                # quick HEAD request to check existence
                try:
                    if requests.head(msds_url_candidate, timeout=5).status_code == 200:
                        msds_url = msds_url_candidate
                    if requests.head(pds_url_candidate, timeout=5).status_code == 200:
                        pds_url = pds_url_candidate
                except:
                    pass
            if msds_url or pds_url:
                break

        # ---------------------
        # Fallback to DuckDuckGo
        # ---------------------
        if not msds_url:
            msds_url = search_pdf(clean_product, "MSDS")
        if not pds_url:
            pds_url = search_pdf(clean_product, "PDS")

        # ---------------------
        # Download PDFs
        # ---------------------
        msds_path = os.path.join(MSDS_FOLDER, f"{index} - {product} MSDS.pdf")
        pds_path = os.path.join(PDS_FOLDER, f"{index} - {product} PDS.pdf")

        msds_downloaded = download_pdf(msds_url, msds_path) if msds_url else False
        pds_downloaded = download_pdf(pds_url, pds_path) if pds_url else False

        msds_records.append({
            "Index": index,
            "Material": product,
            "FileName": f"{index} - {product} MSDS.pdf",
            "URL": msds_url or "NOT FOUND",
            "Downloaded": msds_downloaded
        })

        pds_records.append({
            "Index": index,
            "Material": product,
            "FileName": f"{index} - {product} PDS.pdf",
            "URL": pds_url or "NOT FOUND",
            "Downloaded": pds_downloaded
        })

        time.sleep(1)

    return msds_records, pds_records


# -----------------------------
# INPUT HANDLING
# -----------------------------
def load_materials():
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        with open(sys.argv[1], "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    else:
        print("No input file provided.")
        print("Instructions:")
        print("- You can create a text file with one product per line and pass it as argument next time")
        print("- Or type product names manually, one per line, type 'done' when finished")
        materials = []
        while True:
            item = input("> ").strip()
            if item.lower() == "done":
                break
            if item:
                materials.append(item)
        return materials


# -----------------------------
# MAIN
# -----------------------------
if __name__ == "__main__":
    manufacturer_data = load_json(MANUFACTURER_JSON)
    materials = load_materials()
    msds, pds = process_materials(materials, manufacturer_data)
    export(msds, "msds_index")
    export(pds, "pds_index")
    print("\nDone!")