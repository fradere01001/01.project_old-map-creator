"""Geocoding outcome classification and provider-safe batch pacing."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol

from geopy.exc import GeocoderServiceError
from geopy.geocoders import Nominatim

from .models import GeocodeResult, Outcome


class Location(Protocol):
    address: str
    latitude: float
    longitude: float


class Geocoder(Protocol):
    def geocode(self, query: str) -> Location | None: ...


class GeocodeStatus(Enum):
    SUCCESS = "success"
    NO_MATCH = "no_match"
    SERVICE_FAILURE = "service_failure"


@dataclass(frozen=True)
class GeocodeOutcome:
    status: GeocodeStatus
    location: Location | None = None
    error: Exception | None = None


def geocode_address(geocoder: Geocoder, address: str) -> GeocodeOutcome:
    try:
        location = geocoder.geocode(address)
    except GeocoderServiceError as error:
        return GeocodeOutcome(GeocodeStatus.SERVICE_FAILURE, error=error)
    if location is None:
        return GeocodeOutcome(GeocodeStatus.NO_MATCH)
    return GeocodeOutcome(GeocodeStatus.SUCCESS, location=location)


@dataclass(frozen=True)
class ProviderProfile:
    provider_id: str = "nominatim-public"
    min_delay_seconds: float = 1.0
    max_retries: int = 2
    user_agent: str = "old-map-creator/2.0"


def make_default_geocoder(profile: ProviderProfile | None = None) -> Geocoder:
    selected = profile or ProviderProfile()
    return Nominatim(user_agent=selected.user_agent)


class BatchGeocoder:
    def __init__(
        self,
        geocoder: Geocoder,
        profile: ProviderProfile | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self.geocoder = geocoder
        self.profile = profile or ProviderProfile()
        self.clock = clock
        self.sleeper = sleeper
        self._last_start: float | None = None

    def _pace(self) -> None:
        now = self.clock()
        if self._last_start is not None:
            remaining = self.profile.min_delay_seconds - (now - self._last_start)
            if remaining > 0:
                self.sleeper(remaining)
                now = self.clock()
        self._last_start = now

    def resolve(self, query: str) -> GeocodeResult:
        last_error: Exception | None = None
        for attempt in range(self.profile.max_retries + 1):
            self._pace()
            outcome = geocode_address(self.geocoder, query)
            if outcome.status is GeocodeStatus.SUCCESS:
                assert outcome.location is not None
                return GeocodeResult(
                    Outcome.RESOLVED,
                    resolved_address=outcome.location.address,
                    latitude=float(outcome.location.latitude),
                    longitude=float(outcome.location.longitude),
                )
            if outcome.status is GeocodeStatus.NO_MATCH:
                return GeocodeResult(Outcome.NO_MATCH)
            last_error = outcome.error
            if attempt < self.profile.max_retries:
                continue
        return GeocodeResult(
            Outcome.SERVICE_FAILURE,
            error=str(last_error) if last_error else "Unknown geocoding service failure",
        )
