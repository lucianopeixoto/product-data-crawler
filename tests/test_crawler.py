"""Offline tests for crawler v2. No network: search/download are faked."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from crawler import (clean_name, filename_safe, is_pdf_bytes,
                     load_manufacturers, make_zip, manufacturer_for_url)

MANUS = [{"name": "Soprema", "country": "CA", "domains": ["soprema.ca"]},
         {"name": "IKO", "country": "CA", "domains": ["iko.com"]}]
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


class TestManufacturersFile(unittest.TestCase):
    def test_loads_and_defaults_to_canada(self):
        path = os.path.join(os.path.dirname(__file__), "..", "manufacturers.json")
        manus = load_manufacturers(path)
        names = [m["name"] for m in manus]
        self.assertIn("Soprema", names)
        self.assertIn("IKO", names)
        self.assertTrue(all(m.get("domains") for m in manus))


class TestZip(unittest.TestCase):
    def test_zip_contains_indexes(self):
        import tempfile
        from crawler import export
        with tempfile.TemporaryDirectory() as d:
            export([{"Index": "01", "Material": "Test", "Manufacturer": "Soprema",
                     "FileName": "01 - Test MSDS.pdf", "URL": "https://x/y.pdf",
                     "Downloaded": True, "Status": "ok", "SizeKB": 10}], os.path.join(d, "lists"), "msds_index")
            zp = os.path.join(d, "out.zip")
            make_zip(d, zp)
            import zipfile
            names = zipfile.ZipFile(zp).namelist()
            self.assertIn("lists/msds_index.csv", names)
            self.assertIn("lists/msds_index.xml", names)


class TestProcessWithFakes(unittest.TestCase):
    def test_invalid_candidate_is_skipped_not_saved(self):
        import tempfile
        from crawler import download_pdf, process_materials

        class FakeResp:
            def __init__(self, data, ctype="application/pdf"):
                self.status_code, self._data = 200, data
                self.headers = {"Content-Type": ctype}
            def iter_content(self, n):
                yield self._data

        class FakeSession:
            def get(self, url, **kw):
                if "bad.pdf" in url:
                    return FakeResp(HTML_PAGE, "text/html")
                return FakeResp(REAL_PDF)

        import tempfile
        with tempfile.TemporaryDirectory() as d:
            ok, status, size = download_pdf("https://x/bad.pdf", os.path.join(d, "bad.pdf"), FakeSession())
            self.assertFalse(ok)
            self.assertFalse(os.path.exists(os.path.join(d, "bad.pdf")))
            ok, status, size = download_pdf("https://x/good.pdf", os.path.join(d, "good.pdf"), FakeSession())
            self.assertTrue(ok)
            self.assertTrue(os.path.exists(os.path.join(d, "good.pdf")))

        # End-to-end with faked search: first candidate HTML, second real PDF
        with tempfile.TemporaryDirectory() as d:
            with patch("crawler.search_candidates", return_value=[
                    ("https://soprema.ca/bad.pdf", "Soprema"),
                    ("https://soprema.ca/good.pdf", "Soprema")]), \
                 patch("crawler.requests.Session", return_value=FakeSession()):
                # download_pdf uses the session passed in; process_materials
                # creates its own session, so patch Session to return fakes
                # via a wrapper: FakeSession.get handles both URLs by name
                msds, pds = process_materials(["Test Product"], MANUS, d, want_pds=False)
                self.assertTrue(msds[0]["Downloaded"])
                self.assertEqual(msds[0]["Manufacturer"], "Soprema")
                self.assertTrue(os.path.exists(os.path.join(d, "MSDS", msds[0]["FileName"])))


if __name__ == "__main__":
    unittest.main()
