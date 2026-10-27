"""Product Data Crawler v2 — SDS/MSDS + PDS/TDS submittal packages.

What changed from v1 (and why):
- v1 guessed PDF URLs (base + product + "-msds.pdf"), stopped at the first
  manufacturer that answered 200, and saved whatever came back. That is
  how a Soprema product ended up as a blank PDF from IKO.
- v2 never guesses a URL and never trusts a 200. It searches site-by-site
  (site:manufacturer-domain) so a PDF is only attributed to a manufacturer
  when it actually lives on that manufacturer's domain, and it only saves
  a download after checking: Content-Type is a PDF (when the server says),
  the body starts with %PDF, and it is larger than 2 KB. A failed
  candidate is discarded and the next candidate is tried — nothing blank
  or HTML is ever saved as a .pdf.
- Output is a submittal package: MSDS/ + PDS/ PDFs, CSV + XML indexes,
  and a single ZIP containing all of it, ready to hand to a contractor
  or a general contractor. No data is extracted from inside the PDFs
  (by design — see README).

The CLI (msds-crawler.py) and the web UI (webapp.py) both use this
module, so a fix here fixes both. Only stdlib + requests + bs4 are
required; pandas and tqdm from v1 are gone.
"""

import csv
import json
import os
import re
import time
import urllib.parse
import zipfile
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ProductDataCrawler/2.0)"}
MIN_PDF_BYTES = 2048  # smaller than this is almost certainly a blank/error page
SEARCH_DELAY = 0.5  # kept polite; site search also stops early once candidates exist


def clean_name(name):
    """Normalize a product name for search queries."""
    return re.sub(r'[\\/*?:"<>|]', "", name.lower().strip())


def filename_safe(name):
    """Make a product name safe to use in a file name on any OS."""
    safe = re.sub(r'[\\/*?:"<>|]', "-", name.strip())
    safe = re.sub(r"\s+", " ", safe).strip()
    return safe[:120] or "product"


def load_manufacturers(path="manufacturers.json", country=None):
    """Load manufacturers.json, filtered by country (CA/US/ALL).

    Country is configurable: pass country='CA' (default), 'US', or 'ALL'.
    A manufacturer entry with country='ALL' is always included.
    """
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    wanted = (country or data.get("country_default", "CA")).upper()
    out = []
    for m in data.get("manufacturers", []):
        if wanted == "ALL" or m.get("country", "ALL").upper() in (wanted, "ALL"):
            out.append(m)
    return out


def manufacturer_for_url(url, manufacturers):
    """Return the manufacturer name whose domain owns this URL, or None."""
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return None
    host = host[4:] if host.startswith("www.") else host
    for m in manufacturers:
        for d in m.get("domains", []):
            d = d.lower()
            if host == d or host.endswith("." + d):
                return m["name"]
    return None


def is_pdf_bytes(data):
    """True only for a real, non-trivial PDF body. No HTML, no blank page."""
    if not data or len(data) < MIN_PDF_BYTES:
        return False
    head = data[:1024].lstrip()
    if not head.startswith(b"%PDF"):
        return False
    if b"<html" in head.lower():
        return False
    return True


def _ddg_links(query, session):
    """PDF links for one DuckDuckGo html search. Returns [] on any failure."""
    try:
        resp = session.get(
            "https://duckduckgo.com/html/",
            headers=HEADERS, params={"q": query}, timeout=15,
        )
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            real = None
            if "uddg=" in href:
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                real = qs.get("uddg", [None])[0]
            elif href.lower().split("?")[0].endswith(".pdf"):
                real = href
            if real and real.lower().split("?")[0].endswith(".pdf") and real not in links:
                links.append(real)
        return links
    except Exception:
        return []


def _bing_links(query, session):
    """Fallback engine: Bing search, PDF links only. Returns [] on failure."""
    try:
        resp = session.get(
            "https://www.bing.com/search",
            headers=HEADERS, params={"q": query}, timeout=15,
        )
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.lower().split("?")[0].endswith(".pdf") and href not in links:
                links.append(href)
        return links
    except Exception:
        return []


def search_candidates(product, doc_type, manufacturers, session=None):
    """Ordered PDF candidate URLs for one product + doc type.

    Order matters and is the fix for the v1 bug:
    1. Site-restricted searches, manufacturer by manufacturer, in the
       order in manufacturers.json. A candidate is only kept here if its
       domain belongs to that manufacturer.
    2. General web search, any domain, clearly marked Unknown.
    Each entry is (url, manufacturer_name_or_None).
    """
    session = session or requests.Session()
    if doc_type == "MSDS":
        terms = ["SDS PDF", "MSDS PDF", "safety data sheet PDF"]
    else:
        terms = ["PDS PDF", "TDS PDF", "technical data sheet PDF"]
    candidates = []

    def add(url, manu):
        if url and url not in [u for u, _ in candidates]:
            candidates.append((url, manu))

    for manu in manufacturers:
        for domain in manu.get("domains", [])[:1]:  # primary domain only
            for term in terms[:1]:  # strongest term only; general search below covers the rest
                for url in _ddg_links(f"site:{domain} {product} {term}", session):
                    if manufacturer_for_url(url, manufacturers) == manu["name"]:
                        add(url, manu["name"])
                time.sleep(SEARCH_DELAY)
        if len(candidates) >= 3:
            break  # found the maker (or a strong match) — no need to scan the rest
    if len(candidates) < 5:
        for term in terms:
            for url in _ddg_links(f"{product} {term}", session):
                add(url, manufacturer_for_url(url, manufacturers))
            for url in _bing_links(f"{product} {term}", session):
                add(url, manufacturer_for_url(url, manufacturers))
            time.sleep(SEARCH_DELAY)
    return candidates[:15]


def download_pdf(url, path, session=None):
    """Download a URL, but only save it if it validates as a real PDF.

    Returns (ok, status, size_bytes). On failure nothing (or no partial
    file) is left at path.
    """
    session = session or requests.Session()
    try:
        r = session.get(url, headers=HEADERS, stream=True, timeout=30)
        if r.status_code != 200:
            return False, f"http_{r.status_code}", 0
        ctype = (r.headers.get("Content-Type") or "").lower()
        if ctype and "pdf" not in ctype and "octet-stream" not in ctype:
            return False, f"not_pdf_content_type:{ctype.split(';')[0]}", 0
        data = b"".join(r.iter_content(65536))
        if not is_pdf_bytes(data):
            return False, "invalid_pdf", len(data)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return True, "ok", len(data)
    except Exception as e:
        return False, f"download_error:{type(e).__name__}", 0


def process_materials(materials, manufacturers, out_dir, want_msds=True, want_pds=True, progress=None):
    """Run a whole product list. Returns (msds_records, pds_records).

    For each product and doc type, candidates are tried in order until
    one validates as a real PDF. A product with no valid PDF is recorded
    as NOT FOUND, never as a blank file.
    """
    msds_dir = os.path.join(out_dir, "MSDS")
    pds_dir = os.path.join(out_dir, "PDS")
    lists_dir = os.path.join(out_dir, "lists")
    if want_msds:
        os.makedirs(msds_dir, exist_ok=True)
    if want_pds:
        os.makedirs(pds_dir, exist_ok=True)
    os.makedirs(lists_dir, exist_ok=True)
    session = requests.Session()
    msds_records, pds_records = [], []
    for i, product in enumerate(materials, start=1):
        index = f"{i:02d}"
        safe = filename_safe(product)
        query = clean_name(product)
        if progress:
            progress(f"{index} {product}")
        for doc_type, want, folder, records in (
            ("MSDS", want_msds, msds_dir, msds_records),
            ("PDS", want_pds, pds_dir, pds_records),
        ):
            if not want:
                continue
            filename = f"{index} - {safe} {doc_type}.pdf"
            path = os.path.join(folder, filename)
            url_used, manu_used, status, size = None, None, "not_found", 0
            for url, manu in search_candidates(query, doc_type, manufacturers, session):
                ok, status, size = download_pdf(url, path, session)
                if ok:
                    url_used, manu_used = url, manu or "Unknown (web search)"
                    break
                if os.path.exists(path):
                    os.remove(path)
            records.append({
                "Index": index,
                "Material": product,
                "Manufacturer": manu_used or "",
                "FileName": filename,
                "URL": url_used or "NOT FOUND",
                "Downloaded": bool(url_used),
                "Status": status if url_used else "not_found",
                "SizeKB": round(size / 1024, 1) if url_used else 0,
            })
            time.sleep(SEARCH_DELAY)
    export(msds_records, lists_dir, "msds_index")
    export(pds_records, lists_dir, "pds_index")
    return msds_records, pds_records


def export(records, lists_dir, prefix):
    """Write CSV + XML indexes (same names as v1, for compatibility)."""
    os.makedirs(lists_dir, exist_ok=True)
    fields = ["Index", "Material", "Manufacturer", "FileName", "URL", "Downloaded", "Status", "SizeKB"]
    with open(os.path.join(lists_dir, f"{prefix}.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(records)
    root = ET.Element("Materials")
    for r in records:
        item = ET.SubElement(root, "Material")
        for k in fields:
            child = ET.SubElement(item, k)
            child.text = str(r.get(k, ""))
    ET.ElementTree(root).write(
        os.path.join(lists_dir, f"{prefix}.xml"), encoding="utf-8", xml_declaration=True)


def make_zip(out_dir, zip_path):
    """Zip a whole submittal package: MSDS/, PDS/, lists/."""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _dirs, files in os.walk(out_dir):
            for name in sorted(files):
                full = os.path.join(root, name)
                if os.path.abspath(full) == os.path.abspath(zip_path):
                    continue
                z.write(full, os.path.relpath(full, out_dir))
    return zip_path
