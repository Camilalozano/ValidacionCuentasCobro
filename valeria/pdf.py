"""Extracción aislada: el contenido del PDF nunca se ejecuta como instrucciones."""
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from .models import Page

MAX_BYTES = 40 * 1024 * 1024
MAX_PAGES = 100
MAX_OCR_PAGES = 15


def read_pdf(data: bytes, ocr=True) -> list[Page]:
    if not data.startswith(b"%PDF-"):
        raise ValueError("El archivo no tiene una cabecera PDF válida.")
    if len(data) > MAX_BYTES:
        raise ValueError("El PDF supera el límite de 40 MB.")
    try:
        run = subprocess.run(
            [sys.executable, "-m", "valeria.pdf_worker", "ocr" if ocr else "text"],
            input=data, capture_output=True, timeout=180,
            cwd=Path(__file__).resolve().parent.parent,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("La lectura superó tres minutos. Divida el expediente o aplique OCR antes de cargarlo.") from exc
    if run.returncode:
        raise ValueError("No fue posible leer el PDF. Revise que esté completo y sin contraseña.")
    payload = json.loads(run.stdout)
    if "error" in payload:
        raise ValueError(payload["error"])
    return [Page(**p) for p in payload["pages"]]


def render_page(data, number, scale=1.5):
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(data)
    try:
        page = doc[number - 1]
        # Evitar imágenes desproporcionadas con páginas de tamaño no habitual.
        scale = min(scale, 2200 / max(page.get_size()))
        bitmap = page.render(scale=scale)
        try:
            image = bitmap.to_pil()
            output = io.BytesIO()
            image.save(output, format="PNG")
            return output.getvalue()
        finally:
            bitmap.close(); page.close()
    finally:
        doc.close()


def ocr_page(data, number):
    binary = shutil.which("tesseract")
    if not binary:
        return "", "OCR no disponible en el servidor. Revise visualmente esta página."
    with tempfile.TemporaryDirectory(prefix="valeria-ocr-") as folder:
        image_path = Path(folder) / "page.png"
        image_path.write_bytes(render_page(data, number, scale=2.5))
        run = subprocess.run([binary, str(image_path), "stdout", "-l", "spa+eng", "--psm", "3"],
                             capture_output=True, timeout=18,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if run.returncode:
            return "", "No se pudo completar OCR en español. Revise visualmente esta página."
        return run.stdout.decode("utf-8", errors="replace"), ""
