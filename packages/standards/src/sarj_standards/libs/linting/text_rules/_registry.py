from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

from sarj_standards.libs.linting.text_rules.cloudbuild_contract import CloudBuildContract
from sarj_standards.libs.linting.text_rules.slack_event_text_in_mrkdwn import SlackEventTextInMrkdwn


if TYPE_CHECKING:
    from collections.abc import Mapping

    from sarj_standards.libs.linting.text_rule_base import Rule

REGISTRY: Mapping[str, type[Rule]] = MappingProxyType(
    {SlackEventTextInMrkdwn.id: SlackEventTextInMrkdwn, CloudBuildContract.id: CloudBuildContract}
)
