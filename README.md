# 🛠 Product Data Crawler (MSDS & PDS) — v2

A tool to build **submittal packages** of Safety Data Sheets (SDS/MSDS) and
Product Data Sheets (PDS/TDS) for roofing and construction materials — for
your own company or for other contractors. Paste a product list, get a ZIP
with the PDFs plus CSV/XML indexes.

## What changed in v2

v1 guessed PDF URLs (`base + product + "-msds.pdf"`), stopped at the first
manufacturer that answered 200, and saved whatever came back — which is how
a Soprema product became a blank PDF from IKO. v2 fixes both problems:

- **No guessed URLs.** It searches site-by-site (`site:soprema.ca …`,
  `site:iko.com …`, …) in the order in `manufacturers.json`, so a PDF is
  only attributed to a manufacturer when it actually lives on that
  manufacturer's domain.
- **No blind saves.** A download is only kept if it is a real PDF:
  Content-Type is PDF (when the server says), the body starts with `%PDF`,
  and it is larger than 2 KB. A failed candidate is discarded and the next
  one is tried. Nothing blank or HTML is ever saved as a `.pdf`.
- **Both search problems fixed:** manufacturer-site search first, then a
  general web search (DuckDuckGo, then Bing) as fallback, with several
  candidates tried per product instead of just the first link.
- **Web UI + ZIP:** a simple browser interface that builds a downloadable
  submittal ZIP. The command line still works for scripts and big lists.
- **No data extracted from PDFs**, by design — the output is the documents
  themselves plus the indexes.
- **Cleaner install:** only `requests`, `beautifulsoup4`, `lxml`. The v1
  `requirements.txt` listed `urllib.parse`, which is not a pip package,
  and pandas/tqdm are no longer needed.

## Install

```bash
pip install -r requirements.txt
```

## Web interface (new)

```bash
python webapp.py
# open http://127.0.0.1:8000
```

Paste products (one per line), tick SDS and/or PDS, pick the country, and
download the submittal ZIP from the job page. Keep browser lists modest
(under ~20 products); use the CLI for large lists.

## Command line (same as v1, plus options)

```bash
python msds-crawler.py materials.txt
python msds-crawler.py materials.txt --country US --out submittal-1
python msds-crawler.py materials.txt --no-pds
```

With no file, products are typed manually, one per line, `done` to finish.

Output:

```
MSDS/
  ├─ MSDS/       # downloaded SDS PDFs
  ├─ PDS/        # downloaded PDS PDFs
  └─ lists/      # msds_index.csv/.xml, pds_index.csv/.xml
MSDS.zip         # the whole submittal package
```

Each index row records: product, manufacturer (from the PDF's domain, or
blank for a general web hit), file name, source URL, downloaded yes/no,
status (`ok`, `not_found`, `invalid_pdf`, `http_…`, …), and size in KB.
A product with no valid PDF is recorded as `not_found` — never as a file.

## Manufacturers and country preference

Edit `manufacturers.json` to add, remove, or re-order manufacturers. The
default country is Canada (`CA`); use `--country US` or `--country ALL`
on the CLI, or the dropdown in the web UI, to change it. The current list
covers the big roofing names in Canada: Soprema, IKO, Carlisle, Firestone /
Elevate, Tremco, Sika, GAF, Owens Corning, Johns Manville, Siplast,
Polyglass, Henry, Malarkey, CertainTeed, Derbigum, Kemper System, Garland,
Hydrotech. If a manufacturer changes its site, just update its domains
here — no code change needed.

## Tests

```bash
python -m unittest discover -s tests -v
# or: python tests/test_crawler.py
```

Tests are offline (search and download are faked) and cover PDF validation,
manufacturer-domain matching, ZIP/index output, and the
invalid-candidate-is-skipped path.
