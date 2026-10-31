from django.conf import settings
from django.http import FileResponse, Http404
from django.urls import include, path, re_path


def spa(request):
    """Serve the built React app. Unknown paths load it too."""
    index = settings.FRONTEND_DIST / "index.html"
    if not index.exists():
        raise Http404("Frontend has not been built")
    return FileResponse(index.open("rb"), content_type="text/html")


urlpatterns = [
    path("api/", include("trips.urls")),
    re_path(r"^(?!api/).*$", spa),
]
