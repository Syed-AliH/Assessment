from django.conf import settings
from django.http import FileResponse, Http404
from django.urls import include, path, re_path


def spa(request):
    """Serve the built React app. Unknown paths load it too."""
    index = settings.FRONTEND_DIST / "index.html"
    if not index.exists():
        raise Http404("Frontend has not been built")
    response = FileResponse(index.open("rb"), content_type="text/html")
    # Asset names change with each build, so a saved page would keep loading old ones.
    response["Cache-Control"] = "no-cache"
    return response


urlpatterns = [
    path("api/", include("trips.urls")),
    re_path(r"^(?!api/).*$", spa),
]
