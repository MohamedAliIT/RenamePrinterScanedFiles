import pytesseract
import re
from PIL import Image

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

img = Image.open(r"E:\rename_scans\input\test.jpg")

text = pytesseract.image_to_string(img, lang="ara+eng")

# تنظيف النص
cleaned_text = re.sub(r"[^\w\s\u0600-\u06FF]", " ", text)  # إزالة الرموز الغريبة
cleaned_text = re.sub(r"\s+", " ", cleaned_text)

print("---- RAW OCR ----")
print(text)

print("\n---- CLEANED ----")
print(cleaned_text)
