import json

import pytest

from nika.observation import (
    MAX_OBSERVATION_BYTES,
    ObservationValidationError,
    decode_observation,
    validate_observation,
)


def sample_observation() -> dict:
    return {
        "schema_version": 1,
        "client": {
            "minecraft_version": "1.21.11",
            "mod_version": "0.1.0",
        },
        "world": {"dimension": "minecraft:overworld"},
        "player": {
            "x": 125.5,
            "y": 72.0,
            "z": -4096.25,
            "health": 18.0,
            "food_level": 17,
            "selected_item": "minecraft:diamond_pickaxe",
        },
    }


def test_validate_observation_accepts_supported_v1_payload() -> None:
    result = validate_observation(sample_observation())

    assert result["schema_version"] == 1
    assert result["world"]["dimension"] == "minecraft:overworld"
    assert result["player"]["x"] == 125.5
    assert result["player"]["food_level"] == 17
    assert result["player"]["selected_item"] == "minecraft:diamond_pickaxe"


def test_decode_observation_accepts_utf8_json() -> None:
    body = json.dumps(sample_observation()).encode("utf-8")

    assert decode_observation(body) == validate_observation(sample_observation())


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update(extra=True), "unsupported properties"),
        (lambda value: value.pop("world"), "missing required properties"),
        (lambda value: value.update(schema_version=True), "schema version"),
        (lambda value: value.update(schema_version=2), "schema version"),
        (
            lambda value: value["client"].update(extra="ignored"),
            "unsupported properties",
        ),
        (
            lambda value: value["world"].update(dimension="Overworld"),
            "namespaced Minecraft identifier",
        ),
        (
            lambda value: value["player"].update(selected_item="diamond_pickaxe"),
            "namespaced Minecraft identifier",
        ),
        (
            lambda value: value["player"].update(food_level=True),
            "integer from 0 to 20",
        ),
        (
            lambda value: value["player"].update(food_level=21),
            "integer from 0 to 20",
        ),
        (
            lambda value: value["player"].update(health=-0.1),
            "between 0 and 1024",
        ),
        (
            lambda value: value["player"].update(x=30_000_001),
            "between -3e+07 and 3e+07",
        ),
        (
            lambda value: value["player"].update(y=2049),
            "between -2048 and 2048",
        ),
        (
            lambda value: value["player"].update(z=float("inf")),
            "between -3e+07 and 3e+07",
        ),
        (
            lambda value: value["player"].update(x=True),
            "JSON number",
        ),
        (
            lambda value: value["client"].update(minecraft_version="1.21.10"),
            "Unsupported Minecraft",
        ),
        (
            lambda value: value["client"].update(mod_version="development"),
            "numeric semver",
        ),
        (
            lambda value: value["player"].update(extra="full inventory"),
            "unsupported properties",
        ),
    ],
)
def test_validate_observation_rejects_invalid_payloads(mutation, message: str) -> None:
    payload = sample_observation()
    mutation(payload)

    with pytest.raises(ObservationValidationError, match=message):
        validate_observation(payload)


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"not json",
        b"[]",
        b'{"schema_version":1,"schema_version":1}',
        b'{"value":NaN}',
        b'{"value":Infinity}',
        b"\xff",
    ],
)
def test_decode_observation_rejects_invalid_json(body: bytes) -> None:
    with pytest.raises(ObservationValidationError):
        decode_observation(body)


def test_decode_observation_rejects_oversized_body() -> None:
    with pytest.raises(ObservationValidationError, match="8 KiB"):
        decode_observation(b" " * (MAX_OBSERVATION_BYTES + 1))


def test_decode_observation_rejects_non_finite_exponent() -> None:
    body = json.dumps(sample_observation()).replace(
        '"x": 125.5', '"x": 1e999'
    ).encode("utf-8")

    with pytest.raises(ObservationValidationError, match="finite"):
        decode_observation(body)
