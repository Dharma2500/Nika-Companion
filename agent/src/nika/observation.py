"""Strict, versioned validation for client-side Minecraft observations."""

from __future__ import annotations

import json
import math
import re
from typing import Any

OBSERVATION_SCHEMA_VERSION = 1
MAX_OBSERVATION_BYTES = 8 * 1024

_RESOURCE_LOCATION = re.compile(r"^[a-z0-9_.-]+:[a-z0-9/._-]+$")
_MOD_VERSION = re.compile(r"^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$")

_TOP_LEVEL_KEYS = {"schema_version", "client", "world", "player"}
_CLIENT_KEYS = {"minecraft_version", "mod_version"}
_WORLD_KEYS = {"dimension"}
_PLAYER_KEYS = {
    "x",
    "y",
    "z",
    "health",
    "food_level",
    "selected_item",
}


class ObservationValidationError(ValueError):
    """Raised when an observation does not match the supported v1 contract."""


def _reject_constant(value: str) -> None:
    raise ObservationValidationError(f"Non-standard JSON numeric constant: {value}.")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ObservationValidationError(f"Duplicate JSON property: {key}.")
        result[key] = value
    return result


def decode_observation(body: bytes) -> dict[str, Any]:
    """Decode UTF-8 JSON while rejecting duplicate keys and non-finite constants."""
    if not isinstance(body, bytes):
        raise ObservationValidationError("Observation body must be bytes.")
    if not body:
        raise ObservationValidationError("Observation body must not be empty.")
    if len(body) > MAX_OBSERVATION_BYTES:
        raise ObservationValidationError("Observation body exceeds the 8 KiB limit.")

    try:
        decoded = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except ObservationValidationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ObservationValidationError("Observation body is not valid UTF-8 JSON.") from error

    return validate_observation(decoded)


def _require_object(value: Any, name: str, expected_keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ObservationValidationError(f"{name} must be a JSON object.")
    actual_keys = set(value)
    missing = expected_keys - actual_keys
    extra = actual_keys - expected_keys
    if missing:
        raise ObservationValidationError(
            f"{name} is missing required properties: {', '.join(sorted(missing))}."
        )
    if extra:
        raise ObservationValidationError(
            f"{name} contains unsupported properties: {', '.join(sorted(extra))}."
        )
    return value


def _require_number(
    value: Any,
    name: str,
    minimum: float,
    maximum: float,
) -> float:
    if type(value) not in (int, float):
        raise ObservationValidationError(f"{name} must be a JSON number.")
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ObservationValidationError(
            f"{name} must be finite and between {minimum:g} and {maximum:g}."
        )
    return number


def _require_resource_location(value: Any, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) > 128
        or _RESOURCE_LOCATION.fullmatch(value) is None
    ):
        raise ObservationValidationError(
            f"{name} must be a valid namespaced Minecraft identifier."
        )
    return value


def validate_observation(value: Any) -> dict[str, Any]:
    """Validate and return a normalized copy of a Minecraft observation v1."""
    payload = _require_object(value, "observation", _TOP_LEVEL_KEYS)

    schema_version = payload["schema_version"]
    if type(schema_version) is not int or schema_version != OBSERVATION_SCHEMA_VERSION:
        raise ObservationValidationError("Unsupported observation schema version.")

    client = _require_object(payload["client"], "client", _CLIENT_KEYS)
    if client["minecraft_version"] != "1.21.11":
        raise ObservationValidationError("Unsupported Minecraft client version.")
    mod_version = client["mod_version"]
    if not isinstance(mod_version, str) or _MOD_VERSION.fullmatch(mod_version) is None:
        raise ObservationValidationError("client.mod_version must use numeric semver.")

    world = _require_object(payload["world"], "world", _WORLD_KEYS)
    dimension = _require_resource_location(world["dimension"], "world.dimension")

    player = _require_object(payload["player"], "player", _PLAYER_KEYS)
    x = _require_number(player["x"], "player.x", -30_000_000, 30_000_000)
    y = _require_number(player["y"], "player.y", -2048, 2048)
    z = _require_number(player["z"], "player.z", -30_000_000, 30_000_000)
    health = _require_number(player["health"], "player.health", 0, 1024)

    food_level = player["food_level"]
    if type(food_level) is not int or not 0 <= food_level <= 20:
        raise ObservationValidationError("player.food_level must be an integer from 0 to 20.")

    selected_item = _require_resource_location(
        player["selected_item"], "player.selected_item"
    )

    return {
        "schema_version": OBSERVATION_SCHEMA_VERSION,
        "client": {
            "minecraft_version": "1.21.11",
            "mod_version": mod_version,
        },
        "world": {"dimension": dimension},
        "player": {
            "x": x,
            "y": y,
            "z": z,
            "health": health,
            "food_level": food_level,
            "selected_item": selected_item,
        },
    }
