import io
import subprocess
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from pypdf import PdfWriter
from valeria.extract import extract_documents, find_supports
from valeria.models import Page, Document
from valeria.normalize import money, parse_date, contract, person, words_money, same_supervisor
from valeria.pdf import read_pdf, ocr_page
from valeria.references import read_reference, Reference, ReferenceRow, contractor_rows, budget_matches
from valeria.rules import evaluate
from valeria.service import csv_safe


def documents():
    docs={k:Document(k,[i+1]) for i,k in enumerate(("certificado","informe","planilla","cuenta"))}
    values={"name":"persona de prueba","cc":"123456789","contract":"142-2026",
            "period_start":"2026-02-01","period_end":"2026-02-28"}
    for i,d in enumerate(docs.values(),1):
        for k,v in values.items(): d.add(k,v,Page(i,""),f"{k}: {v}")
    for key in ("certificado","cuenta"):
        for field,value in {"invoice_number":"2","amount":"9360000","start":"2026-01-17","end":"2026-12-16"}.items():
            docs[key].add(field,value,Page(docs[key].pages[0],""),value)
    for key in ("informe","planilla"):
        for field,value in {"paid":"2026-02-24","pila_number":"9498000000"}.items():
            docs[key].add(field,value,Page(docs[key].pages[0],""),value)
    for field,value in {"pension_month":"2026-02","health_month":"2026-02","contributions":"1086700","affiliates":"1"}.items():
        docs["planilla"].add(field,value,Page(3,""),value)
    return docs


def replace(docs,kind,field,value):
    docs[kind].fields.pop(field,None)
    if value is not None: docs[kind].add(field,value,Page(docs[kind].pages[0],""),str(value))


def run_rule(docs,number,**kwargs):
    return next(x for x in evaluate(docs,[],**kwargs) if x.rule==str(number).zfill(2))


class NormalizationTests(unittest.TestCase):
    def test_money_formats_keep_cents(self):
        for text,expected in [("$9.360.000", "9360000"),("1,086,700","1086700"),("9.360.000,50","9360000.50"),("9,360,000.50","9360000.50")]:
            self.assertEqual(money(text),Decimal(expected))
    def test_dates_are_day_first_unless_year_first(self):
        self.assertEqual(parse_date("01/08/2026"),date(2026,8,1))
        self.assertEqual(parse_date("2026/01/08"),date(2026,1,8))
        self.assertEqual(parse_date("02 de febrero2026"),date(2026,2,2))
        self.assertIsNone(parse_date("31/02/2026"))
    def test_identifiers_and_names(self):
        self.assertEqual(contract("ATENEA 001 – 2026"),"1-2026")
        self.assertEqual(person("ANA MARÍA PÉREZ"),person("PEREZ ANA MARIA"))
        self.assertTrue(same_supervisor("victor javier saavedra mercado","victor saavedra mercado"))
        self.assertFalse(same_supervisor("victor garcia mercado","victor saavedra mercado"))
    def test_words_amounts(self):
        self.assertEqual(words_money("Nueve millones trescientos sesenta mil pesos"),Decimal("9360000"))
        self.assertEqual(words_money("Cuatro millones trescientos sesenta y ocho mil pesos"),Decimal("4368000"))
        self.assertIsNone(words_money("Valor sin detallar"))


class RuleTests(unittest.TestCase):
    def test_missing_is_not_validated(self):
        d=documents(); replace(d,"informe","cc",None)
        self.assertEqual(run_rule(d,2).status,"REVISAR")
    def test_conflicting_values_not_first_match(self):
        d=documents(); d["informe"].add("cc","987654321",Page(2,""),"CC 987654321")
        self.assertEqual(run_rule(d,2).status,"REVISAR")
    def test_exact_period_detects_partial_mismatch(self):
        d=documents(); replace(d,"informe","period_end","2026-02-02")
        self.assertEqual(run_rule(d,1).status,"VALIDADO")
        self.assertEqual(run_rule(d,18).status,"REVISAR")
    def test_equal_invalid_payment_dates_do_not_pass(self):
        d=documents()
        for kind in ("informe","planilla"): replace(d,kind,"paid","FECHA INVÁLIDA: 31/02/2026")
        self.assertEqual(run_rule(d,8).status,"REVISAR")
    def test_planilla_health_and_pension_months_both_matter(self):
        d=documents(); replace(d,"planilla","health_month","2026-01")
        self.assertEqual(run_rule(d,1).status,"REVISAR")
        self.assertEqual(run_rule(d,15).status,"REVISAR")
    def test_aportes_boundary(self):
        d=documents(); replace(d,"planilla","contributions","1086583.68")
        self.assertEqual(run_rule(d,9).status,"VALIDADO")
        replace(d,"planilla","contributions","1086583.67")
        self.assertEqual(run_rule(d,9).status,"REVISAR")
    def test_multi_affiliate_total_not_accepted(self):
        d=documents(); replace(d,"planilla","affiliates","2")
        self.assertEqual(run_rule(d,9).status,"REVISAR")
    def test_first_invoice_if_either_document_says_one(self):
        d=documents(); replace(d,"certificado","invoice_number","1")
        self.assertIn("Primera cuenta",run_rule(d,13).message)
        self.assertEqual(run_rule(d,13).status,"REVISAR")
    def test_unknown_consecutive_not_exempt(self):
        d=documents(); replace(d,"cuenta","invoice_number",None)
        self.assertEqual(run_rule(d,13).status,"REVISAR")
    def test_word_and_numeric_difference(self):
        d=documents(); replace(d,"cuenta","amount_words","9000000")
        f=run_rule(d,14)
        self.assertIn("distinto al numérico",f.message)
        self.assertEqual(f.category,"Inconsistencia")
    def test_signatures_never_inferred_from_text(self):
        d=documents()
        self.assertEqual(run_rule(d,19).status,"REVISAR")
        self.assertFalse(any(e.get("document","").startswith("Planilla") for e in run_rule(d,19).evidence))
    def test_rules_keep_source_numbering(self):
        rules=[f.rule for f in evaluate(documents(),[])]
        self.assertEqual(rules,[str(i).zfill(2) for i in range(1,17)]+["18","19"])
    def test_february_full_month_is_30_commercial_days(self):
        d=documents()
        monthly=read_reference(b"documento,valor mensual\n123456789,9360000\n","mensual.csv")
        self.assertEqual(run_rule(d,16,monthly=monthly).status,"VALIDADO")
    def test_partial_january_is_14_commercial_days(self):
        d=documents()
        for field,value in {"period_start":"2026-01-17","period_end":"2026-01-31","amount":"4368000"}.items(): replace(d,"cuenta",field,value)
        monthly=read_reference(b"documento,valor mensual\n123456789,9360000\n","mensual.csv")
        result=run_rule(d,16,monthly=monthly)
        self.assertEqual(result.status,"VALIDADO"); self.assertIn("14 días",result.message)
    def test_monthly_reference_never_uses_nearest_id_or_crp_total(self):
        d=documents(); ref=read_reference(b"documento,valor CRP\n123456789,9360000\n","mensual.csv")
        self.assertEqual(run_rule(d,16,monthly=ref).status,"REVISAR")


class ReferenceTests(unittest.TestCase):
    def test_swapped_cdp_crp_fail_with_headers(self):
        row=ReferenceRow("Data",2,["443","115","50001234"],["Número de CDP","Número de CRP","N° Interno CRP"])
        self.assertEqual(budget_matches(row,"115","443","50001234"),[False,False,True])
    def test_cc_substring_not_a_match(self):
        ref=Reference("test",[ReferenceRow("Data",1,["91234567890"],[])])
        self.assertFalse(contractor_rows(ref,"123456789",None))
    def test_values_not_borrowed_from_another_person(self):
        ref=read_reference(b"documento,cdp,crp,codigo interno\n123456789,115,443,50001234\n987654321,116,444,50005678\n","crp.csv")
        d=documents(); replace(d,"certificado","budget","115|443|50005678")
        self.assertEqual(run_rule(d,11,crp=ref).status,"REVISAR")
    def test_csv_formula_injection_escaped(self):
        self.assertTrue(csv_safe("=HYPERLINK(1)").startswith("'"))


class ExtractionTests(unittest.TestCase):
    def test_table_number_not_template_version(self):
        page=Page(1,"F1_P2_F Version 4 CC 123456789 ATENEA 142-2026", "F1_P2_F\nNo. FACTURA O CUENTA DE COBRO\n  002   01/02/2026 - 28/02/2026  $9.360.000\nVALOR TOTAL: $9.360.000")
        docs=extract_documents([page])
        self.assertEqual(docs["certificado"].get("invoice_number"),"2")
    def test_mentions_in_report_do_not_count_as_supports(self):
        page=Page(1,"F1_P10_C Se revisaron registro unico tributario y certificado de registro presupuestal.")
        extract_documents([page])
        self.assertEqual(find_supports([page]),{})
    def test_payment_key_not_used_as_planilla_number(self):
        page=Page(1,"F1_P10_C PAGO DE LA SEGURIDAD SOCIAL 86190000 (Pago) - 9498000000 (Planilla) - 24/02/2026 PORCENTAJE DE AVANCE")
        result=extract_documents([page])["informe"]
        self.assertEqual(result.get("pila_number"),"9498000000")
    def test_non_pdf_rejected(self):
        with self.assertRaises(ValueError): read_pdf(b"malformed")
    def test_blank_page_is_flagged(self):
        writer=PdfWriter(); writer.add_blank_page(width=600,height=800)
        buffer=io.BytesIO(); writer.write(buffer)
        pages=read_pdf(buffer.getvalue(),ocr=False)
        self.assertTrue(pages[0].issue)
    def test_no_ocr_binary_is_explicit(self):
        with patch("valeria.pdf.shutil.which",return_value=None):
            self.assertIn("OCR no disponible",ocr_page(b"",1)[1])
    def test_parser_timeout_is_reported(self):
        with patch("valeria.pdf.subprocess.run",side_effect=subprocess.TimeoutExpired("pdf",180)):
            with self.assertRaisesRegex(ValueError,"tres minutos"): read_pdf(b"%PDF-1.4")


if __name__ == "__main__": unittest.main()
