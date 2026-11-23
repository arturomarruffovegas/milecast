import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import RequestFactory, override_settings

from server.wsgi import application


class MapPageTests(unittest.TestCase):
    def test_planner_page_sends_site_origin_to_https_tile_provider(self):
        with TemporaryDirectory() as root, override_settings(BASE_DIR=Path(root)):
            index = Path(root) / "frontend" / "dist" / "index.html"
            index.parent.mkdir(parents=True)
            index.write_text("<html></html>", encoding="utf-8")
            response = application.get_response(RequestFactory().get("/", secure=True))
            try:
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Referrer-Policy"], "strict-origin-when-cross-origin")
            finally:
                response.close()
