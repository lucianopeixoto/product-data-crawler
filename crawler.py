"""Product Data Crawler v3 — SDS/MSDS + PDS/TDS submittal packages.

How it finds documents (v3 — direct manufacturer sites only):
- v1 guessed PDF URLs and stopped at the first manufacturer that answered
  200. v2 searched general web search engines (DuckDuckGo, Bing) with
  site: filters. Both could still hand back the wrong manufacturer's PDF,
  and the search engines block datacenter IPs anyway.
- v3 goes directly to each manufacturer's own website and nowhere else:
  * Sika — the manufacturer's own search page (can.sika.com/en/serp.html)
    gives product pages; each product page lists its own SDS and PDS PDFs.
  * Tremco, IKO — the manufacturer's own sitemap lists its product and
    document pages; the crawler follows those pages (found on the site
    itself, never guessed) and takes the PDF links listed on them.
  * Every other manufacturer in manufacturers.json has no verified
    static adapter yet (their catalogues load through JavaScript search,
    or their API needs a login — Soprema and Carlisle are in this group).
    For those, the crawler does NOT fall back to a general web search.
    It reports the product as not found and says exactly why, so the
    user can check that manufacturer's site manually. A wrong PDF from
    another maker is worse than a clear "not found".

- No URL is ever guessed. Every candidate comes from a link on a
  manufacturer's own page, and it is only saved after checking:
  Content-Type is a PDF (when the server says), the body starts with
  %PDF, and it is larger than 2 KB. A failed candidate is discarded and
  the next one tried — nothing blank or HTML is ever saved as a .pdf.
- A product's manufacturer can be given explicitly — "Sika: Sikaflex-1A"
  in a list, --manufacturer on the CLI, or the dropdown in the web UI.
  When no manufacturer is identified and no manufacturer's own site
  turns up a matching document, the record says so plainly
  ("manufacturer not identified") instead of attributing the product
  to some maker found by a web search.
- Output is a submittal package: MSDS/ + PDS/ PDFs, CSV + XML indexes,
  and a single ZIP containing all of it. No data is extracted from
  inside the PDFs (by design — see README).

The CLI (msds-crawler.py) and the web UI (webapp.py) both use this
module, so a fix here fixes both. Only stdlib + requests + bs4 are
required.
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

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ProductDataCrawler/3.0)"}
MIN_PDF_BYTES = 2048  # smaller than this is almost certainly a blank/error page
FETCH_DELAY = 0.5  # polite pause between requests to a manufacturer's site
GENERIC_TOKENS = {"roof", "roofing", "membrane", "system", "product",
                  "series", "the", "and", "for", "with", "of"}


def clean_name(name):
    """Normalize a product name for matching."""
    return re.sub(r'[\\/*?:"<>|]', "", name.lower().strip())


def filename_safe(name):
    """Make a product name safe to use in a file name on any OS."""
    safe = re.sub(r'[\\/*?:"<>|]', "-", name.strip())
    safe = re.sub(r"\s+", " ", safe).strip()
    return safe[:120] or "product"


def product_tokens(product):
    """Significant search tokens for a product name.

    Numbers (180, 250, 1A) are kept — they are usually what tells two
    products from the same family apart. Generic roofing words are
    dropped so they cannot force a false match.
    """
    tokens = re.findall(r"[a-z0-9]+", product.lower())
    return [t for t in tokens if t not in GENERIC_TOKENS and len(t) >= 2]


def match_score(product, url_or_slug):
    """Fraction of the product's tokens found in a URL slug (0..1)."""
    tokens = product_tokens(product)
    if not tokens:
        return 0.0
    slug = url_or_slug.lower()
    matched = sum(1 for t in tokens if t in slug)
    return matched / len(tokens)


def parse_product_line(line, manufacturers):
    """Split an optional "Manufacturer: product" line.

    The prefix only counts when it exactly matches a manufacturer name
    in manufacturers.json (case-insensitive). "Sopralene Flam 180" has
    no colon and stays unidentified; "Sika: Sikaflex-1A" identifies Sika.
    Returns (product, manufacturer_name_or_None).
    """
    if ":" in line:
        prefix, rest = line.split(":", 1)
        for m in manufacturers:
            if prefix.strip().lower() == m["name"].lower():
                return rest.strip(), m["name"]
    return line.strip(), None


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


def fetch_html(url, session):
    """Fetch a page as text, or None on any failure / non-HTML response.

    Two attempts: some manufacturer search pages (Sika's SERP in
    particular) sometimes take over 20 seconds to answer, so a single
    short timeout would report a live product as not found.
    """
    for _attempt in range(2):
        try:
            resp = session.get(url, headers=HEADERS, timeout=30)
            if resp.status_code != 200:
                return None
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if ctype and "html" not in ctype and "xml" not in ctype and "text" not in ctype:
                return None
            return resp.text
        except Exception:
            time.sleep(1)
    return None


def extract_pdf_links(html, base_url):
    """(url, link text) for every PDF link on a page, resolved to absolute."""
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for a in soup.find_all("a", href=True):
        href = urllib.parse.urljoin(base_url, a["href"])
        path = urllib.parse.urlparse(href).path.lower()
        query = urllib.parse.urlparse(href).query.lower()
        if not (path.endswith(".pdf") or ".pdf" in query):
            continue
        text = " ".join(a.get_text(" ", strip=True).split())
        if href not in [u for u, _ in out]:
            out.append((href, text))
    return out


def classify_doc(link_text, url):
    """MSDS, PDS, or None, from a link's text and file name.

    Tremco: "US and Canadian SDS" / "Download Product Data Sheet".
    Sika: "Safety Data Sheet" / "Product Data Sheet".
    IKO: file names like IKO_TDS_... / SDS_..._EN.pdf.
    """
    hay = f"{link_text} {urllib.parse.urlparse(url).path}".lower()
    if ("safety data" in hay or " msds" in hay or " sds" in hay
            or "/sds" in hay or "sds_" in hay or "-sds-" in hay
            or "sds-" in hay):
        return "MSDS"
    if ("product data" in hay or "technical data" in hay
            or " pds" in hay or " tds" in hay
            or "/pds" in hay or "/tds" in hay
            or "pds_" in hay or "tds_" in hay
            or "-pds-" in hay or "-tds-" in hay):
        return "PDS"
    return None


def fetch_page(url, session, cache):
    """fetch_html with a per-run cache: one product's MSDS and PDS runs
    share the manufacturer's search page and product page, so a slow
    site is only fetched once per product instead of once per doc type."""
    if cache is not None and url in cache:
        return cache[url]
    html = fetch_html(url, session)
    if html and cache is not None:
        cache[url] = html
    return html


def fetch_sitemap_locs(url, session, cache, depth=0):
    """All <loc> URLs in a sitemap, following a sitemap index one level."""
    if url in cache:
        return cache[url]
    cache[url] = []
    html = fetch_html(url, session)
    if not html:
        return []
    locs = re.findall(r"<loc>([^<]+)</loc>", html)
    out = []
    if depth == 0:
        for loc in locs:
            if loc.lower().endswith(".xml"):
                out.extend(fetch_sitemap_locs(loc, session, cache, depth=1))
            else:
                out.append(loc)
    else:
        out = [l for l in locs if not l.lower().endswith(".xml")]
    cache[url] = out
    return out


def _page_candidates(page_url, doc_type, manu_name, manufacturers, session, page_cache=None):
    """PDF candidates of one doc type from one manufacturer page."""
    html = fetch_page(page_url, session, page_cache)
    if not html:
        return []
    out = []
    for url, text in extract_pdf_links(html, page_url):
        if classify_doc(text, url) != doc_type:
            continue
        if manufacturer_for_url(url, manufacturers) != manu_name:
            continue  # a PDF on another maker's host is never this maker's doc
        out.append((url, manu_name))
    return out


def _sitemap_candidates(product, doc_type, manu, manufacturers, session, cache, page_cache=None):
    """Candidates via a manufacturer's own sitemap -> product/document page."""
    urls = manu.get("sitemap_urls") or ([manu["sitemap_url"]] if manu.get("sitemap_url") else [])
    locs = []
    for u in urls:
        locs.extend(fetch_sitemap_locs(u, session, cache))
    paths = manu.get("page_paths") or []
    scored = []
    for loc in locs:
        if paths and not any(p in loc for p in paths):
            continue
        score = match_score(product, urllib.parse.urlparse(loc).path)
        if score >= 0.5:
            scored.append((score, loc))
    scored.sort(reverse=True)
    out = []
    for _score, loc in scored[:3]:
        out.extend(_page_candidates(loc, doc_type, manu["name"], manufacturers, session, page_cache))
        if len(out) >= 3:
            break
        time.sleep(FETCH_DELAY)
    return out[:3]


def _sika_candidates(product, doc_type, manu, manufacturers, session, page_cache=None):
    """Candidates via Sika Canada's own search page -> product page."""
    search_url = manu.get("search_url")
    if not search_url:
        return []
    html = fetch_page(search_url.format(q=urllib.parse.quote_plus(product)), session, page_cache)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    scored = []
    for a in soup.find_all("a", href=True):
        href = urllib.parse.urljoin(search_url, a["href"])
        if not href.startswith("https://can.sika.com/en/") or not href.endswith(".html"):
            continue
        if "serp" in href or "search" in href:
            continue
        score = match_score(product, urllib.parse.urlparse(href).path)
        if score >= 0.5:
            scored.append((score, href))
    scored.sort(reverse=True)
    out = []
    for _score, href in scored[:3]:
        out.extend(_page_candidates(href, doc_type, manu["name"], manufacturers, session, page_cache))
        if len(out) >= 3:
            break
        time.sleep(FETCH_DELAY)
    return out[:3]


def search_candidates(product, doc_type, manufacturers, session=None, sitemap_cache=None, page_cache=None):
    """Ordered PDF candidate URLs for one product + doc type.

    Direct manufacturer sites only, in manufacturers.json order. The
    scan stops at the first manufacturer whose own site turns up a
    matching document — that manufacturer is then the identified one.
    There is deliberately no general web search fallback: if no listed
    manufacturer's own site matches, the caller reports "not found"
    instead of attributing the product to a maker found elsewhere.
    Each entry is (url, manufacturer_name).
    """
    session = session or requests.Session()
    cache = sitemap_cache if sitemap_cache is not None else {}
    candidates = []
    for manu in manufacturers:
        adapter = manu.get("adapter")
        if adapter == "sika_serp":
            found = _sika_candidates(product, doc_type, manu, manufacturers, session, page_cache)
        elif adapter == "sitemap":
            found = _sitemap_candidates(product, doc_type, manu, manufacturers, session, cache, page_cache)
        else:
            found = []  # no verified direct adapter yet — never guess
        for url, name in found:
            if url not in [u for u, _ in candidates]:
                candidates.append((url, name))
        if candidates:
            break  # manufacturer identified by its own site
        time.sleep(FETCH_DELAY)
    return candidates[:5]


def download_pdf(url, path, session=None):
    """Download a URL, but only save it if it validates as a real PDF.

    Returns (ok, status, size_bytes). On failure nothing (or no partial
    file) is left at path.
    """
    session = session or requests.Session()
    try:
        r = session.get(url, headers=HEADERS, stream=True, timeout=60)
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


def not_found_status(product_manu, manu_entry, doc_type):
    """The honest 'let the user know' status for a product with no PDF."""
    if product_manu and manu_entry is None:
        return f"not_found: manufacturer '{product_manu}' is not in manufacturers.json"
    if product_manu and not manu_entry.get("adapter"):
        domain = (manu_entry.get("domains") or [""])[0]
        note = manu_entry.get("adapter_note") or f"check {domain} manually"
        return f"not_found: no direct adapter for {product_manu} yet – {note}"
    if product_manu:
        return f"not_found: no matching {doc_type} document on {product_manu}'s own site"
    return ("not_found: manufacturer not identified – no matching document "
            "on any listed manufacturer's own site")


def process_materials(materials, manufacturers, out_dir, want_msds=True, want_pds=True,
                      progress=None, manufacturer_filter=None):
    """Run a whole product list. Returns (msds_records, pds_records).

    For each product and doc type, candidates from the manufacturer's
    own site are tried in order until one validates as a real PDF.
    A product with no valid PDF is recorded as NOT FOUND, never as a
    blank file and never attributed to a manufacturer it was not
    found on.
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
    cache = {}
    page_cache = {}
    by_name = {m["name"].lower(): m for m in manufacturers}
    msds_records, pds_records = [], []
    for i, raw_line in enumerate(materials, start=1):
        index = f"{i:02d}"
        product, line_manu = parse_product_line(raw_line, manufacturers)
        effective_manu = line_manu or manufacturer_filter
        safe = filename_safe(product)
        query = clean_name(product)
        if progress:
            progress(f"{index} {product}")
        check = manufacturers
        if effective_manu:
            check = [by_name[effective_manu.lower()]] if effective_manu.lower() in by_name else []
        for doc_type, want, folder, records in (
            ("MSDS", want_msds, msds_dir, msds_records),
            ("PDS", want_pds, pds_dir, pds_records),
        ):
            if not want:
                continue
            filename = f"{index} - {safe} {doc_type}.pdf"
            path = os.path.join(folder, filename)
            url_used, manu_used, status, size = None, None, "not_found", 0
            for url, manu in search_candidates(query, doc_type, check, session, cache, page_cache):
                ok, status, size = download_pdf(url, path, session)
                if ok:
                    url_used, manu_used = url, manu
                    break
                if os.path.exists(path):
                    os.remove(path)
            if not url_used:
                entry = by_name.get(effective_manu.lower()) if effective_manu else None
                status = not_found_status(effective_manu, entry, doc_type)
            records.append({
                "Index": index,
                "Material": product,
                "Manufacturer": manu_used or (effective_manu or ""),
                "FileName": filename,
                "URL": url_used or "NOT FOUND",
                "Downloaded": bool(url_used),
                "Status": status if url_used else status,
                "SizeKB": round(size / 1024, 1) if url_used else 0,
            })
            time.sleep(FETCH_DELAY)
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
