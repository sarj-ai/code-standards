"""Public API for standards adoption, checking, setup, and release policy."""

from __future__ import annotations

from ._meta import (
    CONFIGS_DIR,
    ESLINT_APPLICATION,
    ESLINT_PEERS,
    ESLINT_STRICT,
    MARKDOWNLINT_STRICT,
    PYRIGHT_STRICT,
    RUFF_APPLICATION,
    RUFF_STRICT,
    TAPLO_STRICT,
    YAMLLINT_STRICT,
    __version__,
)
from .libs.adoption.doctor import Finding as DoctorFinding
from .libs.adoption.doctor import Level as DoctorLevel
from .libs.adoption.doctor import diagnose
from .libs.adoption.lifecycle import Command, Inspection, inspect
from .libs.adoption.manifest import Manifest
from .libs.adoption.manifest import load as load_manifest
from .libs.adoption.scaffold import Plan as ScaffoldPlan
from .libs.adoption.scaffold import apply as apply_scaffold
from .libs.adoption.scaffold import build_plan as plan_scaffold
from .libs.adoption.service import (
    InitPlan,
    InitResult,
    apply_init,
    apply_sync,
    plan_init,
    plan_sync,
)
from .libs.adoption.service import (
    SyncOutcome as ConfigSyncOutcome,
)
from .libs.adoption.service import (
    SyncPlan as ConfigSyncPlan,
)
from .libs.adoption.service import (
    SyncResult as ConfigSyncResult,
)
from .libs.adoption.upgrade import UpgradePlan
from .libs.adoption.upgrade import apply as apply_upgrade
from .libs.adoption.upgrade import build_plan as plan_upgrade
from .libs.linting.library_policy import Finding as LibraryPolicyFinding
from .libs.linting.library_policy import scan as check_library_policy
from .libs.linting.runner import GroupedPaths, group_paths
from .libs.linting.runner import run as check
from .libs.linting.textlint import Finding as TextFinding
from .libs.linting.textlint import check_paths as check_text
from .libs.release import (
    PackedArtifact,
    ReleaseAgePolicy,
    ReleaseAgeReport,
    ReleaseTarget,
    TagSyncResult,
    ValidatedReleaseTag,
    changed_release_targets,
    check_lockfile_release_age,
    create_release_tags,
    load_exact_exclusions,
    missing_remote_release_tags,
    pack_typescript,
    publish_target,
    run_typescript_release,
    validate_release_tag,
    verify_package_tarball,
)
from .libs.repository.hooks import run as run_hooks
from .libs.repository.repository import Finding as RepositoryFinding
from .libs.repository.repository import RepositoryPolicy
from .libs.repository.repository import check as check_repository
from .libs.repository.rule_maintenance import SyncResult as LedgerSyncResult
from .libs.repository.rule_maintenance import inventory as rule_inventory
from .libs.repository.rule_maintenance import sync_ledger
from .libs.setup import SetupPlan, apply_setup, plan_setup


__all__ = [
    "CONFIGS_DIR",
    "ESLINT_APPLICATION",
    "ESLINT_PEERS",
    "ESLINT_STRICT",
    "MARKDOWNLINT_STRICT",
    "PYRIGHT_STRICT",
    "RUFF_APPLICATION",
    "RUFF_STRICT",
    "TAPLO_STRICT",
    "YAMLLINT_STRICT",
    "Command",
    "ConfigSyncOutcome",
    "ConfigSyncPlan",
    "ConfigSyncResult",
    "DoctorFinding",
    "DoctorLevel",
    "GroupedPaths",
    "InitPlan",
    "InitResult",
    "Inspection",
    "LedgerSyncResult",
    "LibraryPolicyFinding",
    "Manifest",
    "PackedArtifact",
    "ReleaseAgePolicy",
    "ReleaseAgeReport",
    "ReleaseTarget",
    "RepositoryFinding",
    "RepositoryPolicy",
    "ScaffoldPlan",
    "SetupPlan",
    "TagSyncResult",
    "TextFinding",
    "UpgradePlan",
    "ValidatedReleaseTag",
    "__version__",
    "apply_init",
    "apply_scaffold",
    "apply_setup",
    "apply_sync",
    "apply_upgrade",
    "changed_release_targets",
    "check",
    "check_library_policy",
    "check_lockfile_release_age",
    "check_repository",
    "check_text",
    "create_release_tags",
    "diagnose",
    "group_paths",
    "inspect",
    "load_exact_exclusions",
    "load_manifest",
    "missing_remote_release_tags",
    "pack_typescript",
    "plan_init",
    "plan_scaffold",
    "plan_setup",
    "plan_sync",
    "plan_upgrade",
    "publish_target",
    "rule_inventory",
    "run_hooks",
    "run_typescript_release",
    "sync_ledger",
    "validate_release_tag",
    "verify_package_tarball",
]
