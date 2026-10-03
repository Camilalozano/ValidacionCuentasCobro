"""Reglas deterministas del instructivo VF_VALIDACION 2 26052026.

REVISAR cubre discrepancias, evidencia insuficiente y controles humanos pendientes.
Ningún resultado autoriza un pago ni certifica la autenticidad de una firma.
"""
import calendar
import re
from datetime import date
from decimal import Decimal

from .models import Finding, LABELS
from .normalize import person, parse_date, pesos, is_full_month, flat, DATE_PATTERN, same_supervisor
from .extract import SUPPORTS, find_supports
from .references import Reference, contractor_rows, budget_matches, monthly_amount

OK = "VALIDADO"
REVIEW = "REVISAR"


def evaluate(docs, pages, crp=None, monthly=None, review_date=None):
    crp = crp or Reference(); monthly = monthly or Reference()
    review_date = review_date or date.today()
    results = []
    c, r, p, q = [docs[k] for k in ("certificado","informe","planilla","cuenta")]

    def evidence(items):
        output=[]
        for doc,key in items:
            facts=doc.fields.get(key, [])
            if not facts:
                output.append({"document":LABELS[doc.kind],"field":key,"value":"NO ENCONTRADO",
                               "pages":doc.pages,"quote":""})
            for fact in facts:
                output.append({"document":LABELS[doc.kind],"field":key,"value":fact.value,
                               "pages":[fact.page],"quote":fact.quote,"method":fact.method})
        return output

    def add(rule,title,passed,message,action="",items=(),category=None,extra=()):
        results.append(Finding(str(rule).zfill(2),title,OK if passed else REVIEW,
                               category or ("Sin diferencia detectada" if passed else "Evidencia incompleta"),
                               message,action,evidence(items)+list(extra)))

    def compare(rule,title,items,normalize=lambda x:x):
        values=[doc.get(key) for doc,key in items]
        complete=all(v is not None for v in values)
        equal=complete and len({normalize(v) for v in values}) == 1
        if any(key=="paid" for _,key in items): equal = equal and all(parse_date(v or "") for v in values)
        description="; ".join(f"{LABELS[d.kind]}: {', '.join(d.values(k)) or 'NO ENCONTRADO'}" for d,k in items)
        add(rule,title,equal,description,
            "Contrastar el campo en las páginas señaladas y corregir la diferencia o completar el soporte." if not equal else "",
            items, "Inconsistencia" if complete and not equal else None)

    # 00 is a technical prerequisite, not an invented business rule 17.
    missing=[LABELS[k] for k,d in docs.items() if not d.pages]
    if missing:
        add("00","Integridad del PDF",False,"No se identificaron: "+", ".join(missing),
            "Incluir los documentos o revisar si están escaneados o en un formato diferente.",category="Evidencia incompleta")
    issues=[x for x in pages if x.issue]
    if issues:
        add("00","Legibilidad y cobertura",False,"Hay páginas cuya lectura requiere contraste visual.",
            "Revisar las imágenes de estas páginas. Los campos no legibles no se dan por cumplidos.",
            category="Revisión visual",extra=[{"pages":[x.number],"quote":x.issue,"method":x.method} for x in issues])

    period_items=[(d,k) for d in (c,r,q) for k in ("period_start","period_end")]
    month_items=period_items+[(p,"pension_month"),(p,"health_month")]
    dates=[parse_date(d.get(k) or "") for d,k in period_items]
    months=[]
    for key in ("pension_month","health_month"):
        raw=p.get(key)
        month=parse_date((raw+"-01") if raw else "")
        months.append(month)
    valid_months=all(dates+months) and len({v.strftime("%Y-%m") for v in dates+months}) == 1
    add(1,"Mes del período y de la planilla",valid_months,
        "Los documentos y ambos períodos de la planilla corresponden al mismo mes." if valid_months else "Los meses no coinciden o falta un período legible.",
        "Contrastar el mes de pensión y salud con el período cobrado. Esta comparación aplica la regla interna suministrada." if not valid_months else "",
        month_items, "Inconsistencia" if all(dates+months) and not valid_months else None)
    compare(2,"Cédula del contratista",[(d,"cc") for d in (c,r,p,q)])
    compare(3,"Número de contrato",[(d,"contract") for d in (c,r,q)])
    compare(4,"Nombre del contratista",[(d,"name") for d in (c,r,p,q)],person)
    compare(5,"Valor certificado y facturado",[(c,"amount"),(q,"amount")],Decimal)
    compare(6,"Número de cuenta de cobro",[(c,"invoice_number"),(q,"invoice_number")])
    compare(7,"Número de planilla",[(r,"pila_number"),(p,"pila_number")])
    compare(8,"Fecha de pago de la planilla",[(r,"paid"),(p,"paid")])

    amount = Decimal(c.get("amount")) if c.get("amount") else None
    total = Decimal(p.get("contributions")) if p.get("contributions") else None
    affiliates=p.get("affiliates")
    ss_items=[(c,"amount"),(p,"contributions"),(p,"affiliates")]
    if amount is not None and total is not None and amount > 0 and affiliates == "1":
        ibc=amount*Decimal("0.4")
        minimum=ibc*(Decimal("0.125")+Decimal("0.16")+Decimal("0.00522"))
        add(9,"Aportes según fórmula del instructivo",total>=minimum,
            f"Base 40%: {pesos(ibc)}. Salud 12,5%, pensión 16% y riesgos 0,522%: {pesos(minimum)}. Aportes: {pesos(total)}.",
            "Revisar los aportes y las particularidades del cotizante. La fórmula es la del instructivo, no una liquidación normativa completa.",
            ss_items,"Inconsistencia" if total<minimum else None)
    else:
        add(9,"Aportes según fórmula del instructivo",False,
            "Falta el valor certificado, el total de aportes o la confirmación de una planilla de un único afiliado.",
            "No comparar el total de varios afiliados contra una sola cuenta. Confirmar los valores del contratista.",ss_items)

    supervisors=[c.get("supervisor"),r.get("supervisor"),r.get("signed_supervisor")]
    main_equal=all(supervisors[:2]) and same_supervisor(supervisors[0],supervisors[1])
    # Caption is additional evidence; it cannot prove a handwritten signature's identity.
    signed_equal=bool(supervisors[2] and main_equal and same_supervisor(supervisors[2],supervisors[0]))
    add(10,"Supervisor y nombre de quien firma",signed_equal,
        ("Los nombres de los campos coinciden. " if main_equal else "Los nombres no coinciden o están incompletos. ") +
        ("Se encontró el mismo nombre en el pie de firma." if signed_equal else "Falta confirmar la identidad en el pie de firma."),
        "Contrastar el nombre bajo la firma. Un segundo nombre omitido debe revisarse con la evidencia del documento." if not signed_equal else "",
        [(c,"supervisor"),(r,"supervisor"),(r,"signed_supervisor")],"Revisión visual" if main_equal and not signed_equal else None)

    cc=c.get("cc") or q.get("cc"); name=c.get("name") or q.get("name")
    candidates=contractor_rows(crp,cc,name,c.get("contract") or q.get("contract"))
    budget_details=[]; every_budget=True
    for entry in c.values("budget"):
        cdp,crp_no,internal=entry.split("|")
        matching=[row for row in candidates if all(budget_matches(row,cdp,crp_no,internal))]
        every_budget &= bool(matching)
        selected=matching or candidates[:3]
        budget_details.extend({"source":f"{crp.name}: {row.sheet}, fila {row.number}",
             "value":f"Valores del PDF: CDP {cdp}, CRP {crp_no}, interno {internal}","quote":row.evidence_text(),
             "matches":dict(zip(["CDP","CRP","Código interno"],budget_matches(row,cdp,crp_no,internal)))} for row in selected[:3])
    found_budget=bool(c.values("budget") and candidates and every_budget)
    add(11,"CDP, CRP y código interno",found_budget,
        ("Se encontró evidencia conjunta del contratista y los códigos en la misma fila." if found_budget else
         "No se encontró coincidencia completa de contratista, CDP, CRP y código interno en la referencia cargada." if crp.rows else
         "No se cargó una base CRP para contrastar los códigos."),
        "Verificar la vigencia de la base y contrastar los códigos exactos. No corregir un dígito sin revisar el soporte." if not found_budget else "",
        [(c,"budget")],"Inconsistencia" if candidates and not every_budget else None,budget_details)

    start_facts=[d.get("start") for d in (c,r,q) if d.get("start")]
    end_facts=[d.get("end") for d in (c,r,q) if d.get("end")]
    start=parse_date(c.get("start") or r.get("start") or "")
    end=parse_date(r.get("end") or c.get("end") or "")
    cutoff=parse_date(r.get("period_end") or q.get("period_end") or "")
    pct=Decimal(r.get("progress")) if r.get("progress") else None
    date_problems=[]; calc=None
    if not start or not end: date_problems.append("Falta una fecha contractual legible.")
    elif start>=end: date_problems.append("El inicio no es anterior a la terminación.")
    elif cutoff:
        duration=(end-start).days
        calc=Decimal((cutoff-start).days)*100/Decimal(duration)
        if not start<=cutoff<=end: date_problems.append("El corte del informe está fuera de la vigencia contractual.")
        if pct is None: date_problems.append("No se encontró el porcentaje de avance reportado.")
        elif abs(pct-calc)>5: date_problems.append("El avance reportado difiere en más de 5 puntos porcentuales.")
    else: date_problems.append("Falta la fecha de corte.")
    if len(start_facts)<2 or len(end_facts)<2: date_problems.append("Las fechas no están corroboradas en dos documentos.")
    if len(set(start_facts))>1 or len(set(end_facts))>1: date_problems.append("Hay fechas contractuales contradictorias.")
    message=f"Inicio: {start or 'NO ENCONTRADO'}. Fin: {end or 'NO ENCONTRADO'}. Corte: {cutoff or 'NO ENCONTRADO'}. "
    if calc is not None: message+=f"Avance calculado con fechas extraídas: {calc:.2f}%. Reportado: {pct if pct is not None else 'NO ENCONTRADO'}%. "
    add(12,"Vigencia y porcentaje de avance",not date_problems,message+" ".join(date_problems),
        "Confirmar las fechas contractuales antes de usar el cálculo de avance." if date_problems else "",
        [(d,k) for d in (c,r) for k in ("start","end")]+[(r,"progress"),(r,"period_end")],
        "Inconsistencia" if any("fuera" in x or "difiere" in x or "contradictorias" in x for x in date_problems) else None)

    invoice_values=c.values("invoice_number")+q.values("invoice_number")
    if "1" in invoice_values:
        supports=find_supports(pages)
        absent=[x for x in SUPPORTS if x not in supports]
        detail="Primera cuenta. Soportes identificados por texto: "+(", ".join(supports) or "ninguno")+". "
        if absent: detail+="Sin evidencia de: "+", ".join(absent)+". "
        bank_pages={e["page"] for e in supports.get("Certificación bancaria",[])}
        issue_dates=[]
        for page in pages:
            if page.number in bank_pages:
                for m in re.finditer(rf"(?:expedid[oa]|fecha de expedicion|se expide)(?: el| a los)?\s*:?\s*({DATE_PATTERN})",flat(page.text)):
                    parsed=parse_date(m[1])
                    if parsed: issue_dates.append(parsed)
        anchor=parse_date(q.get("issued") or c.get("issued") or "") or review_date
        if len(set(issue_dates))==1:
            bank_date=issue_dates[0]
            month_index=bank_date.year*12+bank_date.month-1+3
            y,mo=divmod(month_index,12); mo+=1
            expiry=date(y,mo,min(bank_date.day,calendar.monthrange(y,mo)[1]))
            detail+=f"Certificación bancaria: {bank_date}. Corte: {anchor}. "+("Dentro de tres meses." if bank_date<=anchor<=expiry else "Fuera de vigencia o fecha futura.")
        else: detail+="No se pudo confirmar una fecha única de expedición de la certificación bancaria."
        add(13,"Soportes de primera cuenta",False,detail,
            "Completar los soportes faltantes y confirmar titular, contenido y vigencia de cada copia. Las menciones de un documento no prueban que esté anexado.",
            [(c,"invoice_number"),(q,"invoice_number")],"Evidencia incompleta" if absent else "Revisión visual",
            [{"document":key,**ev} for key,items in supports.items() for ev in items])
    elif len(set(invoice_values))==1 and len(invoice_values)>=2:
        results.append(Finding("13","Soportes de primera cuenta","NO APLICA","No aplica",
                               "Los consecutivos coinciden y son posteriores a la primera cuenta.","",evidence([(c,"invoice_number"),(q,"invoice_number")])))
    else:
        add(13,"Soportes de primera cuenta",False,"No es posible descartar que sea la primera cuenta.",
            "Confirmar el consecutivo antes de excluir los ocho soportes adicionales.",[(c,"invoice_number"),(q,"invoice_number")])

    consistency=[]
    for d in (c,r,q):
        issued=parse_date(d.get("issued") or ""); last=parse_date(d.get("period_end") or "")
        if issued and last and issued<last:
            consistency.append(f"{LABELS[d.kind]}: fecha de expedición/presentación {issued} anterior al cierre del período {last}.")
        for key, facts in d.fields.items():
            if key not in {"budget","cdp","crp","internal_code","crp_date"} and len(d.values(key))>1:
                consistency.append(f"{LABELS[d.kind]}: se encontraron varios valores para {key}; podría haber más de una cuenta o un dato contradictorio.")
    if q.get("amount_words") and q.get("amount") and Decimal(q.get("amount_words")) != Decimal(q.get("amount")):
        consistency.append(f"Cuenta: monto en letras {pesos(q.get('amount_words'))} distinto al numérico {pesos(q.get('amount'))}.")
    contract_id=c.get("contract")
    if contract_id and start and start.year<int(contract_id.split("-")[-1]):
        consistency.append(f"Inicio {start} anterior al año del contrato {contract_id}. Confirmar la fecha original.")
    crp_date=parse_date(c.get("crp_date") or "")
    if contract_id and crp_date and crp_date.year<int(contract_id.split("-")[-1]):
        consistency.append(f"Fecha CRP {crp_date} anterior al año del contrato. Contrastar el registro presupuestal.")
    if start and end:
        for d in (c,r,q):
            first=parse_date(d.get("period_start") or ""); last=parse_date(d.get("period_end") or "")
            if first and last and (first<start or last>end): consistency.append(f"{LABELS[d.kind]}: período fuera de vigencia.")
    add(14,"Consistencia integral del expediente",False,
        " ".join(consistency) if consistency else "Sin contradicciones adicionales detectadas por las comprobaciones automáticas. La correspondencia semántica y las actividades requieren revisión humana.",
        "Revisar los hallazgos y contrastar objeto, actividades, soportes y contenido completo del expediente.",
        [(q,"amount_words"),(q,"amount"),(c,"start"),(c,"crp_date"),(r,"issued")],
        "Inconsistencia" if consistency else "Revisión de contenido")

    invoice_end=parse_date(q.get("period_end") or "")
    pila_months=[parse_date((p.get(k)+"-01") if p.get(k) else "") for k in ("pension_month","health_month")]
    if invoice_end and all(pila_months):
        expired=any((v.year,v.month)<(invoice_end.year,invoice_end.month) for v in pila_months)
        add(15,"Planilla anterior al mes cobrado",not expired,
            "La planilla contiene un período anterior al mes cobrado." if expired else "Ningún período de la planilla es anterior al mes cobrado.",
            "Confirmar el soporte exigible para ese período según la regla interna. No se emite una conclusión de mora legal." if expired else "",
            [(q,"period_end"),(p,"pension_month"),(p,"health_month")],"Inconsistencia" if expired else None)
    else:
        add(15,"Planilla anterior al mes cobrado",False,"No se pudieron comparar los meses.","Confirmar los períodos de cobro y aportes.",[(q,"period_end"),(p,"pension_month"),(p,"health_month")])

    monthly_rows=contractor_rows(monthly,cc,name,c.get("contract") or q.get("contract"))
    monthly_value, monthly_evidence=monthly_amount(monthly_rows)
    first=parse_date(q.get("period_start") or ""); last=parse_date(q.get("period_end") or "")
    if monthly_value is not None and monthly_value>0 and first and last and first<=last and (first.year,first.month)==(last.year,last.month) and q.get("amount"):
        days=30 if is_full_month(first,last) else min(last.day,30)-min(first.day,30)+1
        expected=(monthly_value*Decimal(days)/30).quantize(Decimal("0.01"))
        exact=Decimal(q.get("amount"))==expected
        add(16,"Valor mensual y días de cobro",exact,
            f"Valor mensual: {pesos(monthly_value)}. Base comercial: {days} días. Esperado: {pesos(expected)}. Cobrado: {pesos(q.get('amount'))}.",
            "Contrastar el valor mensual y la convención de 30 días con el contrato." if not exact else "",
            [(q,"amount"),(q,"period_start"),(q,"period_end")],"Inconsistencia" if not exact else None,monthly_evidence)
    else:
        add(16,"Valor mensual y días de cobro",False,
            "No hay un valor mensual único y explícito en la base de honorarios, o falta un período/valor de cobro legible.",
            "Cargar la base de valor mensual. No se toma el valor total del CRP como honorario mensual ni se infiere el valor desde la propia cuenta.",
            [(q,"amount"),(q,"period_start"),(q,"period_end")],extra=monthly_evidence)

    starts=[parse_date(d.get("period_start") or "") for d in (c,r,q)]
    ends=[parse_date(d.get("period_end") or "") for d in (c,r,q)]
    ranges_complete=all(starts+ends)
    ranges_equal=ranges_complete and len(set(starts))==1 and len(set(ends))==1 and all(a<=b for a,b in zip(starts,ends))
    add(18,"Rango exacto del período",ranges_equal,
        "Los tres documentos tienen el mismo rango de fechas." if ranges_equal else "Los rangos no coinciden, son inválidos o no se pudieron extraer.",
        "Comparar día inicial y final, no solo el mes. Se admiten períodos parciales coincidentes." if not ranges_equal else "",
        period_items,"Inconsistencia" if ranges_complete and not ranges_equal else None)

    add(19,"Firmas obligatorias",False,
        "Pendiente de inspección visual: supervisor en certificado, contratista y supervisor en informe, contratista en cuenta. La planilla no requiere revisión de firmas.",
        "Abrir las páginas y verificar un trazo o firma visible en cada campo. Un nombre digitado, una línea o un sello no prueban una firma. La autenticidad requiere verificación aparte.",
        category="Revisión visual",extra=[{"document":LABELS[d.kind],"pages":d.pages,"quote":role}
            for d,role in [(c,"Firma del supervisor"),(r,"Firmas del contratista y supervisor"),(q,"Firma del contratista")]])
    return results
