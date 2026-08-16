"""Rule registry — the single source of truth mapping rule id to rule class."""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

from sarj_iac_lint.rules.no_comment_cruft import NoCommentCruft
from sarj_iac_lint.rules.no_dead_environment_input import NoDeadEnvironmentInput
from sarj_iac_lint.rules.no_environment_conditional import NoEnvironmentConditional
from sarj_iac_lint.rules.require_deletion_protection import RequireDeletionProtection
from sarj_iac_lint.rules.require_prevent_destroy import RequirePreventDestroyOnIrreplaceable


if TYPE_CHECKING:
    from collections.abc import Mapping

    from sarj_iac_lint.rule_base import Rule


REGISTRY: Mapping[str, type[Rule]] = MappingProxyType(
    {
        RequireDeletionProtection.id: RequireDeletionProtection,
        RequirePreventDestroyOnIrreplaceable.id: RequirePreventDestroyOnIrreplaceable,
        NoCommentCruft.id: NoCommentCruft,
        NoEnvironmentConditional.id: NoEnvironmentConditional,
        NoDeadEnvironmentInput.id: NoDeadEnvironmentInput,
    }
)
