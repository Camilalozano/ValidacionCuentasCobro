from dataclasses import dataclass, field, asdict

LABELS = {
    "certificado": "Certificado de cumplimiento (F1_P2_F)",
    "informe": "Informe de ejecución (F1_P10_C)",
    "planilla": "Planilla de seguridad social",
    "cuenta": "Cuenta de cobro",
    "otro": "Soporte adicional / sin clasificar",
}

FIELD_LABELS = {"name":"Nombre", "cc":"Cédula", "contract":"Contrato", "amount":"Valor",
    "period_start":"Inicio del período", "period_end":"Fin del período", "invoice_number":"Consecutivo",
    "supervisor":"Supervisor", "signed_supervisor":"Nombre al pie de firma", "pila_number":"Número de planilla",
    "paid":"Fecha de pago", "pension_month":"Período de pensión", "health_month":"Período de salud",
    "contributions":"Total aportes", "affiliates":"Número de afiliados", "budget":"CDP / CRP / código interno",
    "start":"Inicio del contrato", "end":"Terminación del contrato", "issued":"Expedición o presentación",
    "progress":"Avance reportado", "amount_words":"Monto en letras", "crp_date":"Fecha del CRP"}


@dataclass
class Page:
    number: int
    text: str
    layout: str = ""
    method: str = "texto"
    kind: str = "otro"
    issue: str = ""


@dataclass
class Fact:
    value: str
    page: int
    quote: str
    method: str = "texto"


@dataclass
class Document:
    kind: str
    pages: list[int] = field(default_factory=list)
    fields: dict[str, list[Fact]] = field(default_factory=dict)

    def add(self, key, value, page, quote):
        if value is None or str(value).strip() == "":
            return
        fact = Fact(str(value), page.number, " ".join(quote.split())[:450], page.method)
        if fact not in self.fields.setdefault(key, []):
            self.fields[key].append(fact)

    def values(self, key):
        return list(dict.fromkeys(f.value for f in self.fields.get(key, [])))

    def get(self, key):
        values = self.values(key)
        return values[0] if len(values) == 1 else None


@dataclass
class Finding:
    rule: str
    title: str
    status: str
    category: str
    message: str
    action: str
    evidence: list[dict] = field(default_factory=list)


@dataclass
class Review:
    filename: str
    sha256: str
    reviewed_at: str
    ruleset: str
    documents: dict[str, Document]
    pages: list[Page]
    findings: list[Finding]
    sources: dict = field(default_factory=dict)

    def to_dict(self):
        result = asdict(self)
        # Los textos completos del expediente no forman parte del reporte.
        result["pages"] = [{"number": p.number, "kind": p.kind, "method": p.method,
                            "issue": p.issue} for p in self.pages]
        return result
