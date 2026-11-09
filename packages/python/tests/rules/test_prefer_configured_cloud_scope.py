from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.prefer_configured_cloud_scope import PreferConfiguredCloudScope


P = Path("app/publish.py")
ACCOUNT = "0123456789abcdef0123456789abcdef"
URL = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/workers/scripts"


def test_documented_examples() -> None:
    verify_native_rule(PreferConfiguredCloudScope, analyze)


@pytest.mark.parametrize(
    ("imports", "call"),
    [
        ("import httpx", f"httpx.get('{URL}')"),
        ("import requests", f"requests.post(url='{URL}')"),
        ("import httpx as http", f"http.delete('{URL}')"),
        ("from requests import put as send", f"send('{URL}')"),
        ("from httpx import request", f"request('PATCH', '{URL}')"),
        ("import requests", f"requests.request(method='POST', url='{URL}')"),
        ("from urllib.request import urlopen", f"urlopen('{URL}')"),
        ("import urllib.request", f"urllib.request.urlopen(url='{URL}')"),
    ],
)
def test_import_proven_request_url(imports: str, call: str) -> None:
    [finding] = PreferConfiguredCloudScope().check(P, f"{imports}\n{call}\n")
    assert finding.code == "SARJ566"
    assert finding.severity is Severity.WARNING
    assert finding.line == 2
    assert ACCOUNT not in finding.message
    assert finding.fixes == ()


@pytest.mark.parametrize("suffix", ["", "?page=1", "#metadata", "/workers/scripts"])
def test_account_path_delimiter(suffix: str) -> None:
    source = f"import httpx\nhttpx.get('https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}{suffix}')\n"
    [finding] = PreferConfiguredCloudScope().check(P, source)
    assert finding.line == 2


@pytest.mark.parametrize(
    "value",
    [
        f"'{ACCOUNT}'",
        f"'{ACCOUNT[:16]}' + '{ACCOUNT[16:]}'",
        f"f'{ACCOUNT}'",
    ],
)
def test_account_literal_flows_through_fstring_and_stable_names(value: str) -> None:
    source = (
        "import httpx\n"
        f"account = {value}\n"
        "base = f'https://api.cloudflare.com/client/v4/accounts/{account}/workers/scripts'\n"
        "def load(suffix):\n"
        "    return httpx.get(f'{base}/{suffix}')\n"
    )
    [finding] = PreferConfiguredCloudScope().check(P, source)
    assert finding.line == 2


def test_local_annotated_assignment_and_concatenated_url() -> None:
    source = (
        "import requests\n"
        "def load(suffix):\n"
        f"    scope: str = '{ACCOUNT}'\n"
        "    base = 'https://api.cloudflare.com/client/v4/accounts/' + scope + '/'\n"
        "    return requests.get(base + suffix)\n"
    )
    [finding] = PreferConfiguredCloudScope().check(P, source)
    assert finding.line == 3


def test_split_provider_host_is_resolved_from_source_structure() -> None:
    source = (
        "import httpx\n"
        "host = 'https://api.cloud' + 'flare.com'\n"
        f"httpx.get(host + '/client/v4/accounts/{ACCOUNT}/workers/scripts')\n"
    )
    [finding] = PreferConfiguredCloudScope().check(P, source)
    assert finding.line == 3


def test_reports_origin_once_when_multiple_requests_share_base() -> None:
    source = f"import httpx\nbase = '{URL}'\nhttpx.get(base)\nhttpx.post(f'{{base}}/upload')\n"
    assert [finding.line for finding in PreferConfiguredCloudScope().check(P, source)] == [2]


@pytest.mark.parametrize(
    "source",
    [
        f"account = '{ACCOUNT}'\nworker = 'fixed-name'\n",
        f"from pydantic import BaseModel\nfrom typing import Literal\nclass Policy(BaseModel):\n    account: Literal['{ACCOUNT}']\n",
        f"def verify(account):\n    return account == '{ACCOUNT}'\n",
        f"ALLOWED = frozenset({{'{ACCOUNT}'}})\n",
        f"URL = '{URL}'\n",
        f"# import httpx\n# httpx.get('{URL}')\n",
        f"def get(url): return url\nget('{URL}')\n",
        f"from app import httpx\nhttpx.get('{URL}')\n",
        f"import httpx\ndef load(httpx):\n    return httpx.get('{URL}')\n",
        f"import httpx\nhttpx = custom\nhttpx.get('{URL}')\n",
        f"import httpx\nhttpx.get = custom\nhttpx.get('{URL}')\n",
        "import httpx\nhttpx.get('https://api.cloudflare.com/client/v4/user')\n",
        f"import httpx\nhttpx.get('https://service.example/{ACCOUNT}')\n",
        f"import httpx\nhttpx.get('https://evil.invalid/?next={URL}')\n",
        f"import httpx\nhttpx.get('https://api.cloudflare.com.attacker.invalid/client/v4/accounts/{ACCOUNT}/')\n",
        f"import httpx\nhttpx.get('https://api.cloudflare.com/client/v4/ACCOUNTS/{ACCOUNT}/')\n",
        "import httpx\nhttpx.get('https://api.cloudflare.com/client/v4/accounts/not-an-account/')\n",
        f"import httpx\nhttpx.get('https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}x/')\n",
        "import httpx\nhttpx.get('https://api.cloudflare.com/client/v4/accounts/00000000-0000-0000-0000-000000000001/')\n",
        "import httpx\ndef load(account):\n    return httpx.get(f'https://api.cloudflare.com/client/v4/accounts/{account}/workers/scripts')\n",
        "import os\nimport httpx\naccount = os.environ['CLOUDFLARE_ACCOUNT_ID']\nhttpx.get(f'https://api.cloudflare.com/client/v4/accounts/{account}/workers/scripts')\n",
        "import os\nimport httpx\naccount = os.getenv('CLOUDFLARE_ACCOUNT_ID')\nif not account:\n    raise ValueError('Cloudflare account is required')\nhttpx.get(f'https://api.cloudflare.com/client/v4/accounts/{account}/workers/scripts')\n",
        "import httpx\nfrom pydantic_settings import BaseSettings\nclass Settings(BaseSettings):\n    cloudflare_account_id: str\nsettings = Settings()\nhttpx.get(f'https://api.cloudflare.com/client/v4/accounts/{settings.cloudflare_account_id}/workers/scripts')\n",
        f"import httpx\naccount = '{ACCOUNT}'\naccount = choose()\nhttpx.get(f'https://api.cloudflare.com/client/v4/accounts/{{account}}/workers/scripts')\n",
        f"import httpx\nif condition:\n    account = '{ACCOUNT}'\nhttpx.get(f'https://api.cloudflare.com/client/v4/accounts/{{account}}/workers/scripts')\n",
        f"import httpx\naccount = '{ACCOUNT}'\ndef load(account):\n    return httpx.get(f'https://api.cloudflare.com/client/v4/accounts/{{account}}/workers/scripts')\n",
        f"import httpx\naccount = '{ACCOUNT}'\ndef configure():\n    global account\n    account = choose()\nhttpx.get(f'https://api.cloudflare.com/client/v4/accounts/{{account}}/workers/scripts')\n",
        f"import httpx\naccount = '{ACCOUNT}'\ndef load():\n    return httpx.get(f'https://api.cloudflare.com/client/v4/accounts/{{account!r}}/workers/scripts')\n",
        "import httpx\na = b\nb = a\nhttpx.get(f'https://api.cloudflare.com/client/v4/accounts/{a}/workers/scripts')\n",
        "import httpx\ndef (\n",
    ],
)
def test_configuration_policy_and_unproven_requests_remain_valid(source: str) -> None:
    assert PreferConfiguredCloudScope().check(P, source) == []


@pytest.mark.parametrize("path", ["tests/publish.py", "test_publish.py", "app/publish_test.py", "testing/publish.py"])
def test_test_literals_are_not_deployment_configuration(path: str) -> None:
    assert PreferConfiguredCloudScope().check(Path(path), f"import httpx\nhttpx.get('{URL}')\n") == []


def test_exact_origin_suppression_and_generated_sources() -> None:
    source = (
        "import httpx\n"
        f"account = '{ACCOUNT}'  # sarj-noqa: SARJ566 -- Emergency recovery targets this reviewed account.\n"
        "httpx.get(f'https://api.cloudflare.com/client/v4/accounts/{account}/workers/scripts')\n"
    )
    assert PreferConfiguredCloudScope().check(P, source) == []
    assert PreferConfiguredCloudScope().check(P, source.replace("SARJ566", "SARJ497"))
    assert (
        PreferConfiguredCloudScope().check(P, f"# Code generated. DO NOT EDIT.\nimport httpx\nhttpx.get('{URL}')\n")
        == []
    )


@pytest.mark.parametrize("padding", ["x" * 8193, "ü" * 4097])
def test_oversized_literal_expansion_abstains(padding: str) -> None:
    source = f"import httpx\nhttpx.get('{URL}/{padding}')\n"
    assert PreferConfiguredCloudScope().check(P, source) == []


def test_alias_fanout_expansion_stays_bounded() -> None:
    assignments = [f"part0 = '{URL}'"]
    assignments.extend(f"part{index} = part{index - 1} + part{index - 1}" for index in range(1, 32))
    source = "import httpx\n" + "\n".join(assignments) + "\nhttpx.get(part31)\n"
    assert PreferConfiguredCloudScope().check(P, source) == []


def test_escaped_non_scalar_suffix_does_not_break_analysis() -> None:
    source = f"import httpx\nhttpx.get('{URL}/\\ud800')\n"
    [finding] = PreferConfiguredCloudScope().check(P, source)
    assert finding.line == 2
