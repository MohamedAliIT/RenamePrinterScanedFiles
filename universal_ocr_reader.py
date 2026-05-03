import re
from pathlib import Path
from datetime import datetime

import pytesseract
from PIL import Image
from pdf2image import convert_from_path
from docx import Document
from pdfminer.high_level import extract_text as pdfminer_extract


# ==============================
# CONFIG
# ==============================

BASE_DIR = Path(r"E:\rename_scans")
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
OCR_LANG = "ara+eng"


# ==============================
# TEXT CLEANING
# ==============================

def clean_text(text: str) -> str:
    text = re.sub(r"[^\w\s\u0600-\u06FF]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# ==============================
# DATE EXTRACTION
# ==============================

def extract_date(text: str):
    patterns = [
        r"\d{2}/\d{2}/\d{4}",
        r"\d{4}-\d{2}-\d{2}",
        r"\d{2}-\d{2}-\d{4}",
    ]

    for p in patterns:
        m = re.search(p, text)
        if not m:
            continue

        s = m.group()
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
            try:
                dt = datetime.strptime(s, fmt)
                return dt.strftime("%Y-%m-%d")
            except:
                continue

    return None


# ==============================
# TITLE EXTRACTION (GENERIC)
# ==============================

def guess_document_title(text: str) -> str:
    lines = text.splitlines()

    for line in lines:
        line = line.strip()

        # تجاهل الأسطر القصيرة جداً
        if len(line) < 5:
            continue

        # تجاهل الأسطر التي تحتوي فقط أرقام
        if re.fullmatch(r"[\d\s]+", line):
            continue

        # تنظيف إضافي
        line = re.sub(r"[^\w\s\u0600-\u06FF]", " ", line)
        line = re.sub(r"\s+", " ", line).strip()

        words = line.split()

        # تجاهل الكلمات القصيرة جداً (ضوضاء OCR)
        words = [w for w in words if len(w) >= 2]

        if len(words) >= 2:
            title = "_".join(words[:4])
            return title

    return "Document"


# ==============================
# SAFE FILENAME BUILDER
# ==============================

def build_filename(date, title, suffix):
    if date:
        name = f"{date}_{title}"
    else:
        name = title

    name = re.sub(r"[<>:\"/\\|?*]", "", name)
    name = re.sub(r"\s+", "_", name)
    name = name.strip("_")

    return name[:150] + suffix.lower()


# ==============================
# FILE READERS
# ==============================

def read_image(path: Path) -> str:
    img = Image.open(path)
    return pytesseract.image_to_string(
        img,
        lang=OCR_LANG,
        config="--oem 3 --psm 6"
    )


def read_pdf(path: Path) -> str:
    try:
        text = pdfminer_extract(str(path))
        if text and len(text.strip()) > 30:
            return text
    except:
        pass

    pages = convert_from_path(str(path), dpi=300)
    full_text = ""

    for page in pages:
        full_text += pytesseract.image_to_string(
            page,
            lang=OCR_LANG,
            config="--oem 3 --psm 6"
        )

    return full_text


def read_docx(path: Path) -> str:
    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs)


def extract_text(path: Path) -> str:
    ext = path.suffix.lower()

    if ext in [".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"]:
        return read_image(path)

    elif ext == ".pdf":
        return read_pdf(path)

    elif ext == ".docx":
        return read_docx(path)

    return ""


# ==============================
# MAIN
# ==============================

def main():
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

        cleaned = clean_text(raw_text)

        date = extract_date(cleaned)
        title = guess_document_title(cleaned)

        new_name = build_filename(date, title, file.suffix)
        target = OUTPUT_DIR / new_name

        counter = 1
        while target.exists():
            alt_name = build_filename(date, f"{title}_{counter}", file.suffix)
            target = OUTPUT_DIR / alt_name
            counter += 1

        file.rename(target)
        print(f"  -> Renamed to: {target.name}")


if __name__ == "__main__":
    main()
