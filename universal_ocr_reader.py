import re
from pathlib import Path
from datetime import datetime

import pytesseract
from PIL import Image
from pdf2image import convert_from_path
from docx import Document
from pdfminer.high_level import extract_text as pdfminer_extract


# ============================================================
# CONFIGURATION
# ============================================================
# This section contains the main paths and OCR settings.
# Change these values according to your local environment.
# ============================================================

BASE_DIR = Path(r"E:\rename_scans")
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"

# Create the output directory if it does not already exist
OUTPUT_DIR.mkdir(exist_ok=True)

# Full path to the Tesseract OCR executable on Windows
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# OCR languages:
# ara = Arabic
# eng = English
OCR_LANG = "ara+eng"


# ============================================================
# TEXT CLEANING
# ============================================================

def clean_text(text: str) -> str:
    """
    Clean extracted text before processing.

    This function removes unnecessary symbols while keeping:
    - Arabic characters
    - English characters
    - Numbers
    - Spaces

    It also replaces multiple spaces with a single space.
    """

    text = re.sub(r"[^\w\s\u0600-\u06FF]", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


# ============================================================
# DATE EXTRACTION
# ============================================================

def extract_date(text: str):
    """
    Search for the first valid date inside the document text.

    Supported date formats:
    - DD/MM/YYYY
    - YYYY-MM-DD
    - DD-MM-YYYY

    The returned format will always be:
    - YYYY-MM-DD
    """

    patterns = [
        r"\d{2}/\d{2}/\d{4}",
        r"\d{4}-\d{2}-\d{2}",
        r"\d{2}-\d{2}-\d{4}",
    ]

    formats = [
        "%d/%m/%Y",
        "%Y-%m-%d",
        "%d-%m-%Y",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if not match:
            continue

        date_string = match.group()

        for date_format in formats:
            try:
                parsed_date = datetime.strptime(date_string, date_format)
                return parsed_date.strftime("%Y-%m-%d")
            except ValueError:
                continue

    return None


# ============================================================
# DOCUMENT TITLE DETECTION
# ============================================================

def guess_document_title(text: str) -> str:
    """
    Guess a simple document title from the extracted text.

    The function scans the document line by line and selects
    the first meaningful line.

    It ignores:
    - Very short lines
    - Lines containing only numbers
    - OCR noise
    - Very short words

    The title is created from the first 4 valid words.
    """

    lines = text.splitlines()

    for line in lines:
        line = line.strip()

        # Ignore very short lines because they are usually not useful
        if len(line) < 5:
            continue

        # Ignore lines that contain only numbers and spaces
        if re.fullmatch(r"[\d\s]+", line):
            continue

        # Remove special characters while keeping Arabic, English, numbers, and spaces
        line = re.sub(r"[^\w\s\u0600-\u06FF]", " ", line)
        line = re.sub(r"\s+", " ", line).strip()

        words = line.split()

        # Remove very short words because they are usually OCR noise
        words = [word for word in words if len(word) >= 2]

        if len(words) >= 2:
            return "_".join(words[:4])

    return "Document"


# ============================================================
# SAFE FILE NAME GENERATION
# ============================================================

def build_filename(date, title, suffix):
    """
    Build a safe filename using the extracted date and title.

    Output examples:
    - 2026-05-21_Court_Judgment.pdf
    - Legal_Notice.pdf

    This function removes characters that are not allowed
    in Windows filenames.
    """

    if date:
        filename = f"{date}_{title}"
    else:
        filename = title

    # Remove invalid Windows filename characters
    filename = re.sub(r"[<>:\"/\\|?*]", "", filename)

    # Replace spaces with underscores
    filename = re.sub(r"\s+", "_", filename)

    # Remove extra underscores from beginning and end
    filename = filename.strip("_")

    # Limit filename length to avoid Windows path issues
    return filename[:150] + suffix.lower()


# ============================================================
# IMAGE TEXT EXTRACTION
# ============================================================

def read_image(path: Path) -> str:
    """
    Extract text from image files using Tesseract OCR.

    Supported image formats:
    - JPG
    - JPEG
    - PNG
    - WEBP
    - TIF
    - TIFF
    """

    image = Image.open(path)

    return pytesseract.image_to_string(
        image,
        lang=OCR_LANG,
        config="--oem 3 --psm 6"
    )


# ============================================================
# PDF TEXT EXTRACTION
# ============================================================

def read_pdf(path: Path) -> str:
    """
    Extract text from a PDF file.

    Step 1:
    Try direct text extraction using pdfminer.
    This works well for searchable PDFs.

    Step 2:
    If the PDF has no readable text, convert pages to images
    and apply OCR page by page.
    """

    try:
        text = pdfminer_extract(str(path))

        # If enough text was extracted, return it directly
        if text and len(text.strip()) > 30:
            return text

    except Exception:
        # Ignore direct extraction errors and continue with OCR
        pass

    # Convert scanned PDF pages into images
    pages = convert_from_path(str(path), dpi=300)

    full_text = ""

    for page in pages:
        page_text = pytesseract.image_to_string(
            page,
            lang=OCR_LANG,
            config="--oem 3 --psm 6"
        )

        full_text += page_text + "\n"

    return full_text


# ============================================================
# DOCX TEXT EXTRACTION
# ============================================================

def read_docx(path: Path) -> str:
    """
    Extract text from a Microsoft Word DOCX file.

    The function reads all paragraphs and joins them into
    one text block.
    """

    document = Document(path)

    return "\n".join(paragraph.text for paragraph in document.paragraphs)


# ============================================================
# FILE TYPE HANDLER
# ============================================================

def extract_text(path: Path) -> str:
    """
    Detect the file type and use the correct extraction method.

    Supported files:
    - Images
    - PDF
    - DOCX

    Unsupported file types return an empty string.
    """

    extension = path.suffix.lower()

    if extension in [".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"]:
        return read_image(path)

    if extension == ".pdf":
        return read_pdf(path)

    if extension == ".docx":
        return read_docx(path)

    return ""


# ============================================================
# MAIN PROCESS
# ============================================================

def main():
    """
    Main workflow:

    1. Read all files from the input folder
    2. Extract text from each file
    3. Clean the extracted text
    4. Try to extract a date
    5. Guess a document title
    6. Generate a safe filename
    7. Move the renamed file to the output folder
    """

    files = list(INPUT_DIR.glob("*.*"))

    if not files:
        print("No files found.")
        return

    for file in files:
        print(f"\nProcessing: {file.name}")

        raw_text = extract_text(file)

        if not raw_text.strip():
            print("  -> No text extracted.")
            continue

        cleaned_text = clean_text(raw_text)

        document_date = extract_date(cleaned_text)
        document_title = guess_document_title(cleaned_text)

        new_filename = build_filename(
            document_date,
            document_title,
            file.suffix
        )

        target_path = OUTPUT_DIR / new_filename

        # If a file with the same name already exists,
        # add a counter to avoid overwriting it.
        counter = 1

        while target_path.exists():
            alternative_filename = build_filename(
                document_date,
                f"{document_title}_{counter}",
                file.suffix
            )

            target_path = OUTPUT_DIR / alternative_filename
            counter += 1

        # Move and rename the file
        file.rename(target_path)

        print(f"  -> Renamed to: {target_path.name}")


# ============================================================
# SCRIPT ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()