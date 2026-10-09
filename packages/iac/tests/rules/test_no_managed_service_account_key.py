from __future__ import annotations

from pathlib import Path

import pytest

from sarj_iac_lint.rules.no_managed_service_account_key import NoManagedServiceAccountKey


@pytest.mark.parametrize(
    ("source", "count"),
    [
        ('resource "google_service_account_key" "app" {}', 1),
        ('data "google_service_account_key" "app" {}', 0),
        ('resource "google_service_account" "app" {}', 0),
        ('# resource "google_service_account_key" "app" {}', 0),
        ('locals { text = "resource \\"google_service_account_key\\" \\"app\\" {}" }', 0),
        ('resource "google_service_account_key" "app" {', 0),
    ],
)
def test_managed_keys(source: str, count: int) -> None:
    assert len(NoManagedServiceAccountKey().check(Path("main.tf"), source)) == count
