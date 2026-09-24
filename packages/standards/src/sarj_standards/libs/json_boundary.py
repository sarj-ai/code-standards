import json


def parse_json(text: str) -> object:
    return json.loads(text)  # pyright: ignore[reportAny] -- untyped parser boundary.
