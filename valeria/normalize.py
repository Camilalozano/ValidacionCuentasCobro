import calendar
import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation

MONTHS = {m: i for i, m in enumerate(
    ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
     "septiembre", "octubre", "noviembre", "diciembre"], 1)}
MONTHS["setiembre"] = 9
MONTH_PATTERN = "(?:" + "|".join(MONTHS) + ")"
DATE_PATTERN = rf"(?:\d{{4}}[/.\-]\d{{1,2}}[/.\-]\d{{1,2}}|\d{{1,2}}[/.\-]\d{{1,2}}[/.\-]\d{{4}}|\d{{1,2}}\s*(?:de\s*)?{MONTH_PATTERN}\s*(?:de\s*)?\d{{4}})"


def norm(value):
    value = unicodedata.normalize("NFKD", str(value))
    value = "".join(c for c in value if not unicodedata.combining(c)).lower()
    return re.sub(r"[ \t]+", " ", value.replace("–", "-").replace("—", "-").replace("\xa0", " ")).strip()


def flat(value):
    return re.sub(r"\s+", " ", norm(value)).strip()


def digits(value):
    return re.sub(r"\D", "", str(value))


def person(value):
    return " ".join(sorted(re.findall(r"[a-z]+", norm(value))))


def same_supervisor(left, right):
    a, b = flat(left).split(), flat(right).split()
    if person(left) == person(right): return True
    # First name and two surnames must remain; only middle names may be omitted.
    return len(a)>=3 and len(b)>=3 and a[0]==b[0] and a[-2:]==b[-2:] and (set(a)<=set(b) or set(b)<=set(a))


def contract(value):
    found = re.search(r"(?:atenea\s*[- ]*\s*)?(\d{1,6})\s*-\s*(20\d{2})", flat(value))
    return f"{int(found[1])}-{found[2]}" if found else None


def money(value):
    raw = re.sub(r"[^\d.,\-]", "", str(value)).strip()
    if not raw or raw in {"-", ".", ","}:
        return None
    # Colombian and PILA formats, with optional cents. Never remove decimal cents.
    if "," in raw and "." in raw:
        decimal_sep = "," if raw.rfind(",") > raw.rfind(".") else "."
        raw = raw.replace("." if decimal_sep == "," else ",", "").replace(decimal_sep, ".")
    elif "," in raw or "." in raw:
        sep = "," if "," in raw else "."
        parts = raw.split(sep)
        raw = "".join(parts) if all(len(x) == 3 for x in parts[1:]) else "".join(parts[:-1]) + "." + parts[-1]
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def parse_date(value):
    raw = flat(value)
    try:
        m = re.fullmatch(r"(\d{4})[/.\-](\d{1,2})[/.\-](\d{1,2})", raw)
        if m:
            return date(int(m[1]), int(m[2]), int(m[3]))
        m = re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})", raw)
        if m:
            return date(int(m[3]), int(m[2]), int(m[1]))
        m = re.fullmatch(rf"(\d{{1,2}})\s*(?:de\s*)?({MONTH_PATTERN})\s*(?:de\s*)?(\d{{4}})", raw)
        if m:
            return date(int(m[3]), MONTHS[m[2]], int(m[1]))
    except ValueError:
        pass
    return None


def ranges(value):
    text = flat(value)
    matches = []
    for m in re.finditer(rf"({DATE_PATTERN})\s*(?:-|al|a)\s*({DATE_PATTERN})", text):
        matches.append((parse_date(m[1]), parse_date(m[2]), m[0]))
    for m in re.finditer(rf"(?:del?\s+)?(\d{{1,2}})\s+(?:al|a)\s+(\d{{1,2}})\s+(?:de\s+)?({MONTH_PATTERN})\s*(?:de\s*)?(20\d{{2}})", text):
        matches.append((parse_date(f"{m[1]}/{MONTHS[m[3]]}/{m[4]}"),
                        parse_date(f"{m[2]}/{MONTHS[m[3]]}/{m[4]}"), m[0]))
    return matches


def is_full_month(start, end):
    return (start.year, start.month) == (end.year, end.month) and start.day == 1 and end.day == calendar.monthrange(end.year, end.month)[1]


def pesos(value):
    return "$" + f"{Decimal(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


_NUMBERS = {"cero":0,"un":1,"uno":1,"una":1,"dos":2,"tres":3,"cuatro":4,"cinco":5,
    "seis":6,"siete":7,"ocho":8,"nueve":9,"diez":10,"once":11,"doce":12,"trece":13,
    "catorce":14,"quince":15,"dieciseis":16,"diecisiete":17,"dieciocho":18,"diecinueve":19,
    "veinte":20,"veintiuno":21,"veintiun":21,"veintidos":22,"veintitres":23,"veinticuatro":24,
    "veinticinco":25,"veintiseis":26,"veintisiete":27,"veintiocho":28,"veintinueve":29,
    "treinta":30,"cuarenta":40,"cincuenta":50,"sesenta":60,"setenta":70,"ochenta":80,"noventa":90,
    "cien":100,"ciento":100,"doscientos":200,"trescientos":300,"cuatrocientos":400,"quinientos":500,
    "seiscientos":600,"setecientos":700,"ochocientos":800,"novecientos":900}


def words_money(value):
    tokens = re.findall(r"[a-z]+", flat(value).split("pesos")[0])
    total = section = 0
    seen = False
    for token in tokens:
        if token in _NUMBERS:
            section += _NUMBERS[token]; seen = True
        elif token == "mil":
            section = (section or 1) * 1000; seen = True
        elif token in {"millon", "millones"}:
            total += (section or 1) * 1_000_000; section = 0; seen = True
        elif token not in {"y", "de"}:
            return None
    return Decimal(total + section) if seen else None
