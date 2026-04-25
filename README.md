# PolicyScanner Backend

Flask API that extracts structured data from UK home insurance documents.

## Local dev

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in OPENAI_API_KEY
python app.py
```

App runs on http://localhost:5000

## Endpoints

- `GET /` — status check
- `GET /health` — health + active model
- `POST /upload` — multipart form, field name `file`. Returns `{ success, extracted_text_preview, parsed }`.

## Deploy (Railway)

1. Push to GitHub.
2. Railway → New Project → Deploy from GitHub → pick this repo.
3. Railway auto-detects the `Dockerfile` (gives us tesseract + poppler).
4. Add env var `OPENAI_API_KEY`.
5. Railway exposes a public URL — note it for the frontend.
