import unittest
import io
from pathlib import Path
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from valeria.models import Review, Page
from valeria.rules import evaluate
from tests.test_rules import documents


class AppTests(unittest.TestCase):
    def test_initial_screen_without_secrets(self):
        with patch("pathlib.Path.read_bytes",side_effect=FileNotFoundError):
            app=AppTest.from_file(str(Path(__file__).parents[1]/"app.py"),default_timeout=20).run()
        self.assertEqual(len(app.exception),0)
        self.assertEqual(app.title[0].value,"ValerIA")
        self.assertTrue(app.button[0].disabled)

    def test_upload_run_downloads_and_changed_input_clears_report(self):
        pdf=io.BytesIO(b"%PDF-1.4 synthetic"); pdf.name="ficticio.pdf"
        docs=documents()
        result=Review("ficticio.pdf","hash","2026-02-28","test",docs,[Page(1,"texto")],evaluate(docs,[]),
                      {"crp":"No cargada","valor_mensual":"No cargada"})
        def uploader(label,**kwargs):
            return pdf if kwargs.get("key")=="account_pdf" else None
        with patch("streamlit.file_uploader",side_effect=uploader), patch("valeria.service.analyze",return_value=result), \
             patch("valeria.pdf.render_page",return_value=None), patch("pathlib.Path.read_bytes",side_effect=FileNotFoundError):
            app=AppTest.from_file(str(Path(__file__).parents[1]/"app.py"),default_timeout=20).run()
            app.button[0].click().run()
            self.assertEqual(len(app.exception),0)
            self.assertEqual(len(app.metric),4)
            self.assertEqual(len(app.get("download_button")),4)
            pdf.seek(0); pdf.write(b"%PDF-1.4 different")
            app.run()
            self.assertEqual(len(app.metric),0)


if __name__ == "__main__": unittest.main()
