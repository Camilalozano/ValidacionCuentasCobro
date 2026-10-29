import re

from .models import Document, LABELS
from .normalize import norm, flat, digits, contract, money, parse_date, ranges, DATE_PATTERN, words_money

MONEY = r"\$\s*([\d][\d.,]*)"


def classify(text):
    t = flat(text)
    if re.search(r"f1\s*[_-]\s*p2\s*[_-]\s*f|formato certificado de cumplimiento", t):
        return "certificado"
    if re.search(r"f1\s*[_-]\s*p10\s*[_-]\s*c|formato informe de ejecucion y supervision", t):
        return "informe"
    if re.search(r"resumen general de pago|planilla integrada de autoliquidacion|datos generales de la liquidacion", t):
        return "planilla"
    if re.search(r"cuenta de cobro\s*(?:no\.?|n[°º.]|numero|#)\s*\d+", t) or ("factura electronica de venta" in t and "total" in t):
        return "cuenta"
    return "otro"


def add_match(doc, key, pattern, text, page, convert=lambda v: v, group=1, flags=0):
    for match in re.finditer(pattern, text, flags):
        doc.add(key, convert(match[group]), page, match[0])


def add_dates(doc, key, pattern, text, page):
    for match in re.finditer(pattern, text):
        date = parse_date(match[1])
        doc.add(key, date.isoformat() if date else "FECHA INVÁLIDA: " + match[1], page, match[0])


def extract_documents(pages):
    docs = {kind: Document(kind) for kind in LABELS if kind != "otro"}
    for page in pages:
        page.kind = classify(page.text)
        if page.kind == "otro":
            continue
        doc = docs[page.kind]
        doc.pages.append(page.number)
        t, layout = flat(page.text), norm(page.layout)
        if page.kind != "planilla":
            add_match(doc, "contract", r"atenea\s*[- ]*\s*\d{1,6}\s*-\s*20\d{2}", t, page, contract, group=0)
            # CC must be explicitly labelled. A NIT or bank account is not a CC.
            add_match(doc, "cc", r"\b(?:c\.?\s*c\.?|cedula(?: de ciudadania)?)\s*[:.\-]?\s*([\d.]{6,18})", t, page, digits)
            scope = t
            if page.kind == "informe":
                m = re.search(r"periodo del informe\s*:\s*(.{0,160})", t)
                scope = m[1].split("fecha de presentacion")[0] if m else ""
            for start, end, quote in ranges(scope):
                doc.add("period_start", start.isoformat() if start else "FECHA INVÁLIDA", page, quote)
                doc.add("period_end", end.isoformat() if end else "FECHA INVÁLIDA", page, quote)
        if page.kind == "certificado":
            extract_certificate(doc, page, t, layout)
        elif page.kind == "informe":
            extract_report(doc, page, t)
        elif page.kind == "cuenta":
            extract_invoice(doc, page, t)
        elif page.kind == "planilla":
            extract_pila(doc, page, t)
    return docs


def extract_certificate(doc, page, t, layout):
    # Layout retains table rows for invoice number, amount and signature-name labels.
    for line in layout.splitlines():
        m = re.match(rf"^\s*(\d{{1,5}})\s+({DATE_PATTERN})\s*-\s*({DATE_PATTERN})\s+{MONEY}", line)
        if m:
            doc.add("invoice_number", str(int(m[1])), page, m[0])
        m = re.search(rf"valor total\s*:\s*{MONEY}", line)
        if m:
            doc.add("amount", money(m[1]), page, m[0])
        m = re.search(r"nombre del interventor y/o supervisor\s*:\s*(.+)", line)
        if m:
            doc.add("supervisor", flat(m[1]), page, m[0])
    # Generic explicit invoice labels (not an arbitrary isolated digit).
    add_match(doc, "invoice_number", r"(?:factura|cuenta de cobro)\s*(?:no\.?|numero|n[°º.]|#)\s*:?\s*(\d{1,5})\b", t, page, lambda x:str(int(x)))
    if not doc.fields.get("amount"):
        add_match(doc, "amount", rf"valor total\s*:\s*{MONEY}", t, page, money)
    add_match(doc, "name", r"\bcc\s+[\d.]+\s+([a-z ]+?)\s+(?:bancolombia|banco\b|davivienda|bbva|nequi|daviplata)", t, page)
    add_dates(doc, "start", rf"atenea\s*[- ]*\s*\d{{1,6}}\s*-\s*20\d{{2}}\s+({DATE_PATTERN})", t, page)
    add_dates(doc, "end", rf"fecha (?:de )?terminacion(?: del contrato)?\s*:\s*({DATE_PATTERN})", t, page)
    add_dates(doc, "issued", rf"fecha expedicion\s*:\s*({DATE_PATTERN})", flat(page.layout), page)
    # The source row is retained as one budget tuple; never combine separate CRPs.
    for m in re.finditer(rf"\batenea\s+(\d{{1,8}})\s+(\d{{1,8}})\s+(\d{{8,15}})(?:\s+\d{{1,4}})?\s+({DATE_PATTERN})", t):
        doc.add("budget", f"{int(m[1])}|{int(m[2])}|{m[3]}", page, m[0])
        doc.add("cdp", str(int(m[1])), page, m[0]); doc.add("crp", str(int(m[2])), page, m[0])
        doc.add("internal_code", m[3], page, m[0])
        d = parse_date(m[4]); doc.add("crp_date", d.isoformat() if d else None, page, m[0])


def extract_report(doc, page, t):
    add_match(doc, "object", r"objeto del contrato(?: o convenio)?\s*:?\s*(.*?)\s+obligaciones y/o compromisos", t, page)
    add_match(doc, "name", r"nombre del contratista(?: o)?\s*(?:aliado/asociado/\s*cooperante)?\s*:\s*(.*?)\s+nombre identitario", t, page)
    add_match(doc, "supervisor", r"nombre del supervisor\s*:\s*(.*?)\s+cargo del supervisor", t, page)
    add_dates(doc, "start", rf"fecha (?:acta (?:de )?inicio|de inicio)(?: del contrato)?\s*:\s*({DATE_PATTERN})", t, page)
    add_dates(doc, "end", rf"fecha de terminacion del contrato\s*(?:o convenio)?\s*:\s*({DATE_PATTERN})", t, page)
    add_dates(doc, "issued", rf"fecha de presentacion del\s*informe\s*:\s*({DATE_PATTERN})", t, page)
    add_match(doc, "progress", r"porcentaje de avance del\s*contrato(?: o convenio)?\s*:\s*(\d+(?:[.,]\d+)?)\s*%", t, page, lambda x:x.replace(",", "."))
    section = re.search(r"pago de la seguridad social(.*?)porcentaje de avance", t)
    if section:
        ss = section[1]
        # Clave de pago and número de planilla are different identifiers.
        add_match(doc, "pila_number", r"(\d{5,15})\s*\(planilla\)", ss, page)
        add_match(doc, "pila_number", r"\b(?:numero de planilla|planilla(?:\s+(?:no\.?|numero|n[°º.]))?)\s*[:#-]?\s*(\d{5,15})\b", ss, page)
        dates = re.findall(DATE_PATTERN, ss)
        for raw in dates:
            d = parse_date(raw); doc.add("paid", d.isoformat() if d else "FECHA INVÁLIDA: " + raw, page, ss)
    # Explicit signatory caption only, never infer from the main supervisor field.
    add_match(doc, "signed_supervisor", r"firma (?:del )?supervisor\s*:\s*([a-z ]{8,70})(?=\s+(?:cedula|cc|cargo|firma)|$)", t, page)


def extract_invoice(doc, page, t):
    add_match(doc, "invoice_number", r"(?:cuenta de cobro|factura)\s*(?:no\.?|numero|n[°º.]|#)\s*:?\s*(\d{1,5})\b", t, page, lambda x:str(int(x)))
    add_match(doc, "name", r"debe a\s*:\s*(.*?)\s+(?:la suma de|por concepto)", t, page)
    add_match(doc, "amount", MONEY, t, page, money)
    add_dates(doc, "issued", rf"(?:cuenta de cobro|factura)\s*(?:no\.?|numero|n[°º.]|#)\s*\d+(?:\s*-\s*20\d{{2}})?\s+({DATE_PATTERN})", t, page)
    m = re.search(r"la suma de\s*:\s*(.*?)\s*\(?\s*\$", t)
    if m:
        doc.add("amount_words", words_money(m[1]), page, m[1])


def extract_pila(doc, page, t):
    general = re.search(r"datos generales del aportante(.*?)datos generales de la liquidacion", t)
    if general:
        add_match(doc, "cc", r"\bcc\s*([\d.]{6,18})\b", general[1], page, digits)
        add_match(doc, "name", r"\bcc\s*[\d.]{6,18}\s+([a-z ]+?)\s+(?:independiente|empresa|empleador)", general[1], page)
    else:
        add_match(doc, "cc", r"(?:cedula|\bcc)\s*[:.]?\s*([\d.]{6,18})\b", t, page, digits)
    # Layout used by the supplied PILA: pension month, health month, payment key,
    # planilla, type, deadline, effective payment date, bank, arrears, amount.
    block = re.search(r"datos generales de la liquidacion(.*?)(?:resumen de pago|pagina \d|$)", t)
    if block:
        m = re.search(r"(20\d{2}-\d{2})\s+(20\d{2}-\d{2})\s+(\d{5,15})\s+(\d{5,15})\s+[a-z]\s+(\d{4}/\d{2}/\d{2})\s+(\d{4}/\d{2}/\d{2})\s+(.*?)\s+\d+\s+\$\s*([\d.,]+)", block[1])
        if m:
            for key, index in [("pension_month",1),("health_month",2),("payment_key",3),("pila_number",4)]:
                doc.add(key, m[index], page, m[0])
            d = parse_date(m[6]); doc.add("paid", d.isoformat() if d else None, page, m[0])
            doc.add("contributions", money(m[8]), page, m[0])
    add_match(doc, "pila_number", r"(?:numero de planilla|planilla no\.?)\s*:?\s*(\d{5,15})", t, page)
    for key, pattern in [("health",r"eps \(administradoras: \d+\)\s+\d+\s*"),
                         ("pension",r"afp \(administradoras: \d+\)\s+\d+\s*"),
                         ("risk",r"arl \(administradoras: \d+\)\s+\d+\s*")]:
        add_match(doc, key, pattern + MONEY, t, page, money)
    add_match(doc, "affiliates", r"total\s+afiliados\s*\(\s*(\d+)\s*\)", t, page)


SUPPORTS = {
    "RUT": r"registro unico tributario",
    "RIT": r"registro (?:de )?informacion tributaria",
    "Cédula": r"republica de colombia.{0,100}identificacion personal.{0,100}cedula de ciudadania",
    "Certificación bancaria": r"(?:certificacion bancaria|certificado bancario|(?:bancolombia|davivienda|banco\s+\w+).{0,150}certifica que)",
    "Contrato": r"(?:contrato electronico|informacion general del contrato|contrato de prestacion de servicios.{0,200}(?:contratante|contratista|clausula))",
    "Minuta": r"(?:minuta del? contrato|clausulado|clausula primera.{0,150}objeto)",
    "CRP": r"certificado de registro presupuestal",
    "Disminución de retención": r"solicitud de disminucion (?:de )?retencion",
}


def find_supports(pages):
    found = {}
    for page in pages:
        if page.kind != "otro":
            continue
        t = flat(page.text)
        for name, pattern in SUPPORTS.items():
            match = re.search(pattern, t[:2000])
            if match:
                found.setdefault(name, []).append({"page":page.number,"quote":match[0]})
    return found
