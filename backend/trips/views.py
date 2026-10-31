from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .providers.registry import geocoder, routing_provider
from .serializers import ForecastSubmissionSerializer, TripRequestSerializer
from .services.analyze import TripRequest, WeatherFailure, assess_trip, plan_trip
from .services.heatmap import build_heatmap

MIN_QUERY_LENGTH = 3
MAX_QUERY_LENGTH = 120


class GeocodeView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "geocode"

    def get(self, request):
        query = request.query_params.get("q", "").strip()[:MAX_QUERY_LENGTH]
        if len(query) < MIN_QUERY_LENGTH:
            return Response({"results": []})
        return Response({
            "results": [
                {"label": place.label, "lat": place.lat, "lon": place.lon}
                for place in geocoder().search(query)
            ]
        })


class PlanView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "plan"

    def post(self, request):
        serializer = TripRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        trip = TripRequest(
            origin=(data["origin"]["lat"], data["origin"]["lon"]),
            destination=(data["destination"]["lat"], data["destination"]["lon"]),
            departure=data["departure"],
            load_lb=data["load_lb"],
            interval_miles=data["interval_miles"],
        )
        return Response(plan_trip(trip, routing_provider()))


class AssessView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "forecast"

    def post(self, request, analysis_id: str):
        serializer = ForecastSubmissionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        failure = None
        if data.get("failure"):
            failure = WeatherFailure(
                rate_limited=data["failure"] == "rate_limited", reason=data["reason"]
            )
        return Response(assess_trip(analysis_id, data["locations"], failure))


class HeatmapView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "forecast"

    def post(self, request, analysis_id: str):
        serializer = ForecastSubmissionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(build_heatmap(analysis_id, serializer.validated_data["locations"]))
