import os
import pdfplumber
from docx import Document


def extract_text(file_path):

    extension = os.path.splitext(file_path)[1].lower()

    if extension == ".pdf":
        return extract_pdf(file_path)

    elif extension == ".docx":
        return extract_docx(file_path)

    elif extension == ".txt":
        return extract_txt(file_path)

    else:
        return "Unsupported file format."


def extract_pdf(file_path):

    text = ""

    with pdfplumber.open(file_path) as pdf:

        for page in pdf.pages:

            page_text = page.extract_text()

            if page_text:
                text += page_text + "\n"

    return text


def extract_docx(file_path):

    doc = Document(file_path)

    text = ""

    for paragraph in doc.paragraphs:
        text += paragraph.text + "\n"

    return text


def extract_txt(file_path):

    with open(file_path, "r", encoding="utf-8") as file:
        return file.read()