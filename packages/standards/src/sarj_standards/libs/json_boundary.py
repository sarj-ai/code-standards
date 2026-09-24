import json


def parse_json(text: str) -> object:
    return json.loads(text)  # pyright: ignore[reportAny] -- untyped parser boundary.


def decode_json_prefix(decoder: json.JSONDecoder, text: str) -> object:
    decoded: tuple[object, int] = decoder.raw_decode(text)
    return decoded[0]
