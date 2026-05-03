import re
import json
import hashlib
import logging
import argparse
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

import requests
from pdfminer.high_level import extract_text as pdfminer_extract
from pdf2image import convert_from_path
from PIL import Image
import pytesseract
from docx import Document


# ==========================================================
# CONFIGURATION
# ==========================================================

class Config:
    INPUT_DIR: Path = None
    OUTPUT_DIR: Path = None
    REVIEW_DIR: Path = None

    OLLAMA_URL = "http://localhost:11434/api/generate"
    MODEL = "qwen2.5:7b-instruct"

    TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    POPPLER_PATH = r"C:\poppler\Library\bin"

    MAX_TEXT_LENGTH = 5000
    MIN_CONFIDENCE = 0.60


# ==========================================================
# ARGUMENT PARSING (NEW)
# ==========================================================

def parse_arguments():
    parser = argparse.ArgumentParser(
        description="LLM Legal Document Auto Renamer"
    )

    parser.add_argument(
        "--input",
        required=True,
        help="Input directory path (can be local, network drive, or UNC path)"
    )

    parser.add_argument(
        "--output",
        required=False,
        help="Output directory (default: create _renamed inside input)"
    )

    parser.add_argument(
        "--review",
        required=False,
        help="Review directory (default: create _review inside input)"
    )

    args = parser.parse_args()

    input_dir = Path(args.input)

    if not input_dir.exists():
        print("Input path does not exist.")
        sys.exit(1)

    output_dir = Path(args.output) if args.output else input_dir / "_renamed"
    review_dir = Path(args.review) if args.review else input_dir / "_review"

    output_dir.mkdir(parents=True, exist_ok=True)
    review_dir.mkdir(parents=True, exist_ok=True)

    Config.INPUT_DIR = input_dir
    Config.OUTPUT_DIR = output_dir
    Config.REVIEW_DIR = review_dir


# ==========================================================
# INITIALIZATION
# ==========================================================

pytesseract.pytesseract.tesseract_cmd = Config.TESSERACT_PATH

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)


# ==========================================================
# TEXT EXTRACTION
# ==========================================================

def read_pdf(path: Path) -> str:
    try:
        text = pdfminer_extract(str(path))
        if text and len(text.strip()) > 50:
            logging.info(f"{path.name}: direct text extraction OK")
            return text
    except:
        pass

    logging.info(f"{path.name}: using OCR")
    pages = convert_from_path(
        str(path),
        dpi=300,
        poppler_path=Config.POPPLER_PATH
    )

    text = ""
    for page in pages[:2]:
        text += pytesseract.image_to_string(page, lang="ara+eng")

    return text


def read_docx(path: Path) -> str:
    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs)


def read_image(path: Path) -> str:
    img = Image.open(path)
    return pytesseract.image_to_string(img, lang="ara+eng")


def extract_text(path: Path) -> str:
    ext = path.suffix.lower()

    if ext == ".pdf":
        return read_pdf(path)
    if ext == ".docx":
        return read_docx(path)
    if ext in [".jpg", ".jpeg", ".png", ".tif", ".tiff"]:
        return read_image(path)

    return ""


# ==========================================================
# LLM CALL (UNCHANGED LOGIC)
# ==========================================================

def call_llm(text: str) -> Optional[dict]:

    prompt = f"""
You are a professional legal document naming intelligence engine.

Analyze the document and extract structured metadata
to generate a clear, professional filename.

Rules:
- Do NOT invent data.
- Extract only what is clearly present.
- Prefer legally significant names or authorities.
- Extract dates only if explicit and convert to YYYY-MM-DD.
- Ignore generic words.
- If unknown, leave empty.
- Confidence must be between 0.0 and 1.0.

Return STRICT JSON only.

Schema:

{{
  "core_subject": "",
  "primary_party": "",
  "issuing_authority": "",
  "reference_number": "",
  "issue_date": "",
  "jurisdiction": "",
  "confidence": 0.0
}}

Document:
\"\"\"
{text}
\"\"\"
"""

    try:
        response = requests.post(
            Config.OLLAMA_URL,
            json={
                "model": Config.MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1
                }
            },
            timeout=1200
        )

        if response.status_code != 200:
            logging.error(response.text)
            return None

        data = response.json()
        raw = data.get("response", "").strip()

        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return None

        parsed = json.loads(match.group())
        parsed["confidence"] = float(parsed.get("confidence", 0))

        return parsed

    except Exception as e:
        logging.error(f"LLM error: {e}")
        return None


# ==========================================================
# FILENAME GENERATION (UNCHANGED)
# ==========================================================

def clean_text(value: str) -> str:
    if not value:
        return ""
    value = re.sub(r"[^\w\s]", "", value)
    value = re.sub(r"\s+", "_", value)
    return value.strip("_")


def valid_date(date_str: str) -> Optional[str]:
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        if 1990 <= dt.year <= 2035:
            return dt.strftime("%Y_%m_%d")
    except:
        pass
    return None


def generate_filename(metadata: dict, raw_text: str, suffix: str) -> str:

    parts = []

    subject = clean_text(metadata.get("core_subject", ""))
    party = clean_text(metadata.get("primary_party", ""))
    issuer = clean_text(metadata.get("issuing_authority", ""))
    ref = clean_text(metadata.get("reference_number", ""))
    date = valid_date(metadata.get("issue_date", ""))

    if subject:
        parts.append(subject)

    if party:
        parts.append(party)
    elif issuer:
        parts.append(issuer)

    if ref:
        parts.append(ref)

    if date:
        parts.append(date)

    if not parts:
        fallback = clean_text(raw_text[:50])
        fallback_words = fallback.split("_")[:4]
        parts = ["_".join(fallback_words)] if fallback_words else ["Document"]

    fingerprint = hashlib.sha1(raw_text.encode()).hexdigest()[:6]
    parts.append(fingerprint)

    filename = "_".join(parts)
    return filename + suffix.lower()


# ==========================================================
# MAIN PROCESS
# ==========================================================

def main():
    parse_arguments()

    # تأكد أن المجلدات موجودة
    Config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    Config.REVIEW_DIR.mkdir(parents=True, exist_ok=True)

    try:
        files = [f for f in Config.INPUT_DIR.glob("*.*") if f.is_file()]
    except Exception as e:
        logging.error(f"Cannot access input directory: {e}")
        return

    if not files:
        logging.info("No files found.")
        return

    logging.info(f"Found {len(files)} files")

    for file in files:
        try:
            logging.info(f"Processing {file.name}")

            # ===============================
            # Extract Text
            # ===============================
            try:
                raw_text = extract_text(file)
            except Exception as e:
                logging.error(f"Text extraction failed: {e}")
                file.rename(Config.REVIEW_DIR / file.name)
                continue

            if not raw_text or not raw_text.strip():
                logging.warning("No text extracted → review")
                file.rename(Config.REVIEW_DIR / file.name)
                continue

            raw_text = raw_text[:Config.MAX_TEXT_LENGTH]

            # ===============================
            # Call LLM
            # ===============================
            try:
                metadata = call_llm(raw_text)
            except Exception as e:
                logging.error(f"LLM call failed: {e}")
                file.rename(Config.REVIEW_DIR / file.name)
                continue

            if not metadata:
                logging.warning("LLM returned empty result → review")
                file.rename(Config.REVIEW_DIR / file.name)
                continue

            # ===============================
            # Generate Filename
            # ===============================
            confidence = float(metadata.get("confidence", 0))

            try:
                new_name = generate_filename(metadata, raw_text, file.suffix)
            except Exception as e:
                logging.error(f"Filename generation failed: {e}")
                file.rename(Config.REVIEW_DIR / file.name)
                continue

            logging.info(f" → {new_name}")
            logging.info(f" → confidence={confidence}")

            # ===============================
            # Decision
            # ===============================
            target_dir = (
                Config.OUTPUT_DIR
                if confidence >= Config.MIN_CONFIDENCE
                else Config.REVIEW_DIR
            )

            try:
                file.rename(target_dir / new_name)
            except Exception as e:
                logging.error(f"File move failed: {e}")
                continue

        except Exception as e:
            logging.error(f"Unexpected error processing {file.name}: {e}")
            try:
                file.rename(Config.REVIEW_DIR / file.name)
            except Exception:
                pass
            continue


if __name__ == "__main__":
    main()
