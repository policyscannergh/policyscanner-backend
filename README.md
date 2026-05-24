# PolicyScanner — Backend

Flask API that extracts structured data from UK home insurance documents — policy schedules, IPIDs, renewal letters, full policy wordings. Returns sums insured, excesses, endorsements, exclusions and cover details as JSON so the frontend can compare on **cover**, not just price.

Powers [policyscanner.co.uk](https://policyscanner.co.uk).

## Stack

- **Flask** + **gunicorn** (Python 3.12 in production)
- **Anthropic Claude** `claude-opus-4-7` with prompt caching on the system + schema prefix
- **pdfplumber** for native PDF text extraction
- **pytesseract** + **poppler** for OCR fallback on scanned PDFs
- **Docker** for deploy (Railway)

## Endpoints

| Method | Path      | Purpose                                                                       |
| ------ | --------- | ----------------------------------------------------------------------------- |
| `GET`  | `/`       | Status check                                                                  |
| `GET`  | `/health` | Liveness + active model name                                                  |
| `POST` | `/upload` | Multipart `file` upload (PDF / PNG / JPG / WEBP / TXT). Returns parsed cover. |

`/upload` enforces a 15 MB file cap and trims extracted text to 60k chars before the model call.

## Response shape

```jsonc
{
  "success": true,
  "extracted_text_preview": "...",
  "parsed": {
    "policy":       { "insurer": "...", "policy_number": "...", "annual_premium_gbp": 412.50, ... },
    "property":     { "address": "...", "postcode": "...", "property_type": "...", ... },
    "cover":        { "buildings": {...}, "contents": {...}, "personal_possessions": {...}, ... },
    "excesses":     { "buildings_compulsory_gbp": 100, "subsidence_gbp": 1000, ... },
    "endorsements": ["..."],
    "exclusions":   ["..."],
    "missing_information": ["..."],
    "raw_summary":  "Plain-English summary"
  }
}
```

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in ANTHROPIC_API_KEY
python app.py
```

App runs on `http://localhost:5000`. OCR fallback needs `tesseract` and `poppler` on the host — the provided `Dockerfile` installs both.

## Deploy (Railway)

1. Push to GitHub.
2. Railway → New Project → Deploy from GitHub → pick this repo.
3. Railway auto-detects the `Dockerfile` (gives us tesseract + poppler).
4. Add env var `ANTHROPIC_API_KEY`.
5. Railway exposes a public URL — note it for the frontend's `NEXT_PUBLIC_API_URL`.

## Why

Comparison sites optimise for price. Cover gets quietly trimmed — lower sums insured, missing accidental damage, higher excesses, sneaky exclusions. PolicyScanner pulls the cover out of your documents in plain English so you can compare like-for-like.
