"""CLI for Product Data Crawler v2 (backward compatible with v1 usage).

    python msds-crawler.py materials.txt
    python msds-crawler.py materials.txt --country US --out submittal-1
    python msds-crawler.py --help

With no file argument, products are typed manually, one per line, 'done'
to finish — same as v1. Output is MSDS/ + PDS/ PDFs, lists/*.csv + *.xml,
and a submittal ZIP next to the output folder. For a browser UI instead,
run: python webapp.py
"""

import argparse
import os
import sys

from crawler import load_manufacturers, make_zip, process_materials


def load_materials(path):
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    print("No input file provided.")
    print("- Create a text file with one product per line and pass it next time, or")
    print("- Type product names manually, one per line, type 'done' when finished")
    materials = []
    while True:
        item = input("> ").strip()
        if item.lower() == "done":
            break
        if item:
            materials.append(item)
    return materials


def main():
    ap = argparse.ArgumentParser(description="Download SDS/MSDS + PDS/TDS submittal packages.")
    ap.add_argument("input", nargs="?", help="text file, one product per line")
    ap.add_argument("--country", default="CA", choices=["CA", "US", "ALL"],
                    help="manufacturer country preference (default: CA)")
    ap.add_argument("--manufacturer", default=None,
                    help="only check this manufacturer's own site, e.g. --manufacturer Sika. "
                         "A product line can also name its maker directly: 'Sika: Sikaflex-1A'. "
                         "When no manufacturer is identified and no maker's site matches, "
                         "the product is reported as NOT FOUND, not guessed.")
    ap.add_argument("--out", default="MSDS", help="output folder (default: MSDS)")
    ap.add_argument("--no-msds", action="store_true", help="skip SDS/MSDS")
    ap.add_argument("--no-pds", action="store_true", help="skip PDS/TDS")
    ap.add_argument("--no-zip", action="store_true", help="skip the submittal ZIP")
    args = ap.parse_args()
    materials = load_materials(args.input)
    if not materials:
        print("No products given.")
        return 1
    manufacturers = load_manufacturers(country=args.country)
    msds, pds = process_materials(
        materials, manufacturers, args.out,
        want_msds=not args.no_msds, want_pds=not args.no_pds,
        progress=lambda m: print(m), manufacturer_filter=args.manufacturer)
    found = sum(1 for r in msds + pds if r["Downloaded"])
    print(f"\nDone! {found} of {len(msds) + len(pds)} documents found and validated.")
    if not args.no_zip:
        zip_path = f"{args.out.rstrip('/')}.zip"
        make_zip(args.out, zip_path)
        print(f"Submittal ZIP: {zip_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
