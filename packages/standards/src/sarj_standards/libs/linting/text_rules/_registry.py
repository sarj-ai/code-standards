from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Mapping

    from sarj_standards.libs.linting.text_rule_base import Rule

REGISTRY: Mapping[str, type[Rule]] = MappingProxyType({})
