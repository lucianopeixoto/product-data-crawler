# MSDS Crawler

A Python web crawler that searches, downloads, and organizes Safety Data Sheets (SDS/MSDS/PDS) for a list of materials, with structured PDF naming and CSV/XML indexing.

---

## 🚀 Features

- 🔍 Smart search for SDS/MSDS/PDS PDFs online
- 📄 Automatic download and standardized file naming
- 🧠 Handles inconsistent material naming using multiple search queries
- 📁 Organized output folder (`MSDS/`)
- 📊 Generates structured indexes:
  - `index.csv`
  - `index.xml`
- 🧾 Flexible input methods:
  - Manual entry
  - File input (one material per line)

---

## 📂 Output Structure

MSDS/
│
├── 01 - Material A PDS.pdf
├── 02 - Material B PDS.pdf
├── ...
│
├── index.csv
└── index.xml

---

## 🛠️ Installation

Install dependencies:

pip install requests beautifulsoup4 pandas lxml tqdm

TODO (REVIEW README.MD LATER)

▶️ Usage

Run the script:

python crawler.py
Input Options
1. Manual Input

Enter materials one by one:

> Asphalt Primer
> EPDM Membrane
> done
2. File Input

Provide a .txt file with one material per line:

asphalt primer
epdm membrane
polyiso insulation
🧠 How It Works

For each material, the crawler:

Generates multiple search queries, such as:

"Material SDS PDF"

"Material MSDS PDF"

"Material technical data sheet PDF"

Scrapes search results using DuckDuckGo

Identifies the first valid PDF link

Downloads and renames the file using a standardized format

Logs results into CSV and XML indexes

⚠️ Limitations

Some websites block automated requests

Some documents are behind JavaScript or login portals

The first PDF result may not always be the most accurate

🔧 Future Improvements

Selenium-based browser automation for better compatibility

Manufacturer-specific search optimization

PDF metadata extraction

Web interface for managing and reviewing documents

Integration with estimating or project workflows

📌 Notes

File names are sanitized to remove invalid characters

Files are indexed sequentially (01, 02, 03...)

Materials without a found PDF are still recorded in the index files

📄 License

This project is open-source and free to use.

👷 Use Case

Useful for professionals who need fast access to material documentation:

Construction estimators

Project managers

Safety and compliance teams
