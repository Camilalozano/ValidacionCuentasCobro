"""Contraste con SECOP: la URL PAR nunca se incluye en resultados ni errores."""
import csv
import hashlib
import io
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .models import Finding, LABELS
from .normalize import flat, parse_date, pesos, is_full_month

REFERENCE = 'referencia_del_contrato (contratos_electronicos)'
COLUMNS = {
    'supervisor': 'nombre_supervisor (contratos_electronicos)',
    'name': 'proveedor_adjudicado (contratos_electronicos)',
    'cc': 'documento_proveedor (contratos_electronicos)',
    'start': 'fecha_de_inicio_del_contrato (contratos_electronicos)',
    'end': 'fecha_de_fin_del_contrato (contratos_electronicos)',
    'object': 'descripcion_del_proceso (contratos_electronicos)',
    'monthly': 'valor_pago_mensual_inferido',
}

def reference_key(value):
    key = re.sub(r'[\s\-\u2010-\u2015\u2212]+', '', str(value).upper())
    return key[6:] if key.startswith('ATENEA') else key

def text(value):
    value = str(value or '').strip()
    return '' if value.lower() in {'nan', 'none', 'null', 'no definido', 'no identificado'} else value

def name_matches(a, b):
    def tokens(value):
        return set(re.findall(r'[a-z]+', flat(value))) - {'de', 'del', 'la', 'las', 'los', 'y'}
    a, b = tokens(a), tokens(b)
    # Permite una omisión, pero nunca acepta un solo nombre ni letras diferentes.
    return bool(len(a) >= 2 and len(b) >= 2 and (a == b or
                (min(len(a), len(b)) >= 3 and (a <= b or b <= a) and abs(len(a)-len(b)) <= 1)))

def select_record(data, reference):
    raw = data.decode('utf-8-sig')
    try:
        dialect = csv.Sniffer().sniff(raw[:32768], delimiters=',;\t')
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(raw), dialect=dialect)
    headers = reader.fieldnames or []
    if REFERENCE not in headers or len(headers) != len(set(headers)):
        raise ValueError('La base SECOP no tiene una estructura válida.')
    matches = []
    for number, row in enumerate(reader, 2):
        if number > 200001:
            raise ValueError('La base SECOP supera 200.000 registros.')
        if reference_key(row.get(REFERENCE, '')) == reference_key(reference):
            matches.append((number, {key: text(row.get(column)) for key, column in COLUMNS.items()}))
    if not matches:
        raise ValueError('Contrato no encontrado en la base SECOP.')
    if any(record != matches[0][1] for _, record in matches[1:]):
        raise ValueError('Hay registros contradictorios para el contrato en la base SECOP; no se seleccionó ninguno.')
    return dict(record=matches[0][1], rows=[n for n, _ in matches],
                sha256=hashlib.sha256(data).hexdigest(),
                consulted_at=datetime.now(timezone.utc).isoformat(), reference=reference)

def lookup(url, reference):
    if not reference:
        return {'error': 'No se extrajo un contrato único del informe de ejecución.'}
    if not url:
        return {'error': 'Falta configurar la ruta PAR de la base SECOP.'}
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname != 'objectstorage.us-ashburn-1.oraclecloud.com':
        return {'error': 'La ruta PAR configurada no es válida.'}
    try:
        with urlopen(Request(url, headers={'User-Agent': 'ValerIA/SECOP'}), timeout=30) as response:
            if response.geturl() != url:
                return {'error': 'La base SECOP devolvió una redirección inesperada.'}
            data = response.read(50 * 1024 * 1024 + 1)
        if len(data) > 50 * 1024 * 1024:
            return {'error': 'La base SECOP supera 50 MB.'}
    except Exception:
        return {'error': 'No se pudo consultar SECOP. Revise la conexión y la vigencia de la ruta PAR.'}
    try:
        return select_record(data, reference)
    except Exception as exc:
        return {'error': str(exc) if isinstance(exc, ValueError) and not isinstance(exc, UnicodeError)
                else 'No se pudo interpretar el CSV de SECOP.'}

def base_date(value):
    return parse_date(text(value).split('T')[0].split(' ')[0])

def compare_with_base(docs, base):
    """Reglas adicionales 20/21 y reemplazo de la regla 10, sin modificar los PDF."""
    error = base.get('error')
    record = base.get('record', {})
    provenance = {'source': 'Base SECOP · Oracle', 'quote':
                  f"Contrato {base.get('reference', '')}; filas {base.get('rows', [])}; consulta {base.get('consulted_at', '')}; SHA-256 {base.get('sha256', '')}"}
    def finding(rule, title, details, differences=False, missing=False, evidence=()):
        return Finding(rule, title, 'REVISAR' if differences or missing else 'VALIDADO',
                       'Inconsistencia' if differences else 'Evidencia incompleta' if missing else 'Sin diferencia detectada',
                       '\n'.join(details), 'Prima la base SECOP. Revisar las diferencias y completar los campos faltantes.'
                       if differences or missing else '', [provenance] + list(evidence))
    if error:
        return [finding('10', 'Supervisor frente a SECOP', [error, 'La firma sigue pendiente de inspección visual (regla 19).'], missing=True),
                finding('20', 'Consistencia de documentos con SECOP', [error], missing=True),
                finding('21', 'Honorarios orientativos de SECOP', [error], missing=True)]
    results = []
    details, evidence, diff, missing = [], [], False, False
    supervisor = record.get('supervisor', '')
    for kind in ('certificado', 'informe'):
        doc = docs[kind]
        values = doc.values('supervisor')
        missing |= not supervisor or not values
        mismatch = bool(supervisor and values and any(not name_matches(v, supervisor) for v in values))
        diff |= mismatch
        details.append(f"{LABELS[kind]}: {', '.join(values) or 'NO ENCONTRADO'}; supervisor SECOP: {supervisor or 'SIN DATO'}" + (' · DIFERENCIA' if mismatch else ''))
        evidence.extend({'document': LABELS[kind], 'pages': [f.page], 'field': 'supervisor', 'value': f.value, 'quote': f.quote} for f in doc.fields.get('supervisor', []))
    details.append('Se aceptan diferencias de caja, tildes, puntuación, orden y una omisión de nombre/apellido con al menos tres componentes coincidentes. La firma requiere inspección visual (regla 19).')
    results.append(finding('10', 'Supervisor frente a SECOP', details, diff, missing, evidence))
    details, evidence, diff, missing = [], [], False, False
    for key in ('name', 'cc', 'start', 'end', 'object'):
        expected = record.get(key, '')
        expected_value = base_date(expected) if key in ('start', 'end') else expected
        details.append(f"Base SECOP · {COLUMNS[key]}: {expected or 'SIN DATO'}")
        missing |= not expected_value
        kinds = ('certificado', 'informe', 'planilla', 'cuenta') if key in ('name', 'cc') else ('informe',) if key == 'object' else ('certificado', 'informe')
        found = False
        for kind in kinds:
            doc = docs[kind]
            values = doc.values(key)
            if not values:
                # La falta de un campo en un soporte no sustituye la comparación en los demás.
                continue
            found = True
            for value in values:
                if key == 'name':
                    same = name_matches(value, expected)
                elif key in ('start', 'end'):
                    same = bool(expected_value and parse_date(value) == expected_value)
                elif key == 'cc':
                    same = re.sub(r'\D', '', value) == re.sub(r'\D', '', expected)
                else:
                    clean = lambda v: ' '.join(re.findall(r'[a-z0-9]+', flat(v)))
                    same = clean(value) == clean(expected)
                mismatch = bool(expected_value and not same)
                diff |= mismatch
                details.append(f"{LABELS[kind]} · {key}: {value}" + (' · DIFERENCIA: prima SECOP' if mismatch else ' · coincide' if expected_value else ' · sin referencia'))
            evidence.extend({'document': LABELS[kind], 'pages': [f.page], 'field': key, 'value': f.value, 'quote': f.quote} for f in doc.fields.get(key, []))
        if not found:
            missing = True
            details.append(f"PDF · {key}: NO ENCONTRADO")
    details.append('El objeto se compara por texto normalizado; diferencias de redacción requieren revisión de contenido.')
    results.append(finding('20', 'Consistencia de documentos con SECOP', details, diff, missing, evidence))
    q = docs['cuenta']
    raw = record.get('monthly', '')
    details = [f"Valor mensual orientativo SECOP (inferido): {raw or 'SIN DATO'}. Umbral de alerta: diferencia mayor al 10 %. No valida el honorario contractual exacto."]
    try:
        monthly = Decimal(raw.replace(',', ''))
        amount = Decimal(q.get('amount') or '')
        first, last = parse_date(q.get('period_start') or ''), parse_date(q.get('period_end') or '')
        if monthly <= 0 or not monthly.is_finite() or not amount.is_finite() or not first or not last or first > last or (first.year, first.month) != (last.year, last.month):
            raise ValueError()
        days = 30 if is_full_month(first, last) else min(last.day, 30)-min(first.day, 30)+1
        expected = monthly * Decimal(days) / 30
        deviation = abs(amount-expected) / expected * 100
        details.append(f"Mensual orientativo: {pesos(monthly)}. Período: {days} días comerciales. Referencia proporcional: {pesos(expected)}. Cobrado: {pesos(amount)}. Diferencia: {deviation:.2f}%.")
        results.append(finding('21', 'Honorarios orientativos de SECOP', details, deviation > 10))
    except (InvalidOperation, ValueError, ZeroDivisionError):
        results.append(finding('21', 'Honorarios orientativos de SECOP', details + ['No se pudo comparar: falta un valor o período válido.'], missing=True))
    return results
