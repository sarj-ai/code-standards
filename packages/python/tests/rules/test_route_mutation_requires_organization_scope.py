from __future__ import annotations

from pathlib import Path

import pytest
from sarj_rule_contracts import Severity
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.route_mutation_requires_organization_scope import RouteMutationRequiresOrganizationScope


def test_documented_examples() -> None:
    verify_native_rule(RouteMutationRequiresOrganizationScope, analyze)


def _route(body: str, *, decorator: str = "@router.delete('/automations/{merchant_id}')", params: str = "") -> str:
    return f"class Routes:\n    {decorator}\n    async def handle(self, merchant_id: str{params}) -> None:\n" + "".join(
        f"        {line}\n" for line in body.splitlines()
    )


_ORG = ", organization_id: OrganizationId"


@pytest.mark.parametrize(
    ("decorator", "body"),
    [
        ("@router.delete('/a')", "await self.automation_store.delete(merchant_id)"),
        ("@router.post('/a')", "await self.automation_store.remove_rule(merchant_id)"),
        ("@app.put('/a')", "self.store.update(merchant_id, enabled=True)"),
        ("@router.patch('/a')", "await automation_store.set_enabled(merchant_id, False)"),
        ("@router.delete('/a')", "if not await self.automation_store.delete(merchant_id):\n    raise NotFound"),
    ],
)
def test_unscoped_store_mutations(decorator: str, body: str) -> None:
    findings = RouteMutationRequiresOrganizationScope().check(
        Path("app/routes.py"), _route(body, decorator=decorator, params=_ORG)
    )
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING
    assert "organization_id" in findings[0].message


@pytest.mark.parametrize(
    ("decorator", "params", "body"),
    [
        ("@router.delete('/a')", _ORG, "await self.automation_store.delete(merchant_id, organization_id)"),
        (
            "@router.delete('/a')",
            _ORG,
            "await self.automation_store.delete(merchant_id, organization_id=organization_id)",
        ),
        ("@router.delete('/a')", _ORG, "await self.automation_store.delete(merchant_id, org=user.organization_id)"),
        ("@router.delete('/a')", _ORG, "await self.automation_store.delete(merchant_id, subject)"),
        (
            "@router.post('/a')",
            _ORG,
            "data = UpsertWebhook(organization_id=organization_id, url=merchant_id)\nawait self.webhook_store.upsert(data)",
        ),
        ("@router.delete('/a')", "", "await self.automation_store.delete(merchant_id)"),
        ("@router.get('/a')", _ORG, "await self.automation_store.delete(merchant_id)"),
        ("@router.delete('/a')", _ORG, "await self.automation_client.delete(merchant_id)"),
        ("@router.delete('/a')", _ORG, "await self.store_factory.delete(merchant_id)"),
        ("@router.delete('/a')", _ORG, "await self.automation_store.get(merchant_id)"),
        ("@router.delete('/a')", _ORG, "await self.automation_store.settings(merchant_id)"),
    ],
)
def test_scoped_or_out_of_scope_calls(decorator: str, params: str, body: str) -> None:
    source = _route(body, decorator=decorator, params=params)
    assert RouteMutationRequiresOrganizationScope().check(Path("app/routes.py"), source) == []


def test_tests_are_skipped() -> None:
    source = _route("await self.automation_store.delete(merchant_id)", params=_ORG)
    assert RouteMutationRequiresOrganizationScope().check(Path("tests/test_routes.py"), source) == []
