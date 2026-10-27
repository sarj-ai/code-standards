from pathlib import Path

import pytest

from sarj_python_lint.rules.prefer_precise_object_contract import PreferPreciseObjectContract


_WRITER = "class Domain: pass\ndef overwrite(namespace):\n    namespace['result'] = Domain()\n"
_HOLDER_WRITER = "class Domain: pass\ndef overwrite(holders):\n    holders[0]['result'] = Domain()\n"


@pytest.mark.parametrize(
    "source",
    [
        _WRITER
        + "def f(source: str) -> object:\n    namespace = {}\n    exec(source, namespace)\n    overwrite(namespace)\n    return namespace['result']\n",
        _WRITER
        + "def f(source: str) -> object:\n    namespace = {}\n    exec(source, namespace)\n    overwrite(namespace=namespace)\n    return namespace['result']\n",
        _WRITER
        + "def f(source: str) -> object:\n    namespace = {}\n    exec(source, namespace); overwrite(namespace)\n    return namespace['result']\n",
        "class Domain: pass\ndef f(source: str) -> object:\n    namespace = {}\n    exec(source, namespace)\n    def overwrite():\n        namespace['result'] = Domain()\n    overwrite()\n    return namespace['result']\n",
        "class Domain: pass\ndef f(source: str) -> object:\n    namespace = {}\n    def overwrite():\n        namespace['result'] = Domain()\n    exec(source, namespace)\n    overwrite()\n    return namespace['result']\n",
        "class Domain: pass\ndef f(source: str) -> object:\n    namespace = {}\n    def overwrite(target=namespace):\n        target['result'] = Domain()\n    exec(source, namespace)\n    overwrite()\n    return namespace['result']\n",
        "class Domain: pass\ndef f(source: str) -> object:\n    namespace = {}\n    def overwrite():\n        namespace['result'] = Domain()\n    callback = overwrite\n    exec(source, namespace)\n    callback()\n    return namespace['result']\n",
        _HOLDER_WRITER
        + "def f(source: str) -> object:\n    namespace = {}\n    exec(source, namespace)\n    holders = [namespace]\n    overwrite(holders)\n    return namespace['result']\n",
        _HOLDER_WRITER
        + "def f(source: str) -> object:\n    namespace = {}\n    holders = [namespace]\n    exec(source, namespace)\n    overwrite(holders)\n    return namespace['result']\n",
        _HOLDER_WRITER
        + "def f(source: str) -> object:\n    namespace = {}\n    holders = [namespace]\n    alias = holders\n    exec(source, namespace)\n    overwrite(alias)\n    return namespace['result']\n",
        _HOLDER_WRITER
        + "def f(source: str) -> object:\n    namespace = {}\n    holders = []\n    holders.append(namespace)\n    exec(source, namespace)\n    overwrite(holders)\n    return namespace['result']\n",
        _HOLDER_WRITER
        + "def f(source: str) -> object:\n    namespace = {}\n    holders = [None]\n    holders[0] = namespace\n    exec(source, namespace)\n    overwrite(holders)\n    return namespace['result']\n",
        "class Domain: pass\ndef overwrite(holders):\n    holders['nested']['namespace']['result'] = Domain()\ndef f(source: str) -> object:\n    namespace = {}\n    holders = {'nested': {}}\n    nested = holders['nested']\n    nested['namespace'] = namespace\n    exec(source, namespace)\n    overwrite(holders)\n    return namespace['result']\n",
        _HOLDER_WRITER
        + "def f(source: str) -> object:\n    namespace = {}\n    holders = [namespace]\n    exec(source, namespace)\n    overwrite(*[holders])\n    return namespace['result']\n",
        "class Domain: pass\ndef f(source: str) -> object:\n    namespace = {}\n    exec(source, namespace)\n    exec(\"namespace['result'] = Domain()\")\n    return namespace['result']\n",
        "class Domain: pass\ndef f(source: str) -> object:\n    namespace = {}\n    exec(source, namespace)\n    eval(\"namespace.update(result=Domain())\")\n    return namespace['result']\n",
        "class Domain: pass\ndef f(source: str) -> object:\n    namespace = {}\n    exec(source, namespace)\n    exec(\"namespace['result'] = Domain()\", None)\n    return namespace['result']\n",
        "class Domain: pass\ndef f(source: str) -> object:\n    namespace = {}\n    exec(source, namespace)\n    exec(\"namespace['result'] = Domain()\", None, None)\n    return namespace['result']\n",
        "class Domain: pass\ndef f(source: str) -> object:\n    namespace = {}\n    exec(source, namespace)\n    exec(\"namespace['result'] = Domain()\", globals=None, locals=None)\n    return namespace['result']\n",
        "class Domain: pass\ndef f(source: str) -> object:\n    namespace = {}\n    exec(source, namespace)\n    scope = {'namespace': namespace, 'Domain': Domain}\n    exec(\"namespace['result'] = Domain()\", scope)\n    return namespace['result']\n",
        "class Domain: pass\ndef f(source: str) -> object:\n    namespace = {}\n    scope = {'namespace': namespace, 'Domain': Domain}\n    exec(source, namespace)\n    exec(\"namespace['result'] = Domain()\", {}, scope)\n    return namespace['result']\n",
    ],
)
def test_escaped_namespace_cannot_lend_opaque_result_ownership(source: str) -> None:
    findings = PreferPreciseObjectContract().check(Path("app/contracts.py"), source)
    assert len(findings) == 1


@pytest.mark.parametrize(
    "body",
    [
        "    exec(source, namespace)\n    return namespace['result']\n",
        "    alias = namespace\n    exec(source, namespace)\n    return alias['result']\n",
        "    holders = [namespace]\n    exec(source, namespace)\n    return namespace['result']\n",
        "    def unused():\n        namespace['result'] = 'known'\n    exec(source, namespace)\n    return namespace['result']\n",
        "    exec(source, namespace)\n    len(namespace)\n    id(namespace)\n    bool(namespace)\n    type(namespace)\n    return namespace['result']\n",
        "    exec(source, namespace)\n    namespace.get('value')\n    namespace.copy()\n    return namespace['result']\n",
        "    exec(source, namespace)\n    count = len(namespace)\n    unrelated(count)\n    return namespace['result']\n",
        "    other = {}\n    exec(source, namespace)\n    overwrite(other)\n    return namespace['result']\n",
        "    other = {}\n    def overwrite():\n        other['result'] = 'known'\n    exec(source, namespace)\n    overwrite()\n    return namespace['result']\n",
        "    exec(source, namespace)\n    exec('pass', {})\n    return namespace['result']\n",
        "    exec(source, namespace)\n    exec(source, namespace)\n    return namespace['result']\n",
        "    exec(source, namespace)\n    exec(source, None, namespace)\n    return namespace['result']\n",
        "    exec(source, namespace)\n    exec(source, namespace, None)\n    return namespace['result']\n",
        "    exec(source, namespace)\n    exec(source, globals=None, locals=namespace)\n    return namespace['result']\n",
        "    exec(source, namespace)\n    eval(source, None, namespace)\n    return namespace['result']\n",
    ],
)
def test_unescaped_namespace_retains_opaque_result_ownership(body: str) -> None:
    source = "def f(source: str) -> object:\n    namespace = {}\n" + body
    assert PreferPreciseObjectContract().check(Path("app/contracts.py"), source) == []


def test_namespace_carrier_proof_abstains_at_alias_depth_limit() -> None:
    aliases = "".join(f"    holder_{index} = holder_{index - 1}\n" for index in range(1, 20))
    source = (
        _HOLDER_WRITER
        + "def f(source: str) -> object:\n    namespace = {}\n    holder_0 = [namespace]\n"
        + aliases
        + "    exec(source, namespace)\n    overwrite(holder_19)\n    return namespace['result']\n"
    )
    assert len(PreferPreciseObjectContract().check(Path("app/contracts.py"), source)) == 1
