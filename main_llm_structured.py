"""
==============================================================
AI LEGAL DOCUMENT AUTO RENAMER
==============================================================

Description:
This script automatically reads legal documents, extracts text,
sends the extracted text to a local LLM model through Ollama,
then generates a clean professional filename based on the
document metadata.

Supported file types:
- PDF
- DOCX
- JPG / JPEG / PNG / TIF / TIFF

Main features:
- Direct text extraction from searchable PDFs
- OCR fallback for scanned PDFs and images
- Local AI metadata extraction using Ollama
- Confidence-based decision system
- Automatic review folder for uncertain files
- Duplicate-safe filenames using SHA1 fingerprint
- Support for local folders and network shared folders

Run example:
python main_llm_structured.py --input "\\192.168.1.10\scan liberal"
"""

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
# This class stores all global configuration values used
# across the script.
# ==========================================================

class Config:
    # These paths will be assigned after reading command-line arguments
    INPUT_DIR: Path = None
    OUTPUT_DIR: Path = None
    REVIEW_DIR: Path = None

    # Ollama local API endpoint
    OLLAMA_URL = "http://localhost:11434/api/generate"

    # Local LLM model name installed in Ollama
    MODEL = "qwen2.5:7b-instruct"

    # Tesseract OCR executable path
    TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

    # Poppler path used to convert PDF pages into images
    POPPLER_PATH = r"C:\poppler\Library\bin"

    # Maximum text length sent to the LLM
    MAX_TEXT_LENGTH = 5000

    # Minimum confidence required to rename automatically
    MIN_CONFIDENCE = 0.60


# ==========================================================
# COMMAND-LINE ARGUMENT PARSING
# ==========================================================
# This function allows the user to pass input, output, and
# review folders when running the script.
# ==========================================================

def parse_arguments():
    """
    Read command-line arguments and prepare input/output folders.

    Arguments:
    --input   Required. Source folder containing documents.
    --output  Optional. Folder for renamed documents.
    --review  Optional. Folder for files that need manual review.
    """

    parser = argparse.ArgumentParser(
        description="AI Legal Document Auto Renamer"
    )

    parser.add_argument(
        "--input",
        required=True,
        help="Input directory path. It can be local, network drive, or UNC path."
    )

    parser.add_argument(
        "--output",
        required=False,
        help="Output directory. Default: create _renamed inside input folder."
    )

    parser.add_argument(
        "--review",
        required=False,
        help="Review directory. Default: create _review inside input folder."
    )

    args = parser.parse_args()

    input_dir = Path(args.input)

    # Stop the script if the input folder does not exist
    if not input_dir.exists():
        print("Input path does not exist.")
        sys.exit(1)

    # If output/review folders are not provided, create them inside input folder
    output_dir = Path(args.output) if args.output else input_dir / "_renamed"
    review_dir = Path(args.review) if args.review else input_dir / "_review"

    # Create folders if they do not already exist
    output_dir.mkdir(parents=True, exist_ok=True)
    review_dir.mkdir(parents=True, exist_ok=True)

    # Store paths in global configuration
    Config.INPUT_DIR = input_dir
    Config.OUTPUT_DIR = output_dir
    Config.REVIEW_DIR = review_dir


# ==========================================================
# INITIALIZATION
# ==========================================================
# Set OCR path and configure logging format.
# ==========================================================

pytesseract.pytesseract.tesseract_cmd = Config.TESSERACT_PATH

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)


# ==========================================================
# PDF TEXT EXTRACTION
# ==========================================================

def read_pdf(path: Path) -> str:
    """
    Extract text from a PDF file.

    Processing strategy:
    1. Try direct text extraction using pdfminer.
       This is faster and better for searchable PDFs.

    2. If direct extraction fails or returns very little text,
       convert PDF pages to images and apply OCR.

    Only the first 2 pages are OCR-processed to reduce time.
    """

    try:
        text = pdfminer_extract(str(path))

        if text and len(text.strip()) > 50:
            logging.info(f"{path.name}: direct PDF text extraction completed")
            return text

    except Exception as e:
        logging.warning(f"{path.name}: direct PDF extraction failed: {e}")

    logging.info(f"{path.name}: using OCR because PDF may be scanned")

    pages = convert_from_path(
        str(path),
        dpi=300,
        poppler_path=Config.POPPLER_PATH
    )

    text = ""

    for page in pages[:2]:
        text += pytesseract.image_to_string(
            page,
            lang="ara+eng"
        )

    return text


# ==========================================================
# DOCX TEXT EXTRACTION
# ==========================================================

def read_docx(path: Path) -> str:
    """
    Extract text from a Microsoft Word DOCX file.

    The function reads all paragraphs and joins them together
    into one text block.
    """

    doc = Document(path)

    return "\n".join(paragraph.text for paragraph in doc.paragraphs)


# ==========================================================
# IMAGE OCR EXTRACTION
# ==========================================================

def read_image(path: Path) -> str:
    """
    Extract text from image files using Tesseract OCR.

    Supported image types:
    JPG, JPEG, PNG, TIF, TIFF
    """

    image = Image.open(path)

    return pytesseract.image_to_string(
        image,
        lang="ara+eng"
    )


# ==========================================================
# FILE TYPE DETECTION
# ==========================================================

def extract_text(path: Path) -> str:
    """
    Detect file type by extension and extract text accordingly.

    Returns empty string if the file type is not supported.
    """

    ext = path.suffix.lower()

    if ext == ".pdf":
        return read_pdf(path)

    if ext == ".docx":
        return read_docx(path)

    if ext in [".jpg", ".jpeg", ".png", ".tif", ".tiff"]:
        return read_image(path)

    return ""


# ==========================================================
# LLM METADATA EXTRACTION
# ==========================================================

def call_llm(text: str) -> Optional[dict]:
    """
    Send extracted document text to the local Ollama LLM.

    The model is instructed to return structured JSON only.

    Expected metadata:
    - core_subject
    - primary_party
    - issuing_authority
    - reference_number
    - issue_date
    - jurisdiction
    - confidence
    """

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
            logging.error(f"LLM API error: {response.text}")
            return None

        data = response.json()

        raw_response = data.get("response", "").strip()

        # Extract JSON object from the model response
        match = re.search(r"\{.*\}", raw_response, re.DOTALL)

        if not match:
            logging.warning("LLM response does not contain valid JSON")
            return None

        parsed = json.loads(match.group())

        # Ensure confidence is always a float value
        parsed["confidence"] = float(parsed.get("confidence", 0))

        return parsed

    except Exception as e:
        logging.error(f"LLM error: {e}")
        return None


# ==========================================================
# TEXT CLEANING FOR FILENAMES
# ==========================================================

def clean_text(value: str) -> str:
    """
    Clean a text value so it can be safely used in a filename.

    This function:
    - Removes special characters
    - Replaces spaces with underscores
    - Removes extra underscores
    """

    if not value:
        return ""

    value = re.sub(r"[^\w\s]", "", value)
    value = re.sub(r"\s+", "_", value)

    return value.strip("_")


# ==========================================================
# DATE VALIDATION
# ==========================================================

def valid_date(date_str: str) -> Optional[str]:
    """
    Validate and format extracted date.

    Expected input format:
    YYYY-MM-DD

    Output format:
    YYYY_MM_DD

    The allowed year range is 1990 to 2035.
    """

    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")

        if 1990 <= dt.year <= 2035:
            return dt.strftime("%Y_%m_%d")

    except Exception:
        pass

    return None


# ==========================================================
# FILENAME GENERATION
# ==========================================================

def generate_filename(metadata: dict, raw_text: str, suffix: str) -> str:
    """
    Generate a professional filename using extracted metadata.

    Filename priority:
    1. Core subject
    2. Primary party
    3. Issuing authority
    4. Reference number
    5. Issue date
    6. Short SHA1 fingerprint

    The fingerprint prevents duplicate filenames.
    """

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

    # Fallback filename if no useful metadata is found
    if not parts:
        fallback = clean_text(raw_text[:50])
        fallback_words = fallback.split("_")[:4]

        if fallback_words:
            parts = ["_".join(fallback_words)]
        else:
            parts = ["Document"]

    # Add a short fingerprint to avoid duplicate filenames
    fingerprint = hashlib.sha1(raw_text.encode()).hexdigest()[:6]
    parts.append(fingerprint)

    filename = "_".join(parts)

    return filename + suffix.lower()


# ==========================================================
# MAIN PROCESS
# ==========================================================

def main():
    """
    Main workflow:

    1. Read command-line arguments
    2. Load files from input folder
    3. Extract text from each file
    4. Send text to LLM for metadata extraction
    5. Generate filename
    6. Move file to:
       - Output folder if confidence is high
       - Review folder if confidence is low or an error happens
    """

    parse_arguments()

    Config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    Config.REVIEW_DIR.mkdir(parents=True, exist_ok=True)

    try:
        files = [
            file for file in Config.INPUT_DIR.glob("*.*")
            if file.is_file()
        ]

    except Exception as e:
        logging.error(f"Cannot access input directory: {e}")
        return

    if not files:
        logging.info("No files found.")
        return

    logging.info(f"Found {len(files)} files")

    for file in files:
        try:
            logging.info(f"Processing file: {file.name}")

            # --------------------------------------------------
            # Step 1: Extract text from the file
            # --------------------------------------------------
            try:
                raw_text = extract_text(file)

            except Exception as e:
                logging.error(f"Text extraction failed: {e}")
                file.rename(Config.REVIEW_DIR / file.name)
                continue

            # If no text is extracted, the file must be reviewed manually
            if not raw_text or not raw_text.strip():
                logging.warning("No text extracted. Moving file to review folder.")
                file.rename(Config.REVIEW_DIR / file.name)
                continue

            # Limit text size before sending it to the LLM
            raw_text = raw_text[:Config.MAX_TEXT_LENGTH]

            # --------------------------------------------------
            # Step 2: Extract structured metadata using LLM
            # --------------------------------------------------
            try:
                metadata = call_llm(raw_text)

            except Exception as e:
                logging.error(f"LLM call failed: {e}")
                file.rename(Config.REVIEW_DIR / file.name)
                continue

            if not metadata:
                logging.warning("LLM returned no valid metadata. Moving file to review folder.")
                file.rename(Config.REVIEW_DIR / file.name)
                continue

            # --------------------------------------------------
            # Step 3: Generate new filename
            # --------------------------------------------------
            confidence = float(metadata.get("confidence", 0))

            try:
                new_name = generate_filename(
                    metadata,
                    raw_text,
                    file.suffix
                )

            except Exception as e:
                logging.error(f"Filename generation failed: {e}")
                file.rename(Config.REVIEW_DIR / file.name)
                continue

            logging.info(f"Generated filename: {new_name}")
            logging.info(f"LLM confidence score: {confidence}")

            # --------------------------------------------------
            # Step 4: Decide final destination
            # --------------------------------------------------
            # High confidence files are renamed automatically.
            # Low confidence files go to manual review.
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
            logging.error(f"Unexpected error while processing {file.name}: {e}")

            # If anything unexpected happens, move the file to review folder
            try:
                file.rename(Config.REVIEW_DIR / file.name)
            except Exception:
                pass

            continue


# ==========================================================
# SCRIPT ENTRY POINT
# ==========================================================
# This ensures the script runs only when executed directly,
# not when imported as a module.
# ==========================================================

if __name__ == "__main__":
    main()