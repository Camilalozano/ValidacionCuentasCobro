import io
import json
import re
import sys

from pypdf import PdfReader
from .models import Page
from .pdf import MAX_BYTES, MAX_PAGES, MAX_OCR_PAGES, ocr_page
from dataclasses import asdict


def extract(data, ocr=True):
    reader = PdfReader(io.BytesIO(data), strict=False)
    if reader.is_encrypted:
        return {"error": "El PDF está protegido. Cargue una copia sin contraseña."}
    if not 0 < len(reader.pages) <= MAX_PAGES:
        return {"error": "El PDF debe contener entre 1 y 100 páginas."}
    pages = []
    ocr_count = total_chars = 0
    for i, pdf_page in enumerate(reader.pages, 1):
        if pdf_page.get("/Contents") is None:
            text = layout = ""
        else:
            text = pdf_page.extract_text() or ""
            layout = pdf_page.extract_text(extraction_mode="layout") or text
        page = Page(i, text[:60000], layout[:120000])
        if len(re.findall(r"[a-zA-Z0-9]", text)) < 90:
            page.issue = "Texto escaso: puede ser una imagen, una página de firmas o una página vacía."
            if ocr and ocr_count < MAX_OCR_PAGES:
                ocr_count += 1
                try:
                    scanned, issue = ocr_page(data, i)
                    if len(scanned.strip()) > len(text.strip()):
                        page.text = scanned[:60000]; page.layout = scanned[:120000]; page.method = "OCR"
                    page.issue = issue or ("Extracción OCR: contraste los campos con la imagen." if scanned.strip() else page.issue)
                except Exception:
                    page.issue = "OCR incompleto. Revise visualmente esta página."
            elif ocr:
                page.issue = "Se alcanzó el límite de 15 páginas OCR. Esta página requiere revisión visual."
        if len(text) > 60000 or len(layout) > 120000:
            page.issue = "Página truncada por exceso de texto. No se ha revisado íntegramente."
        total_chars += len(page.text) + len(page.layout)
        if total_chars > 4_000_000:
            return {"error": "El PDF contiene demasiado texto para una revisión. Divida el expediente."}
        pages.append(asdict(page))
    return {"pages": pages}


if __name__ == "__main__":
    try:
        data = sys.stdin.buffer.read(MAX_BYTES + 1)
        payload = extract(data, len(sys.argv) > 1 and sys.argv[1] == "ocr") if len(data) <= MAX_BYTES else {"error":"El PDF supera 40 MB."}
    except Exception:
        payload = {"error": "PDF ilegible, incompleto o no compatible. Intente exportarlo nuevamente."}
    sys.stdout.buffer.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
