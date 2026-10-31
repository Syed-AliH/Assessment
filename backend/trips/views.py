from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .providers.registry import geocoder, routing_provider, weather_provider
from .serializers import TripRequestSerializer
from .services.analyze import TripRequest, analyze_trip
from .services.heatmap import cached_heatmap

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


class AnalyzeView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "analyze"

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
        return Response(analyze_trip(trip, routing_provider(), weather_provider()))


class HeatmapView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "analyze"

    def get(self, request, analysis_id: str):
        return Response(cached_heatmap(analysis_id, weather_provider()))
