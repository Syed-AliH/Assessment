"""Build providers from settings, so swapping a vendor touches only this file."""
from django.conf import settings
from django.utils.module_loading import import_string

from .base import Geocoder, RoutingProvider, WeatherProvider
from .open_meteo import OpenMeteoClient
from .tomtom import TomTomClient


def routing_provider() -> RoutingProvider:
    if settings.ROUTING_PROVIDER:
        return import_string(settings.ROUTING_PROVIDER)()
    return TomTomClient(settings.TOMTOM_API_KEY)


def geocoder() -> Geocoder:
    if settings.GEOCODER:
        return import_string(settings.GEOCODER)()
    return TomTomClient(settings.TOMTOM_API_KEY)


def weather_provider() -> WeatherProvider:
    return OpenMeteoClient(settings.OPEN_METEO_API_KEY)
