from datetime import datetime, timedelta, timezone

from rest_framework import serializers

from .domain.geo import haversine_miles

MAX_LOAD_LB = 80_000
INTERVALS = (10, 25, 50)
MAX_DEPARTURE_DAYS = 14
# Local clocks run at most 12 hours behind timezone.utc. This is a coarse check, because
# the origin's zone is only known once the route comes back: see analyze_trip.
LOCAL_CLOCK_MARGIN = timedelta(hours=12)
MIN_TRIP_MILES = 1.0


class ForecastSubmissionSerializer(serializers.Serializer):
    """Forecasts from the browser, in the order the plan asked for them."""

    locations = serializers.ListField(allow_empty=True, default=list)
    failure = serializers.ChoiceField(choices=("rate_limited", "unavailable"), required=False)
    reason = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class PlaceSerializer(serializers.Serializer):
    label = serializers.CharField(max_length=200, required=False, allow_blank=True)
    lat = serializers.FloatField(min_value=-90, max_value=90)
    lon = serializers.FloatField(min_value=-180, max_value=180)


class TripRequestSerializer(serializers.Serializer):
    origin = PlaceSerializer()
    destination = PlaceSerializer()
    departure = serializers.CharField(required=False, allow_null=True, default=None)
    load_lb = serializers.FloatField(min_value=0, max_value=MAX_LOAD_LB)
    interval_miles = serializers.ChoiceField(choices=INTERVALS, default=25)

    def validate_departure(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            departure = datetime.fromisoformat(value)
        except ValueError:
            raise serializers.ValidationError("Enter a valid date and time.") from None
        if departure.tzinfo is not None:
            raise serializers.ValidationError("Send origin-local time with no timezone.utc offset.")
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if departure < now - LOCAL_CLOCK_MARGIN:
            raise serializers.ValidationError("Departure cannot be in the past.")
        if departure > now + timedelta(days=MAX_DEPARTURE_DAYS) + LOCAL_CLOCK_MARGIN:
            raise serializers.ValidationError(
                f"Departure must be within {MAX_DEPARTURE_DAYS} days, the range the forecast can cover."
            )
        return departure

    def validate(self, attrs):
        origin = (attrs["origin"]["lat"], attrs["origin"]["lon"])
        destination = (attrs["destination"]["lat"], attrs["destination"]["lon"])
        if haversine_miles(origin, destination) < MIN_TRIP_MILES:
            raise serializers.ValidationError(
                {"destination": ["Origin and destination are the same place."]}
            )
        return attrs
