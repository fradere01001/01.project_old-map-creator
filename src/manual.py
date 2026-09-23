"""Interactive one-address-at-a-time collection."""

from __future__ import annotations

from typing import Callable, Protocol

from .exporters import CheckpointError
from .geocoding import GeocodeStatus, Geocoder, geocode_address


class ManualStore(Protocol):
    destination: object
    location_count: int
    saved_count: int

    def add_location(self, location: object) -> bool: ...
    def checkpoint(self) -> None: ...


def _ask_choice(prompt: str, choices: dict[str, str], input_fn: Callable[[str], str], output_fn: Callable[[str], None]) -> str:
    while True:
        answer = input_fn(prompt).strip().lower()
        if answer in choices:
            return choices[answer]
        output_fn(f"Choose one of: {', '.join(choices)}.")


def _finish(store: ManualStore, output_fn: Callable[[str], None]) -> bool:
    try:
        store.checkpoint()
    except CheckpointError as error:
        output_fn(str(error))
        output_fn(
            f"Last recoverable output: {store.destination} ({store.saved_count} saved row(s))."
            if store.saved_count else "No recoverable output was published."
        )
        return False
    output_fn(f"Saved {store.saved_count} location row(s) to {store.destination}.")
    return True


def run_session(
    geocoder: Geocoder,
    store: ManualStore,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> bool:
    try:
        while True:
            address = input_fn("Enter a place (or 'finish'): ").strip()
            if address.lower() in {"finish", "no"}:
                return _finish(store, output_fn)
            if not address:
                output_fn("Enter a place or type 'finish'.")
                continue
            while True:
                outcome = geocode_address(geocoder, address)
                if outcome.status is GeocodeStatus.SUCCESS:
                    assert outcome.location is not None
                    added = store.add_location(outcome.location)
                    if not added:
                        output_fn(f"Already exists: {outcome.location.address}")
                        break
                    try:
                        store.checkpoint()
                    except CheckpointError as error:
                        output_fn(str(error))
                        output_fn(
                            f"Collection stopped. Last recoverable output: {store.destination} "
                            f"({store.saved_count} saved row(s))."
                            if store.saved_count
                            else "Collection stopped. No recoverable output was published."
                        )
                        return False
                    output_fn(f"Saved: {outcome.location.address}")
                    break
                if outcome.status is GeocodeStatus.NO_MATCH:
                    output_fn(f"No match found for: {address}")
                    action = _ask_choice(
                        "Retry, correct, skip, or finish? [r/c/s/f]: ",
                        {"r": "retry", "retry": "retry", "c": "correct", "correct": "correct", "s": "skip", "skip": "skip", "f": "finish", "finish": "finish"},
                        input_fn,
                        output_fn,
                    )
                    if action == "retry":
                        continue
                    if action == "correct":
                        corrected = input_fn("Corrected place: ").strip()
                        if corrected:
                            address = corrected
                        else:
                            output_fn("The corrected place cannot be empty.")
                        continue
                    if action == "skip":
                        break
                    return _finish(store, output_fn)
                output_fn(f"Geocoding service failure: {outcome.error}")
                action = _ask_choice(
                    "Retry, skip, or finish? [r/s/f]: ",
                    {"r": "retry", "retry": "retry", "s": "skip", "skip": "skip", "f": "finish", "finish": "finish"},
                    input_fn,
                    output_fn,
                )
                if action == "retry":
                    continue
                if action == "skip":
                    break
                return _finish(store, output_fn)
    except KeyboardInterrupt:
        output_fn(
            f"Interrupted. Recoverable output: {store.destination} ({store.saved_count} saved row(s))."
            if store.saved_count
            else "Interrupted. No location rows were saved."
        )
        return False
