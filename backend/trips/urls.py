from django.urls import path

from .views import AssessView, GeocodeView, HeatmapView, PlanView

urlpatterns = [
    path("geocode", GeocodeView.as_view()),
    path("trips/plan", PlanView.as_view()),
    path("trips/<str:analysis_id>/assess", AssessView.as_view()),
    path("trips/<str:analysis_id>/heatmap", HeatmapView.as_view()),
]
