import importlib.util
import struct
import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.config import Settings
from backend.source_preview import PreviewPageNotFoundError, render_source_page


@unittest.skipUnless(importlib.util.find_spec("pymupdf"), "PDF preview backend dependency required")
class SourcePreviewTests(unittest.TestCase):
    def pdf(self, width=595, height=842):
        import pymupdf as fitz
        with fitz.open() as document:
            page = document.new_page(width=width, height=height)
            page.insert_text((50, 60), "Original page one")
            page = document.new_page(width=width, height=height)
            page.insert_text((50, 60), "Original page two")
            return document.tobytes()

    def test_renders_selected_page_as_png_and_rejects_missing_pages(self):
        with TemporaryDirectory() as root:
            path = Path(root) / "source.pdf"
            path.write_bytes(self.pdf())
            first = render_source_page(path, 1)
            second = render_source_page(path, 2)
            self.assertTrue(second.startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertNotEqual(first, second)
            for page in [0, 3]:
                with self.assertRaises(PreviewPageNotFoundError):
                    render_source_page(path, page)

    def test_large_pdf_geometry_is_pixel_and_edge_bounded(self):
        with TemporaryDirectory() as root:
            path = Path(root) / "large.pdf"
            path.write_bytes(self.pdf(width=20000, height=15000))
            png = render_source_page(path, 1)
        width, height = struct.unpack(">II", png[16:24])
        self.assertLessEqual(width * height, 2_000_000)
        self.assertLessEqual(max(width, height), 4096)

    def test_preview_has_same_authentication_as_original_pdf(self):
        with TemporaryDirectory() as root:
            settings = Settings(data_dir=Path(root), builtin_profile_dir=Path(__file__).resolve().parents[1] / "profiles", api_keys=(("reader", "reader-key", "read"), ("writer", "writer-key", "write")))
            app = create_app(settings, start_workers=False)
            with TestClient(app) as client:
                task = app.state.service.create_task("source.pdf", BytesIO(self.pdf()), "manual_query")
                route = f'/v1/tasks/{task["id"]}/source/pages/2.png'
                self.assertEqual(401, client.get(route).status_code)
                headers = {"Authorization": "Bearer reader-key"}
                image = client.get(route, headers=headers)
                self.assertEqual(200, image.status_code)
                self.assertEqual("image/png", image.headers["content-type"])
                self.assertEqual("no-store", image.headers["cache-control"])
                self.assertEqual(404, client.get(route.replace("2.png", "3.png"), headers=headers).status_code)
                self.assertEqual(404, client.get('/v1/tasks/unknown/source/pages/1.png', headers=headers).status_code)

    def test_corrupt_pdf_fails_as_client_error(self):
        with TemporaryDirectory() as root:
            settings = Settings(data_dir=Path(root), builtin_profile_dir=Path(__file__).resolve().parents[1] / "profiles")
            app = create_app(settings, start_workers=False)
            with TestClient(app) as client:
                task = app.state.service.create_task("bad.pdf", BytesIO(b"%PDF-1.7\ninvalid"), "manual_query")
                result = client.get(f'/v1/tasks/{task["id"]}/source/pages/1.png')
                self.assertEqual(422, result.status_code)
                self.assertEqual("source_page_render_failed", result.json()["detail"])


if __name__ == "__main__":
    unittest.main()
