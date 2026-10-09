import json


def parse_json(text: str) -> object:
    return json.loads(text)  # pyright: ignore[reportAny] -- untyped parser boundary.


def parse_unique_json(text: str) -> object:
    return json.loads(text, object_pairs_hook=_unique_pairs)  # pyright: ignore[reportAny] -- untyped parser boundary.


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            msg = f"duplicate JSON key: {key}"
            raise ValueError(msg)
        result[key] = value
    return result


def decode_json_prefix(decoder: json.JSONDecoder, text: str) -> object:
    decoded: tuple[object, int] = decoder.raw_decode(text)
    return decoded[0]
