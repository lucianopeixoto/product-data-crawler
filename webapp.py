"""Simple web interface for Product Data Crawler v2 (stdlib only).

Run:  python webapp.py            # http://127.0.0.1:8000
      python webapp.py --port 8080 --host 0.0.0.0

Flow: paste products (one per line) -> choose SDS and/or PDS and the
country -> the server searches the web, validates every PDF, and builds
a submittal ZIP you can download, plus CSV/XML indexes inside it.

The CLI (msds-crawler.py) is still there for scripts and large lists;
this UI is for contractors who just want a package without a terminal.
Jobs are kept under jobs/<job-id>/ in the working directory. Keep lists
modest in the browser (under ~20 products); the CLI has no such limit.
"""

import argparse
import html
import os
import re
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from crawler import load_manufacturers, make_zip, process_materials

JOBS_DIR = "jobs"
JOBS = {}  # job_id -> dict(status, message, zip, msds, pds)


def safe_job_id(job_id):
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", job_id or ""))


PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Product Data Crawler — Submittal Packages</title>
<style>body{font-family:system-ui,sans-serif;max-width:760px;margin:2rem auto;padding:0 1rem;color:#222}
h1{font-size:1.6rem} textarea{width:100%;height:220px} button{padding:.6rem 1.4rem;font-size:1rem}
.muted{color:#666} .ok{color:#0a7a2f} .bad{color:#b00} table{border-collapse:collapse} td,th{border:1px solid #ccc;padding:.3rem .6rem;text-align:left}</style>
</head><body>
<h1>Product Data Crawler</h1>
<p class="muted">Paste products, one per line. The tool searches manufacturer sites first
(Canada by default, configurable), checks every PDF is real before saving it,
and bundles everything into a downloadable submittal ZIP.</p>
<form method="post" action="/run">
<p><label>Products (one per line):<br><textarea name="products" placeholder="Sopralene Flam 180&#10;Colphene 3000&#10;Duotack"></textarea></label></p>
<p><label><input type="checkbox" name="msds" checked> Safety Data Sheets (SDS/MSDS)</label>
&nbsp;<label><input type="checkbox" name="pds" checked> Product Data Sheets (PDS/TDS)</label></p>
<p><label>Country preference:
<select name="country"><option value="CA" selected>Canada</option><option value="US">United States</option><option value="ALL">All countries</option></select></label></p>
<p><button type="submit">Search &amp; build submittal ZIP</button></p>
</form>
<p class="muted">Tip: for large lists, use the command line instead: <code>python msds-crawler.py materials.txt</code></p>
</body></html>"""


def job_page(job):
    rows = ""
    for rec in (job.get("msds") or []) + (job.get("pds") or []):
        cls = "ok" if rec["Downloaded"] else "bad"
        rows += (f"<tr><td>{html.escape(str(rec['Index']))}</td><td>{html.escape(rec['Material'])}</td>"
                 f"<td>{html.escape(rec['Manufacturer'])}</td><td>{html.escape(rec['FileName'])}</td>"
                 f"<td class='{cls}'>{html.escape(rec['Status'])}</td></tr>")
    dl = (f'<p><a href="/download/{job["id"]}.zip"><strong>Download submittal ZIP</strong></a></p>'
          if job.get("zip") else "")
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Job {job['id']}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem}}
table{{border-collapse:collapse}} td,th{{border:1px solid #ccc;padding:.3rem .6rem;text-align:left}}
.ok{{color:#0a7a2f}} .bad{{color:#b00}}</style></head><body>
<h1>Submittal job {html.escape(job['id'])}</h1><p>Status: <strong>{html.escape(job['status'])}</strong> — {html.escape(job.get('message',''))}</p>
{dl}<table><tr><th>#</th><th>Product</th><th>Manufacturer</th><th>File</th><th>Status</th></tr>{rows}</table>
<p><a href="/">Start another package</a></p></body></html>"""


def run_job(job_id, products, want_msds, want_pds, country):
    out_dir = os.path.join(JOBS_DIR, job_id)
    try:
        JOBS[job_id]["status"] = "running"
        manufacturers = load_manufacturers(country=country)
        msds, pds = process_materials(
            products, manufacturers, out_dir, want_msds, want_pds,
            progress=lambda m: JOBS[job_id].update(message=m))
        zip_path = os.path.join(JOBS_DIR, f"{job_id}.zip")
        make_zip(out_dir, zip_path)
        found = sum(1 for r in msds + pds if r["Downloaded"])
        total = len(msds) + len(pds)
        JOBS[job_id].update(status="done", message=f"{found} of {total} documents found and validated.",
                            zip=zip_path, msds=msds, pds=pds)
    except Exception as e:  # never leave a job hanging with no message
        JOBS[job_id].update(status="failed", message=f"{type(e).__name__}: {e}")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, ctype="text/html", status=200):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(PAGE)
        elif self.path.startswith("/job/"):
            job_id = self.path.split("/job/")[1].split("/")[0]
            if job_id in JOBS:
                self._send(job_page(JOBS[job_id]))
            else:
                self._send("Unknown job.", status=404)
        elif self.path.startswith("/download/") and self.path.endswith(".zip"):
            job_id = self.path[len("/download/"):-len(".zip")]
            if not safe_job_id(job_id):
                self._send("Bad job id.", status=400)
                return
            zip_path = os.path.join(JOBS_DIR, f"{job_id}.zip")
            if os.path.exists(zip_path):
                with open(zip_path, "rb") as f:
                    self._send(f.read(), "application/zip")
            else:
                self._send("ZIP not ready yet.", status=404)
        else:
            self._send("Not found.", status=404)

    def do_POST(self):
        if self.path != "/run":
            self._send("Not found.", status=404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        fields = urllib.parse.parse_qs(self.rfile.read(length).decode())
        products = [l.strip() for l in fields.get("products", [""])[0].splitlines() if l.strip()]
        if not products:
            self._send("No products pasted. <a href='/'>Go back</a>", status=400)
            return
        job_id = time.strftime("%Y%m%d-%H%M%S")
        JOBS[job_id] = {"id": job_id, "status": "queued", "message": "Starting…"}
        threading.Thread(target=run_job, args=(
            job_id, products,
            "msds" in fields, "pds" in fields,
            fields.get("country", ["CA"])[0]), daemon=True).start()
        self.send_response(303)
        self.send_header("Location", f"/job/{job_id}")
        self.end_headers()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    os.makedirs(JOBS_DIR, exist_ok=True)
    print(f"Product Data Crawler web UI: http://{args.host}:{args.port}/")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
