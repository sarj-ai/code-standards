import yaml


def parse_yaml(text: str) -> object:
    return yaml.safe_load(text)  # pyright: ignore[reportAny] -- untyped parser boundary.
