from __future__ import annotations

from pydantic import BaseModel, ValidationError, model_validator
import pytest


class _Attachment(BaseModel):
    url: str


class _Record(BaseModel):
    name: str
    attachment: _Attachment


class _NormalizedRecord(BaseModel):
    name: str
    active: bool

    @model_validator(mode="before")
    @classmethod
    def normalize(cls, data: dict[str, object]) -> dict[str, object]:
        return {**data, "active": True}


def _sign(record: _Record, url: str) -> _Record:
    attachment = record.attachment.model_copy(update={"url": url})
    return record.model_copy(update={"attachment": attachment})


def test_repeated_path_copies_preserve_original_and_previous_outputs() -> None:
    original = _Record(name="record", attachment=_Attachment(url="original"))
    first = _sign(original, "first")
    second = _sign(original, "second")
    assert original.attachment.url == "original"
    assert first.attachment.url == "first"
    assert second.attachment.url == "second"
    assert first.attachment is not original.attachment
    assert second.attachment is not first.attachment


def test_shallow_copy_control_exposes_shared_nested_value() -> None:
    original = _Record(name="record", attachment=_Attachment(url="original"))
    copied = original.model_copy()
    copied.attachment.url = "changed"
    assert original.attachment.url == "changed"
    assert copied.attachment is original.attachment


@pytest.mark.parametrize("name", ["record", None], ids=["successful-validation", "failed-validation"])
def test_before_validation_replacement_preserves_raw_input(name: str | None) -> None:
    raw: dict[str, object] = {"name": name}
    if name is None:
        with pytest.raises(ValidationError):
            _NormalizedRecord.model_validate(raw)
    else:
        normalized = _NormalizedRecord.model_validate(raw)
        assert normalized.active is True
    assert raw == {"name": name}


def test_discarded_copy_control_does_not_update_original() -> None:
    original = _Attachment(url="original")
    original.model_copy(update={"url": "replacement"})  # sarj-noqa: SARJ483 — discarded-copy control
    assert original.url == "original"
    replacement = original.model_copy(update={"url": "replacement"})
    assert replacement.url == "replacement"
