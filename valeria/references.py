import csv
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime

from .normalize import flat, person, money, contract


@dataclass
class ReferenceRow:
    sheet: str
    number: int
    cells: list[str]
    headers: list[str]

    @property
    def text(self):
        return " | ".join(self.cells)

    def labelled(self, pattern):
        return [v for h,v in zip(self.headers,self.cells) if re.search(pattern, flat(h)) and v]

    def evidence_text(self):
        selected=[f"{h}: {v}" for h,v in zip(self.headers,self.cells)
                  if v and re.search(r"numero.*doc.*beneficiario|nombre.*beneficiario|cedula|documento|^nombre$|^contrato$|no\.? compromiso|numero de c[dr]p|^c[dr]p$|interno.*crp|crp.*interno|codigo interno|^ejercicio$|valor mensual|honorarios mensuales",flat(h))]
        return " | ".join(selected) if selected else self.text[:1600]


@dataclass
class Reference:
    name: str = "No cargada"
    rows: list[ReferenceRow] = field(default_factory=list)


def cell_text(value):
    if value is None: return ""
    if isinstance(value, (datetime,date)): return value.isoformat()[:10]
    if isinstance(value, float) and value.is_integer(): return str(int(value))
    return str(value).strip()


def read_reference(data, filename):
    if len(data) > 10 * 1024 * 1024:
        raise ValueError("La base de referencia supera 10 MB.")
    rows = []
    if filename.lower().endswith(".xlsx"):
        from openpyxl import load_workbook
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as package:
                if sum(x.file_size for x in package.infolist()) > 60*1024*1024 or len(package.infolist()) > 1000:
                    raise ValueError("El Excel descomprimido supera los límites de lectura.")
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True, keep_links=False)
            try:
                for sheet in wb:
                    if (sheet.max_row or 0) > 30000 or (sheet.max_column or 0) > 100:
                        raise ValueError("La base debe tener hasta 30.000 filas y 100 columnas por hoja.")
                    rows.extend(_rows(sheet.iter_rows(values_only=True), sheet.title))
            finally:
                wb.close()
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("No fue posible leer el Excel. Guarde una copia como XLSX sin contraseña.") from exc
    elif filename.lower().endswith(".csv"):
        try: text = data.decode("utf-8-sig")
        except UnicodeDecodeError: text = data.decode("cp1252")
        try: dialect = csv.Sniffer().sniff(text[:12000], delimiters=",;\t")
        except csv.Error: dialect = csv.excel
        rows.extend(_rows(csv.reader(io.StringIO(text), dialect), "CSV"))
    else:
        raise ValueError("La base debe ser XLSX o CSV.")
    if not rows:
        raise ValueError("La base de referencia no contiene filas legibles.")
    return Reference(filename, rows)


def _rows(values, sheet):
    headers = []
    count = 0
    for i, raw in enumerate(values, 1):
        if i > 30000 or len(raw) > 100:
            raise ValueError("La base supera los límites de filas o columnas.")
        cells = [cell_text(v) for v in raw]
        count += sum(len(c) for c in cells)
        if count > 12_000_000:
            raise ValueError("La base contiene demasiado texto.")
        if not any(cells): continue
        if not headers and any(re.search(r"beneficiario|contratista|cedula|documento|numero de cdp", flat(c)) for c in cells):
            headers = cells
            continue
        yield ReferenceRow(sheet, i, cells, headers)


def contractor_rows(reference, cc, name, contract_id=None):
    result = []
    name_tokens = set(person(name or "").split())
    for row in reference.rows:
        contract_cells = row.labelled(r"(?:numero|no\.?|n[°º])\s*(?:de )?(?:contrato|compromiso)|^contrato$")
        contracts = [contract(c) for c in contract_cells if contract(c)]
        if contract_id and contracts and contract_id not in contracts:
            continue
        id_cells = row.labelled(r"(?:numero.*doc.*beneficiario|cedula|documento|^cc$)")
        if not id_cells: id_cells = row.cells
        # IDs compare as entire cells, never substrings inside another identifier.
        id_match = bool(cc and any(re.sub(r"[.\s]", "", c) == cc for c in id_cells))
        name_match = bool(len(name_tokens) >= 3 and name_tokens.issubset(set(person(row.text).split())))
        if id_match or name_match:
            result.append(row)
    return result


def budget_matches(row, cdp, crp, internal):
    # Use labelled evidence when available, retaining the complete row context.
    groups = [row.labelled(r"^(?:numero de |n[°º.]?\s*)?cdp$"),
              row.labelled(r"^(?:numero de |n[°º.]?\s*)?crp$"),
              row.labelled(r"interno.*crp|crp.*interno|codigo interno")]
    flags = []
    for values, expected in zip(groups, (cdp,crp,internal)):
        candidates = values or row.cells
        flags.append(any(re.split(r"\s+", c.strip())[0].lstrip("0") == expected.lstrip("0") for c in candidates if c.strip()))
    return flags


def monthly_amount(rows):
    values = []
    evidence = []
    for row in rows:
        for value in row.labelled(r"valor mensual|honorarios mensuales|^mensualidad$"):
            amount = money(value)
            if amount is not None:
                values.append(amount)
                evidence.append({"source":f"{row.sheet}, fila {row.number}","value":str(amount),"quote":row.evidence_text()})
    unique = list(dict.fromkeys(values))
    return (unique[0] if len(unique) == 1 else None), evidence
