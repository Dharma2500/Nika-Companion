import json

import pytest

from nika.observation import (
    MAX_OBSERVATION_BYTES,
    ObservationValidationError,
    decode_observation,
    validate_observation,
)


def sample_observation_v1() -> dict:
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


def sample_observation_v2() -> dict:
    payload = sample_observation_v1()
    payload["schema_version"] = 2
    payload["client"]["mod_version"] = "0.2.0"
    payload["world"]["block_sample"] = {
        "center": {"x": 125, "y": 72, "z": -4096},
        "range": {"x": 2, "y": 1, "z": 2},
        "scanned_positions": 75,
        "non_air_blocks": 2,
        "truncated": False,
        "blocks": [
            {
                "dx": 0,
                "dy": -1,
                "dz": 0,
                "id": "minecraft:stone",
                "properties": {},
                "properties_truncated": False,
            },
            {
                "dx": 1,
                "dy": 0,
                "dz": 0,
                "id": "minecraft:oak_stairs",
                "properties": {"facing": "north", "half": "bottom", "shape": "straight"},
                "properties_truncated": False,
            },
        ],
    }
    return payload


def test_validate_observation_accepts_supported_v1_payload() -> None:
    result = validate_observation(sample_observation_v1())

    assert result["schema_version"] == 1
    assert result["world"]["dimension"] == "minecraft:overworld"
    assert result["player"]["x"] == 125.5
    assert result["player"]["food_level"] == 17
    assert result["player"]["selected_item"] == "minecraft:diamond_pickaxe"


def test_validate_observation_accepts_bounded_block_sample_v2() -> None:
    result = validate_observation(sample_observation_v2())

    block_sample = result["world"]["block_sample"]
    assert result["schema_version"] == 2
    assert block_sample["scanned_positions"] == 75
    assert block_sample["non_air_blocks"] == 2
    assert block_sample["blocks"][1]["properties"]["facing"] == "north"


def test_decode_observation_accepts_utf8_json_for_both_versions() -> None:
    for payload in (sample_observation_v1(), sample_observation_v2()):
        body = json.dumps(payload).encode("utf-8")
        assert decode_observation(body) == validate_observation(payload)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update(extra=True), "unsupported properties"),
        (lambda value: value.pop("world"), "missing required properties"),
        (lambda value: value.update(schema_version=True), "schema version"),
        (lambda value: value.update(schema_version=3), "schema version"),
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
            "finite and between",
        ),
        (
            lambda value: value["player"].update(y=2049),
            "between -2048 and 2048",
        ),
        (
            lambda value: value["player"].update(z=float("inf")),
            "finite and between",
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
    ],
)
def test_validate_observation_rejects_invalid_v1_payloads(mutation, message: str) -> None:
    payload = sample_observation_v1()
    mutation(payload)

    with pytest.raises(ObservationValidationError, match=message):
        validate_observation(payload)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda value: value["world"]["block_sample"].update(unexpected=True),
            "unsupported properties",
        ),
        (
            lambda value: value["world"]["block_sample"]["range"].update(x=8),
            "integer from 0 to 4",
        ),
        (
            lambda value: value["world"]["block_sample"].update(scanned_positions=76),
            "integer from 0 to 75",
        ),
        (
            lambda value: value["world"]["block_sample"].update(non_air_blocks=76),
            "integer from 0 to 75",
        ),
        (
            lambda value: value["world"]["block_sample"].update(truncated="false"),
            "must be a boolean",
        ),
        (
            lambda value: value["world"]["block_sample"]["blocks"][0].update(dx=3),
            "integer from -2 to 2",
        ),
        (
            lambda value: value["world"]["block_sample"]["blocks"][0].update(
                id="stone"
            ),
            "namespaced Minecraft identifier",
        ),
        (
            lambda value: value["world"]["block_sample"]["blocks"][0]["properties"].update(
                {"Bad Key": "north"}
            ),
            "invalid property name or value",
        ),
        (
            lambda value: value["world"]["block_sample"]["blocks"][0].update(
                extra="block entity data"
            ),
            "unsupported properties",
        ),
        (
            lambda value: value["world"]["block_sample"]["blocks"].append(
                value["world"]["block_sample"]["blocks"][0].copy()
            ),
            "duplicates a block offset",
        ),
    ],
)
def test_validate_observation_rejects_invalid_v2_payloads(mutation, message: str) -> None:
    payload = sample_observation_v2()
    mutation(payload)

    with pytest.raises(ObservationValidationError, match=message):
        validate_observation(payload)


def test_validate_observation_requires_consistent_block_truncation() -> None:
    payload = sample_observation_v2()
    payload["world"]["block_sample"]["non_air_blocks"] = 33
    payload["world"]["block_sample"]["truncated"] = False

    with pytest.raises(ObservationValidationError, match="inconsistent"):
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
    body = json.dumps(sample_observation_v1()).replace(
        '"x": 125.5', '"x": 1e999'
    ).encode("utf-8")

    with pytest.raises(ObservationValidationError, match="finite"):
        decode_observation(body)
