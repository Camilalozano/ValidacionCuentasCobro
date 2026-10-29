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
        self.assertEqual([f.rule for f in findings], ["10","20","21"])
        self.assertTrue(all(f.status == "REVISAR" for f in findings))

    def test_report_planilla_and_object(self):
        docs = extract_documents([Page(1, "F1_P10_C PAGO DE LA SEGURIDAD SOCIAL Planilla 1234567890. Clave de pago 987654321. PORCENTAJE DE AVANCE 25%. OBJETO DEL CONTRATO O CONVENIO Prestar servicios. OBLIGACIONES Y/O COMPROMISOS")])
        self.assertEqual(docs["informe"].get("pila_number"), "1234567890")
        self.assertEqual(docs["informe"].get("object"), "prestar servicios.")

if __name__ == "__main__":
    unittest.main()
