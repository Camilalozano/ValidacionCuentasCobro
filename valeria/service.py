import csv
import hashlib
import io
import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from . import RULESET, VERSION
from .extract import extract_documents
from .models import Review
from .pdf import read_pdf
from .rules import evaluate
from .secop import lookup, compare_with_base


def analyze(data, filename, crp=None, monthly=None, review_date=None, ocr=True, secop_url=None):
    pages = read_pdf(data, ocr=ocr)
    docs = extract_documents(pages)
    now = datetime.now(ZoneInfo("America/Bogota"))
    contract_reference = docs["informe"].get("contract")
    if contract_reference and re.fullmatch(r"\d{1,6}-20\d{2}", contract_reference):
        contract_reference = "ATENEA-" + contract_reference
    base = lookup(secop_url, contract_reference)
    findings = evaluate(docs,pages,crp,monthly,review_date or now.date(), secop=base)
    findings = [f for f in findings if f.rule != "10"] + compare_with_base(docs, base)
    findings.sort(key=lambda f: int(f.rule))
    return Review(filename,hashlib.sha256(data).hexdigest(),now.isoformat(),RULESET,docs,pages,findings,
                  {"crp":crp.name if crp else "No cargada","valor_mensual":monthly.name if monthly else "No cargada",
                   "secop": "Base SECOP · Oracle; " + (base.get("error") or "consulta " + base.get("consulted_at", "")),
                   "version":VERSION,"fecha_revision":str(review_date or now.date())})


def report_text(review):
    lines=["VALERIA · REVISIÓN DE CUENTA DE COBRO",f"Archivo: {review.filename}",
           f"Fecha: {review.reviewed_at}",f"Reglas: {review.ruleset}",
           "Resultado: revisión pendiente. Este reporte no aprueba ni autoriza un pago.",
           f"Referencia CRP: {review.sources['crp']}",f"Referencia valor mensual: {review.sources['valor_mensual']}",""]
    for item in review.findings:
        lines.extend([f"{item.rule}. {item.title} — {item.status} ({item.category})",item.message])
        if item.action: lines.append("Qué revisar: "+item.action)
        for ev in item.evidence:
            label=ev.get("document",ev.get("source","PDF"))
            page_label=", ".join(map(str,ev.get("pages",[ev["page"]] if "page" in ev else [])))
            if page_label: label+=f" · páginas {page_label}"
            lines.append(f"  {label}: {ev.get('value','')} {ev.get('quote','')}")
        lines.append("")
    return "\n".join(lines)


def report_json(review):
    return json.dumps(review.to_dict(),ensure_ascii=False,indent=2)


def csv_safe(value):
    value=str(value)
    return "'"+value if value.lstrip().startswith(("=","+","-","@","\t","\r")) else value


def report_csv(review):
    output=io.StringIO(newline="")
    writer=csv.writer(output,delimiter=";")
    writer.writerow(["Regla","Validación","Estado","Tipo","Observación","Qué revisar","Páginas"])
    for f in review.findings:
        pages=sorted({n for ev in f.evidence for n in ev.get("pages",[ev["page"]] if "page" in ev else [])})
        writer.writerow([csv_safe(v) for v in [f.rule,f.title,f.status,f.category,f.message,f.action,", ".join(map(str,pages))]])
    return output.getvalue().encode("utf-8-sig")
