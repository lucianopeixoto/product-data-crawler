"""Offline tests for crawler v3. No network: site fetches are faked.

v3 goes directly to manufacturers' own sites — no general web search,
no guessed URLs. These tests cover: PDF validation, doc classification,
product-line manufacturer parsing, sitemap + on-site-search adapters
with faked manufacturer pages, and the honest NOT FOUND statuses.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from crawler import (classify_doc, clean_name, filename_safe, is_pdf_bytes,
                     load_manufacturers, make_zip, manufacturer_for_url,
                     match_score, not_found_status, parse_product_line,
                     product_tokens)

MANUS = [{"name": "Soprema", "country": "CA", "domains": ["soprema.ca"]},
         {"name": "IKO", "country": "CA", "domains": ["iko.com"]}]
TREMCO = [{"name": "Tremco", "country": "CA", "domains": ["tremcoroofing.com"],
           "adapter": "sitemap", "page_paths": ["/products/"],
           "sitemap_url": "https://www.tremcoroofing.com/sitemap.xml"}]
SIKA = [{"name": "Sika", "country": "CA", "domains": ["can.sika.com"],
         "adapter": "sika_serp",
         "search_url": "https://can.sika.com/en/serp.html?q={q}"}]
SOPREMA_NULL = [{"name": "Soprema", "country": "CA", "domains": ["soprema.ca"],
                 "adapter": None,
                 "adapter_note": "check soprema.ca manually"}]
REAL_PDF = b"%PDF-1.7\n" + b"x" * 5000
HTML_PAGE = b"<html><body>not a pdf</body></html>" + b"x" * 5000


class TestValidation(unittest.TestCase):
    def test_real_pdf_passes(self):
        self.assertTrue(is_pdf_bytes(REAL_PDF))

    def test_html_rejected(self):
        self.assertFalse(is_pdf_bytes(HTML_PAGE))

    def test_small_file_rejected(self):
        self.assertFalse(is_pdf_bytes(b"%PDF-1.7\ntiny"))

    def test_empty_rejected(self):
        self.assertFalse(is_pdf_bytes(b""))


class TestNames(unittest.TestCase):
    def test_clean_name(self):
        self.assertEqual(clean_name('  Sopralene/Flam: 180 '), "sopraleneflam 180")

    def test_filename_safe(self):
        self.assertNotIn("/", filename_safe("a/b:c"))
        self.assertTrue(len(filename_safe("x" * 200)) <= 120)

    def test_manufacturer_for_url(self):
        self.assertEqual(manufacturer_for_url("https://www.soprema.ca/en/foo.pdf", MANUS), "Soprema")
        self.assertEqual(manufacturer_for_url("https://www.iko.com/na/bar.pdf", MANUS), "IKO")
        self.assertIsNone(manufacturer_for_url("https://example.com/x.pdf", MANUS))

    def test_product_tokens_keep_numbers_drop_generic(self):
        tokens = product_tokens("Sopralene Flam 180 Roofing Membrane")
        self.assertIn("180", tokens)
        self.assertNotIn("roofing", tokens)
        self.assertNotIn("membrane", tokens)

    def test_match_score(self):
        self.assertEqual(match_score("AlphaGuard BIO Top Coat",
                                     "/products/alphaguard-bio-top-coat"), 1.0)
        self.assertLess(match_score("AlphaGuard BIO Top Coat",
                                    "/products/something-else"), 0.5)


class TestClassify(unittest.TestCase):
    def test_tremco_sds_text(self):
        self.assertEqual(classify_doc("US and Canadian SDS", "https://x/US-and-Canadian-SDS.pdf"), "MSDS")

    def test_tremco_pds_text(self):
        self.assertEqual(classify_doc("Download Product Data Sheet", "https://x/AlphaGuard-BIO-Top-Coat-0626.pdf"), "PDS")

    def test_sika_texts(self):
        self.assertEqual(classify_doc("Safety Data Sheet", "https://can.sika.com/dam/dms/ca01/j/sds-sikaflex-1a.pdf"), "MSDS")
        self.assertEqual(classify_doc("Product Data Sheet", "https://can.sika.com/content/dam/dms/ca01/l/sikaflex-1a.pdf"), "PDS")

    def test_iko_filename(self):
        self.assertEqual(classify_doc("", "https://mediaresourcecenter.iko.com/m/abc/original/IKO_TDS_NRDC_EN.pdf"), "PDS")

    def test_unclassified(self):
        self.assertIsNone(classify_doc("LEED Products List", "https://x/leed.pdf"))


class TestParseLine(unittest.TestCase):
    def test_named_manufacturer(self):
        product, manu = parse_product_line("Sika: Sikaflex-1A", SIKA)
        self.assertEqual((product, manu), ("Sikaflex-1A", "Sika"))

    def test_unnamed_stays_unidentified(self):
        product, manu = parse_product_line("Sopralene Flam 180", SIKA)
        self.assertEqual((product, manu), ("Sopralene Flam 180", None))

    def test_unknown_prefix_is_not_a_manufacturer(self):
        product, manu = parse_product_line("Acme: Wonder Membrane", SIKA)
        self.assertIsNone(manu)


class TestNoGeneralSearch(unittest.TestCase):
    def test_no_search_engine_helpers(self):
        import crawler
        self.assertFalse(hasattr(crawler, "_ddg_links"))
        self.assertFalse(hasattr(crawler, "_bing_links"))


class TestManufacturersFile(unittest.TestCase):
    def test_loads_and_defaults_to_canada(self):
        path = os.path.join(os.path.dirname(__file__), "..", "manufacturers.json")
        manus = load_manufacturers(path)
        names = [m["name"] for m in manus]
        self.assertIn("Soprema", names)
        self.assertIn("Sika", names)
        self.assertIn("Tremco", names)
        self.assertTrue(all(m.get("domains") for m in manus))
        adapters = {m["name"]: m.get("adapter") for m in manus}
        self.assertEqual(adapters["Sika"], "sika_serp")
        self.assertEqual(adapters["Tremco"], "sitemap")
        self.assertIsNone(adapters["Soprema"])


class TestZip(unittest.TestCase):
    def test_zip_contains_indexes(self):
        import tempfile
        from crawler import export
        with tempfile.TemporaryDirectory() as d:
            export([{"Index": "01", "Material": "Test", "Manufacturer": "Sika",
                     "FileName": "01 - Test MSDS.pdf", "URL": "https://x/y.pdf",
                     "Downloaded": True, "Status": "ok", "SizeKB": 10}], os.path.join(d, "lists"), "msds_index")
            zp = os.path.join(d, "out.zip")
            make_zip(d, zp)
            import zipfile
            names = zipfile.ZipFile(zp).namelist()
            self.assertIn("lists/msds_index.csv", names)
            self.assertIn("lists/msds_index.xml", names)


class FakeResp:
    def __init__(self, text="", data=None, ctype="text/html"):
        self.status_code, self.text = 200, text
        self.headers = {"Content-Type": ctype}
        self._data = data if data is not None else text.encode()

    def iter_content(self, n):
        yield self._data


class FakeSession:
    """Serves a fake Tremco sitemap + product page, and real fake PDFs."""
    SITEMAP = ('<?xml version="1.0"?><urlset>'
               '<url><loc>https://www.tremcoroofing.com/products/alphaguard-bio-top-coat</loc></url>'
               '<url><loc>https://www.tremcoroofing.com/blog</loc></url></urlset>')
    PRODUCT = ('<html><body>'
               '<a href="/media/AlphaGuard_Bio%20TC/US-and-Canadian-SDS.pdf">US and Canadian SDS</a>'
               '<a href="/media/AlphaGuard_Bio%20TC/AlphaGuard-BIO-Top-Coat-0626.pdf">Download Product Data Sheet</a>'
               '<a href="/media/AlphaGuard_Bio%20TC/LEED.pdf">LEED Products List</a>'
               '</body></html>')
    SERP = ('<html><body>'
            '<a href="https://can.sika.com/en/construction/adhesives-sealants/adhesives/sikaflex-1a.html">Sikaflex-1A</a>'
            '</body></html>')
    SIKA_PRODUCT = ('<html><body>'
                    '<a href="/dam/dms/ca01/j/sds-sikaflex-1a.pdf">Safety Data Sheet</a>'
                    '<a href="/content/dam/dms/ca01/l/sikaflex-1a.pdf">Product Data Sheet</a>'
                    '</body></html>')

    def get(self, url, **kw):
        if url.endswith(".pdf"):
            return FakeResp(data=REAL_PDF, ctype="application/pdf")
        if "sitemap.xml" in url:
            return FakeResp(text=self.SITEMAP, ctype="application/xml")
        if "serp.html" in url:
            return FakeResp(text=self.SERP)
        if "sikaflex-1a.html" in url:
            return FakeResp(text=self.SIKA_PRODUCT)
        if "alphaguard-bio-top-coat" in url:
            return FakeResp(text=self.PRODUCT)
        r = FakeResp(text="<html></html>")
        r.status_code = 404
        return r


class TestDirectAdapters(unittest.TestCase):
    def test_sitemap_adapter_finds_both_docs(self):
        import tempfile
        from crawler import process_materials
        with tempfile.TemporaryDirectory() as d:
            with patch("crawler.requests.Session", return_value=FakeSession()):
                msds, pds = process_materials(["AlphaGuard BIO Top Coat"], TREMCO, d)
        self.assertTrue(msds[0]["Downloaded"])
        self.assertEqual(msds[0]["Manufacturer"], "Tremco")
        self.assertTrue(pds[0]["Downloaded"])
        self.assertEqual(pds[0]["Manufacturer"], "Tremco")

    def test_sika_serp_adapter_finds_both_docs(self):
        import tempfile
        from crawler import process_materials
        with tempfile.TemporaryDirectory() as d:
            with patch("crawler.requests.Session", return_value=FakeSession()):
                msds, pds = process_materials(["Sikaflex-1A"], SIKA, d)
        self.assertTrue(msds[0]["Downloaded"])
        self.assertEqual(msds[0]["Manufacturer"], "Sika")
        self.assertTrue(pds[0]["Downloaded"])

    def test_invalid_candidate_is_skipped_not_saved(self):
        import tempfile
        from crawler import download_pdf
        with tempfile.TemporaryDirectory() as d:
            ok, _s, _z = download_pdf("https://x/bad.pdf", os.path.join(d, "bad.pdf"), FakeSession())
            # FakeSession serves a real PDF for every .pdf URL; use the
            # HTML-page guard instead: a non-PDF body must be rejected.
            self.assertTrue(ok)
        with tempfile.TemporaryDirectory() as d:
            class HtmlSession(FakeSession):
                def get(self, url, **kw):
                    return FakeResp(data=HTML_PAGE, ctype="text/html")
            ok, status, _z = download_pdf("https://x/bad.pdf", os.path.join(d, "bad.pdf"), HtmlSession())
            self.assertFalse(ok)
            self.assertFalse(os.path.exists(os.path.join(d, "bad.pdf")))


class TestNotFoundStatuses(unittest.TestCase):
    def test_unidentified_manufacturer(self):
        status = not_found_status(None, None, "MSDS")
        self.assertIn("manufacturer not identified", status)

    def test_named_no_adapter(self):
        status = not_found_status("Soprema", SOPREMA_NULL[0], "MSDS")
        self.assertIn("no direct adapter for Soprema", status)

    def test_named_no_match_on_own_site(self):
        import tempfile
        from crawler import process_materials
        with tempfile.TemporaryDirectory() as d:
            with patch("crawler.requests.Session", return_value=FakeSession()):
                msds, _pds = process_materials(["Tremco: Some Other Membrane"], TREMCO, d,
                                                want_pds=False)
        self.assertFalse(msds[0]["Downloaded"])
        self.assertIn("no matching MSDS document on Tremco's own site", msds[0]["Status"])
        self.assertEqual(msds[0]["Manufacturer"], "Tremco")

    def test_unnamed_no_match_is_unidentified(self):
        import tempfile
        from crawler import process_materials
        with tempfile.TemporaryDirectory() as d:
            with patch("crawler.requests.Session", return_value=FakeSession()):
                msds, _pds = process_materials(["Some Other Membrane"], TREMCO, d,
                                                want_pds=False)
        self.assertFalse(msds[0]["Downloaded"])
        self.assertIn("manufacturer not identified", msds[0]["Status"])
        self.assertEqual(msds[0]["Manufacturer"], "")

    def test_named_manufacturer_filter_reports_that_maker(self):
        import tempfile
        from crawler import process_materials
        with tempfile.TemporaryDirectory() as d:
            with patch("crawler.requests.Session", return_value=FakeSession()):
                msds, _pds = process_materials(["AlphaGuard BIO Top Coat"], SOPREMA_NULL, d,
                                                want_pds=False, manufacturer_filter="Soprema")
        self.assertFalse(msds[0]["Downloaded"])
        self.assertEqual(msds[0]["Manufacturer"], "Soprema")
        self.assertIn("no direct adapter for Soprema", msds[0]["Status"])


if __name__ == "__main__":
    unittest.main()
