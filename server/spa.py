from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404


def index(request, path=""):
    index_path = Path(settings.BASE_DIR) / "frontend" / "dist" / "index.html"
    if path or not index_path.exists():
        raise Http404("Page not found")
    return FileResponse(index_path.open("rb"), content_type="text/html; charset=utf-8")
