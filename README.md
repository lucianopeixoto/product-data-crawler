# 🛠 Product Data Crawler (MSDS & PDS) — v3

A tool to build **submittal packages** of Safety Data Sheets (SDS/MSDS) and
Product Data Sheets (PDS/TDS) for roofing and construction materials — for
your own company or for other contractors. Paste a product list, get a ZIP
with the PDFs plus CSV/XML indexes.

## What changed in v3: direct manufacturer sites only

v1 guessed PDF URLs (`base + product + "-msds.pdf"`), stopped at the first
manufacturer that answered 200, and saved whatever came back — which is how
a Soprema product became a blank PDF from IKO. v2 searched general web
search engines with `site:` filters, but those engines block datacenter IPs
and a general search can still hand back the wrong maker's PDF. v3 goes
**directly to each manufacturer's own website and nowhere else**:

- **Sika** — Sika Canada's own search page gives its product pages, and
  each product page lists its own SDS and PDS PDFs.
- **Tremco, IKO** — the manufacturer's own sitemap lists its product and
  document pages; the crawler follows those pages (found on the site
  itself, never guessed) and takes the PDF links listed on them.
- **No general web search fallback, ever.** If no listed manufacturer's
  own site turns up a matching document, the product is reported as
  **not found** and the record says why — including when no manufacturer
  was identified at all, and when a manufacturer has no verified adapter
  yet (see below). A wrong PDF from another maker is worse than a clear
  "not found" you can check manually.

Other rules that did not change:

- **No guessed URLs.** Every candidate comes from a link on a
  manufacturer's own page.
- **No blind saves.** A download is only kept if it is a real PDF:
  Content-Type is PDF (when the server says), the body starts with `%PDF`,
  and it is larger than 2 KB. A failed candidate is discarded and the next
  one is tried. Nothing blank or HTML is ever saved as a `.pdf`.
- **No data extracted from PDFs**, by design — the output is the documents
  themselves plus the indexes.
- **Cleaner install:** only `requests`, `beautifulsoup4`, `lxml`.

## Install

```bash
pip install -r requirements.txt
```

## Web interface

```bash
python webapp.py
# open http://127.0.0.1:8000
```

Paste products (one per line), pick the manufacturer if you know it, tick
SDS and/or PDS, pick the country, and download the submittal ZIP from the
job page. Keep browser lists modest (under ~20 products); use the CLI for
large lists.

A line can name its maker directly, e.g. `Sika: Sikaflex-1A`. If no maker
is named and no listed manufacturer's own site has a matching document,
the row says "manufacturer not identified" instead of guessing one.

## Command line (same as v1, plus options)

```bash
python msds-crawler.py materials.txt
python msds-crawler.py materials.txt --country US --out submittal-1
python msds-crawler.py materials.txt --no-pds
python msds-crawler.py materials.txt --manufacturer Sika
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

Each index row records: product, manufacturer (the maker whose own site
the PDF came from, the maker you named, or blank when none was
identified), file name, source URL, downloaded yes/no, status (`ok`, or a
`not_found: …` reason), and size in KB. A product with no valid PDF is
recorded as `not_found` — never as a file, never attributed to a maker
it was not found on.

## Manufacturers and country preference

Edit `manufacturers.json` to add, remove, or re-order manufacturers. The
default country is Canada (`CA`); use `--country US` or `--country ALL`
on the CLI, or the dropdown in the web UI, to change it. The current list
covers the big roofing names in Canada: Soprema, IKO, Carlisle, Firestone /
Elevate, Tremco, Sika, GAF, Owens Corning, Johns Manville, Siplast,
Polyglass, Henry, Malarkey, CertainTeed, Derbigum, Kemper System, Garland,
Hydrotech.

Each entry also carries an `adapter` — how the crawler reads that maker's
own site (`sika_serp`, `sitemap`, or `null`). Adapters verified live on
2026-10-27: Sika, Tremco, IKO. Manufacturers with `adapter: null` have no
verified static adapter yet, for a stated reason (Soprema's catalogue
loads through its on-site JavaScript search and its product API needs a
login; Carlisle's document search is likewise JavaScript-driven). For
those, the crawler reports not found with that reason instead of
guessing. To add an adapter for a new maker, add its sitemap or on-site
search URL to its entry — the code does the rest.

## Tests

```bash
python -m unittest discover -s tests -v
# or: python tests/test_crawler.py
```

Tests are offline (manufacturer pages are faked) and cover PDF validation,
doc classification (SDS vs PDS from link text and file name),
manufacturer-domain matching, product-line manufacturer parsing, the
sitemap and on-site-search adapters end to end, ZIP/index output, the
invalid-candidate-is-skipped path, and the not-found statuses.
