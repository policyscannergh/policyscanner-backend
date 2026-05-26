import io
import json
import os
import re
import tempfile

import anthropic
import pdfplumber
import pytesseract
from flask import Flask, jsonify, request
from flask_cors import CORS
from PIL import Image

app = Flask(__name__)

ALLOWED_ORIGINS = [
    "https://policyscanner.co.uk",
    "https://www.policyscanner.co.uk",
    "http://localhost:3000",
    re.compile(r"^https://policyscanner-frontend(-[a-z0-9-]+)?\.vercel\.app$"),
]
CORS(app, resources={r"/*": {"origins": ALLOWED_ORIGINS}})

_anthropic_client: anthropic.Anthropic | None = None


def get_anthropic_client() -> anthropic.Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        _anthropic_client = anthropic.Anthropic(api_key=api_key)
    return _anthropic_client


ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "webp", "txt"}
MAX_FILE_BYTES = 15 * 1024 * 1024
MIN_TEXT_CHARS = 50
MAX_TEXT_CHARS = 60_000
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-7")
MAX_OUTPUT_TOKENS = 16_000


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def extract_text_from_pdf(filepath: str) -> str:
    parts: list[str] = []
    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                parts.append(page_text)
    text = "\n\n".join(parts).strip()

    if len(text) >= MIN_TEXT_CHARS:
        return text

    return ocr_pdf_pages(filepath)


def ocr_pdf_pages(filepath: str) -> str:
    parts: list[str] = []
    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            pil_image = page.to_image(resolution=200).original
            ocr_text = pytesseract.image_to_string(pil_image)
            if ocr_text:
                parts.append(ocr_text)
    return "\n\n".join(parts).strip()


def extract_text_from_image(filepath: str) -> str:
    image = Image.open(filepath)
    return pytesseract.image_to_string(image).strip()


def extract_text_from_txt(filepath: str) -> str:
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        return f.read().strip()


def extract_text(filepath: str, filename: str) -> str:
    ext = filename.rsplit(".", 1)[1].lower()
    if ext == "pdf":
        return extract_text_from_pdf(filepath)
    if ext in {"png", "jpg", "jpeg", "webp"}:
        return extract_text_from_image(filepath)
    if ext == "txt":
        return extract_text_from_txt(filepath)
    return ""


SYSTEM_PROMPT_HEADER = """You are an expert UK home insurance document parser.

Extract structured information from a home insurance renewal schedule, policy schedule, quote, or related document.

Return valid JSON only. No prose, no markdown fences.

Rules:
- Do not invent information. Missing fields must be null. Missing lists must be [].
- Preserve monetary values as numbers in GBP (no currency symbols, no commas).
- Distinguish buildings cover from contents cover.
- Distinguish voluntary and compulsory excesses.
- Capture separate excesses for escape of water, subsidence, accidental damage, and personal possessions if present.
- Capture endorsements and exclusions verbatim where possible.
- Capture specified items and whether they are covered away from home.
- Identify whether the document is buildings-only, contents-only, or combined.
- Add anything you noticed but couldn't categorise to `missing_information` or `assumptions`.
"""

JSON_TEMPLATE = """{
  "policyholder": {"name": null, "date_of_birth": null, "occupation": null, "marital_status": null},
  "policy": {
    "insurer": null, "brand": null, "policy_number": null, "quote_reference": null,
    "document_type": null, "start_date": null, "end_date": null, "renewal_date": null,
    "annual_premium_gbp": null, "monthly_premium_gbp": null, "payment_method": null
  },
  "property": {
    "address": null, "postcode": null, "property_type": null, "bedrooms": null, "bathrooms": null,
    "year_built": null, "construction_type": null, "roof_type": null, "flat_roof_percentage": null,
    "listed_status": null, "ownership_status": null, "occupancy": null, "business_use": null,
    "number_of_adults": null, "number_of_children": null, "smoker": null, "pets": null,
    "security_features": [], "flood_risk_notes": null, "subsidence_notes": null
  },
  "cover": {
    "buildings": {"included": null, "sum_insured_gbp": null, "accidental_damage": null, "no_claims_discount_years": null},
    "contents": {"included": null, "sum_insured_gbp": null, "accidental_damage": null, "no_claims_discount_years": null},
    "personal_possessions": {"included": null, "limit_gbp": null, "away_from_home": null, "specified_items": []},
    "legal_expenses": {"included": null, "limit_gbp": null},
    "home_emergency": {"included": null, "limit_gbp": null},
    "bike_cover": {"included": null, "limit_gbp": null},
    "valuables_limit": null, "single_item_limit_gbp": null, "alternative_accommodation_limit_gbp": null
  },
  "excesses": {
    "buildings_compulsory_gbp": null, "buildings_voluntary_gbp": null,
    "contents_compulsory_gbp": null, "contents_voluntary_gbp": null,
    "escape_of_water_gbp": null, "subsidence_gbp": null,
    "accidental_damage_gbp": null, "personal_possessions_gbp": null
  },
  "claims": [],
  "endorsements": [],
  "exclusions": [],
  "assumptions": [],
  "missing_information": [],
  "raw_summary": null
}"""


CACHED_SYSTEM_PROMPT = (
    SYSTEM_PROMPT_HEADER
    + "\nReturn JSON in this exact structure (same keys, same nesting):\n\n"
    + JSON_TEMPLATE
)


def parse_insurance_document(text: str) -> dict:
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS]

    user_prompt = (
        "Extract all relevant home insurance information from the document text below. "
        "Return only the JSON object — no prose, no markdown fences.\n\n"
        "Document text:\n\n"
        f"{text}"
    )

    response = get_anthropic_client().messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=[
            {
                "type": "text",
                "text": CACHED_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_prompt}],
    )

    content = next(
        (block.text for block in response.content if block.type == "text"),
        "",
    )

    cleaned = _strip_json_fences(content)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {"error": "AI parser did not return valid JSON", "raw_response": content}


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


@app.route("/", methods=["GET"])
def index():
    return jsonify({"status": "PolicyScanner backend running"})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "model": ANTHROPIC_MODEL})


@app.route("/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    uploaded_file = request.files["file"]

    if uploaded_file.filename == "":
        return jsonify({"error": "No selected file"}), 400

    if not allowed_file(uploaded_file.filename):
        return jsonify({"error": "Unsupported file type"}), 400

    blob = uploaded_file.read()
    if len(blob) > MAX_FILE_BYTES:
        return jsonify({"error": "File too large (max 15 MB)"}), 400
    if not blob:
        return jsonify({"error": "Empty file"}), 400

    suffix = "." + uploaded_file.filename.rsplit(".", 1)[1].lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp:
        temp.write(blob)
        temp_path = temp.name

    try:
        extracted_text = extract_text(temp_path, uploaded_file.filename)

        if not extracted_text or len(extracted_text.strip()) < MIN_TEXT_CHARS:
            return (
                jsonify(
                    {
                        "error": "Could not extract enough text from the document. If this is a scanned PDF, try a clearer scan or a text-based PDF.",
                        "extracted_text_preview": (extracted_text or "")[:500],
                    }
                ),
                400,
            )

        parsed_data = parse_insurance_document(extracted_text)

        return jsonify(
            {
                "success": True,
                "extracted_text_preview": extracted_text[:1000],
                "parsed": parsed_data,
            }
        )

    except Exception as e:
        app.logger.exception("upload failed")
        return jsonify({"success": False, "error": str(e)}), 500

    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass


if __name__ == "__main__":
    app.run(debug=True, port=int(os.getenv("PORT", "5000")))
