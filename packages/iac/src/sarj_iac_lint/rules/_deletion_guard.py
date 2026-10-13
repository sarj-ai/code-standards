from __future__ import annotations

from typing import TYPE_CHECKING

from sarj_iac_lint._hcl import literal_string, literal_token


if TYPE_CHECKING:
    from sarj_iac_lint._hcl import Block


def unresolved_deletion_guard(
    block: Block, protection_attributes: tuple[str, ...], *, policy: bool, nested: bool = False
) -> bool:
    lifecycle = block.child("lifecycle")
    if lifecycle is not None:
        guard = lifecycle.attribute("prevent_destroy")
        if guard is not None and literal_token(guard.value) not in {"true", "false"}:
            return True
    for name in protection_attributes:
        guard = block.attribute(name)
        if guard is not None and literal_token(guard.value) not in {"true", "false"}:
            return True
    if policy:
        guard = block.attribute("deletion_policy")
        if guard is not None and literal_string(guard.value) not in {"PREVENT", "DELETE"}:
            return True
    return nested and any(
        unresolved_deletion_guard(
            child, ("deletion_protection", "deletion_protection_enabled"), policy=False, nested=True
        )
        for child in block.blocks
    )
