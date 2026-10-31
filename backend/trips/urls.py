from django.urls import path

from .views import AnalyzeView, GeocodeView, HeatmapView

urlpatterns = [
    path("geocode", GeocodeView.as_view()),
    path("trips/analyze", AnalyzeView.as_view()),
    path("trips/<str:analysis_id>/heatmap", HeatmapView.as_view()),
]
