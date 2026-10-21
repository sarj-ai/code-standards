from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

from sarj_standards.libs.linting.text_rules.ci_cloud_target_literal import CiCloudTargetLiteral
from sarj_standards.libs.linting.text_rules.cloudbuild_contract import CloudBuildContract


if TYPE_CHECKING:
    from collections.abc import Mapping

    from sarj_standards.libs.linting.text_rule_base import Rule

REGISTRY: Mapping[str, type[Rule]] = MappingProxyType(
    {CiCloudTargetLiteral.id: CiCloudTargetLiteral, CloudBuildContract.id: CloudBuildContract}
)
