import csv
import io
import unittest
from valeria.secop import REFERENCE, COLUMNS, select_record, name_matches, compare_with_base
from valeria.models import Document, Page
from valeria.extract import extract_documents

class SecopTests(unittest.TestCase):
    def test_names(self):
        self.assertTrue(name_matches("LUCIA ANDREA PEREZ GOMEZ", "Lucía Pérez Gómez"))
        self.assertTrue(name_matches("Gomez Perez Lucia Andrea", "Lucía Andrea Pérez Gómez"))
        self.assertFalse(name_matches("Lucia Andrea Ruiz Gomez", "Lucía Andrea Pérez Gómez"))
        self.assertFalse(name_matches("Lucia Andrea", "Lucía Andrea Pérez Gómez"))

    def test_conflicting_rows(self):
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=[REFERENCE, COLUMNS["supervisor"]])
        writer.writeheader()
        writer.writerow({REFERENCE:"ATENEA-001-2026", COLUMNS["supervisor"]:"PERSONA UNO"})
        writer.writerow({REFERENCE:"ATENEA-001-2026", COLUMNS["supervisor"]:"PERSONA DOS"})
        with self.assertRaises(ValueError):
            select_record(output.getvalue().encode(), "atenea 001 2026")

    def test_outage_is_review(self):
        docs = {k: Document(k) for k in ("certificado","informe","cuenta","planilla")}
        findings = compare_with_base(docs, {"error":"Consulta no disponible"})
        self.assertEqual([f.rule for f in findings], ["10","20","16"])
        self.assertTrue(all(f.status == "REVISAR" for f in findings))

    def test_monthly_secop_rule_16(self):
        docs = {k: Document(k) for k in ("certificado","informe","cuenta","planilla")}
        page = Page(1, "")
        for key, value in {"amount":"1500", "period_start":"2026-10-01", "period_end":"2026-10-31"}.items():
            docs["cuenta"].add(key, value, page, "")
        def check(monthly):
            return next(f for f in compare_with_base(docs, {"record":{"monthly":monthly}}) if f.rule == "16")
        self.assertEqual(check("1500").status, "VALIDADO")
        self.assertEqual(check("1000").category, "Inconsistencia")
        self.assertEqual(check("").category, "Evidencia incompleta")
        docs["cuenta"].fields["amount"][0].value = "750"
        docs["cuenta"].fields["period_end"][0].value = "2026-10-15"
        partial = check("1500")
        self.assertEqual(partial.status, "VALIDADO")
        self.assertIn("15 días", partial.message)

    def test_report_planilla_and_object(self):
        docs = extract_documents([Page(1, "F1_P10_C PAGO DE LA SEGURIDAD SOCIAL Planilla 1234567890. Clave de pago 987654321. PORCENTAJE DE AVANCE 25%. OBJETO DEL CONTRATO O CONVENIO Prestar servicios. OBLIGACIONES Y/O COMPROMISOS")])
        self.assertEqual(docs["informe"].get("pila_number"), "1234567890")
        self.assertEqual(docs["informe"].get("object"), "prestar servicios.")

if __name__ == "__main__":
    unittest.main()
