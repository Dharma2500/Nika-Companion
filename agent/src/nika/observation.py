"""Strict, versioned validation for client-side Minecraft observations."""

from __future__ import annotations

import json
import math
import re
from typing import Any

OBSERVATION_SCHEMA_VERSION = 2
SUPPORTED_OBSERVATION_SCHEMA_VERSIONS = frozenset({1, 2})
MAX_OBSERVATION_BYTES = 8 * 1024
MAX_BLOCK_SAMPLE_BLOCKS = 32
MAX_BLOCK_PROPERTIES = 12
BLOCK_SAMPLE_RANGE = {"x": 2, "y": 1, "z": 2}
BLOCK_SAMPLE_POSITION_COUNT = 75

_RESOURCE_LOCATION = re.compile(r"^[a-z0-9_.-]+:[a-z0-9/._-]+$")
_MOD_VERSION = re.compile(r"^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$")
_PROPERTY_NAME = re.compile(r"^[a-z0-9_]{1,64}$")
_PROPERTY_VALUE = re.compile(r"^[a-z0-9_.-]{1,64}$")

_TOP_LEVEL_KEYS_V1 = {"schema_version", "client", "world", "player"}
_TOP_LEVEL_KEYS_V2 = {"schema_version", "client", "world", "player"}
_CLIENT_KEYS = {"minecraft_version", "mod_version"}
_WORLD_KEYS_V1 = {"dimension"}
_WORLD_KEYS_V2 = {"dimension", "block_sample"}
_PLAYER_KEYS = {
    "x",
    "y",
    "z",
    "health",
    "food_level",
    "selected_item",
}


class ObservationValidationError(ValueError):
    """Raised when an observation does not match a supported contract."""


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
    """Decode bounded UTF-8 JSON and validate its versioned observation contract."""
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


def _require_number(value: Any, name: str, minimum: float, maximum: float) -> float:
    if type(value) not in (int, float):
        raise ObservationValidationError(f"{name} must be a JSON number.")
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ObservationValidationError(
            f"{name} must be finite and between {minimum:g} and {maximum:g}."
        )
    return number


def _require_integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ObservationValidationError(
            f"{name} must be an integer from {minimum} to {maximum}."
        )
    return value


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


def _validate_client(value: Any) -> dict[str, str]:
    client = _require_object(value, "client", _CLIENT_KEYS)
    if client["minecraft_version"] != "1.21.11":
        raise ObservationValidationError("Unsupported Minecraft client version.")
    mod_version = client["mod_version"]
    if not isinstance(mod_version, str) or _MOD_VERSION.fullmatch(mod_version) is None:
        raise ObservationValidationError("client.mod_version must use numeric semver.")
    return {
        "minecraft_version": "1.21.11",
        "mod_version": mod_version,
    }


def _validate_player(value: Any) -> dict[str, Any]:
    player = _require_object(value, "player", _PLAYER_KEYS)
    x = _require_number(player["x"], "player.x", -30_000_000, 30_000_000)
    y = _require_number(player["y"], "player.y", -2048, 2048)
    z = _require_number(player["z"], "player.z", -30_000_000, 30_000_000)
    health = _require_number(player["health"], "player.health", 0, 1024)
    food_level = _require_integer(player["food_level"], "player.food_level", 0, 20)
    selected_item = _require_resource_location(
        player["selected_item"], "player.selected_item"
    )
    return {
        "x": x,
        "y": y,
        "z": z,
        "health": health,
        "food_level": food_level,
        "selected_item": selected_item,
    }


def _validate_v1(payload: dict[str, Any]) -> dict[str, Any]:
    _require_object(payload, "observation", _TOP_LEVEL_KEYS_V1)
    client = _validate_client(payload["client"])
    world = _require_object(payload["world"], "world", _WORLD_KEYS_V1)
    dimension = _require_resource_location(world["dimension"], "world.dimension")
    player = _validate_player(payload["player"])
    return {
        "schema_version": 1,
        "client": client,
        "world": {"dimension": dimension},
        "player": player,
    }


def _validate_block_sample(value: Any) -> dict[str, Any]:
    sample_keys = {
        "center",
        "range",
        "scanned_positions",
        "non_air_blocks",
        "truncated",
        "blocks",
    }
    sample = _require_object(value, "world.block_sample", sample_keys)

    center = _require_object(
        sample["center"], "world.block_sample.center", {"x", "y", "z"}
    )
    normalized_center = {
        "x": _require_integer(center["x"], "block_sample.center.x", -30_000_000, 30_000_000),
        "y": _require_integer(center["y"], "block_sample.center.y", -2048, 2048),
        "z": _require_integer(center["z"], "block_sample.center.z", -30_000_000, 30_000_000),
    }

    observed_range = _require_object(
        sample["range"], "world.block_sample.range", {"x", "y", "z"}
    )
    normalized_range = {
        key: _require_integer(observed_range[key], f"block_sample.range.{key}", 0, 4)
        for key in ("x", "y", "z")
    }
    if normalized_range != BLOCK_SAMPLE_RANGE:
        raise ObservationValidationError("block_sample.range must be the supported 5x3x5 region.")

    scanned = _require_integer(
        sample["scanned_positions"],
        "block_sample.scanned_positions",
        0,
        BLOCK_SAMPLE_POSITION_COUNT,
    )
    non_air = _require_integer(
        sample["non_air_blocks"], "block_sample.non_air_blocks", 0, scanned
    )
    truncated = sample["truncated"]
    if type(truncated) is not bool:
        raise ObservationValidationError("block_sample.truncated must be a boolean.")

    raw_blocks = sample["blocks"]
    if not isinstance(raw_blocks, list) or len(raw_blocks) > MAX_BLOCK_SAMPLE_BLOCKS:
        raise ObservationValidationError(
            f"block_sample.blocks must contain at most {MAX_BLOCK_SAMPLE_BLOCKS} entries."
        )

    normalized_blocks: list[dict[str, Any]] = []
    seen_offsets: set[tuple[int, int, int]] = set()
    for index, raw_block in enumerate(raw_blocks):
        label = f"block_sample.blocks[{index}]"
        block = _require_object(
            raw_block,
            label,
            {"dx", "dy", "dz", "id", "properties", "properties_truncated"},
        )
        dx = _require_integer(block["dx"], f"{label}.dx", -2, 2)
        dy = _require_integer(block["dy"], f"{label}.dy", -1, 1)
        dz = _require_integer(block["dz"], f"{label}.dz", -2, 2)
        offset = (dx, dy, dz)
        if offset in seen_offsets:
            raise ObservationValidationError(f"{label} duplicates a block offset.")
        seen_offsets.add(offset)

        block_id = _require_resource_location(block["id"], f"{label}.id")
        raw_properties = block["properties"]
        if not isinstance(raw_properties, dict) or len(raw_properties) > MAX_BLOCK_PROPERTIES:
            raise ObservationValidationError(
                f"{label}.properties must contain at most {MAX_BLOCK_PROPERTIES} entries."
            )
        properties: dict[str, str] = {}
        for property_name, property_value in raw_properties.items():
            if (
                not isinstance(property_name, str)
                or _PROPERTY_NAME.fullmatch(property_name) is None
                or not isinstance(property_value, str)
                or _PROPERTY_VALUE.fullmatch(property_value) is None
            ):
                raise ObservationValidationError(
                    f"{label}.properties contains an invalid property name or value."
                )
            properties[property_name] = property_value

        properties_truncated = block["properties_truncated"]
        if type(properties_truncated) is not bool:
            raise ObservationValidationError(
                f"{label}.properties_truncated must be a boolean."
            )
        normalized_blocks.append(
            {
                "dx": dx,
                "dy": dy,
                "dz": dz,
                "id": block_id,
                "properties": properties,
                "properties_truncated": properties_truncated,
            }
        )

    expected_entries = min(non_air, MAX_BLOCK_SAMPLE_BLOCKS)
    if len(normalized_blocks) > expected_entries:
        raise ObservationValidationError(
            "block_sample contains more entries than the observed non-air block count."
        )
    if len(normalized_blocks) < expected_entries and not truncated:
        raise ObservationValidationError(
            "block_sample omitted block entries without setting the truncation flag."
        )
    if non_air > MAX_BLOCK_SAMPLE_BLOCKS and not truncated:
        raise ObservationValidationError(
            "block_sample must be marked truncated when more than 32 non-air blocks exist."
        )
    if non_air <= MAX_BLOCK_SAMPLE_BLOCKS and len(normalized_blocks) == non_air and truncated:
        raise ObservationValidationError(
            "block_sample is marked truncated even though all non-air blocks are present."
        )

    return {
        "center": normalized_center,
        "range": normalized_range,
        "scanned_positions": scanned,
        "non_air_blocks": non_air,
        "truncated": truncated,
        "blocks": normalized_blocks,
    }


def _validate_v2(payload: dict[str, Any]) -> dict[str, Any]:
    _require_object(payload, "observation", _TOP_LEVEL_KEYS_V2)
    client = _validate_client(payload["client"])
    world = _require_object(payload["world"], "world", _WORLD_KEYS_V2)
    dimension = _require_resource_location(world["dimension"], "world.dimension")
    block_sample = _validate_block_sample(world["block_sample"])
    player = _validate_player(payload["player"])
    return {
        "schema_version": 2,
        "client": client,
        "world": {
            "dimension": dimension,
            "block_sample": block_sample,
        },
        "player": player,
    }


def validate_observation(value: Any) -> dict[str, Any]:
    """Validate and return a normalized copy of a supported Minecraft observation."""
    if not isinstance(value, dict):
        raise ObservationValidationError("observation must be a JSON object.")
    schema_version = value.get("schema_version")
    if type(schema_version) is not int:
        raise ObservationValidationError("Unsupported observation schema version.")
    if schema_version == 1:
        return _validate_v1(value)
    if schema_version == 2:
        return _validate_v2(value)
    raise ObservationValidationError("Unsupported observation schema version.")
