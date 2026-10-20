from __future__ import annotations

from pathlib import Path

import pytest

from sarj_python_lint.cast_access import indirect_typing_cast_accesses


@pytest.mark.parametrize(
    "source",
    [
        "from typing import *\n",
        "from typing_extensions import *\n",
        'import typing\ncoerce = getattr(typing, "cast")\n',
        'import typing_extensions as t\ncoerce = getattr(t, "cast", None)\n',
        'def coerce():\n    import typing as t\n    return getattr(t, "ca" "st")\n',
        'import typing\ncoerce = getattr(typing, "ca" + "st")\n',
        'import typing\ncoerce = getattr(typing, f"cast")\n',
        'import typing\ncoerce = typing.__dict__["cast"]\n',
        'import typing_extensions as t\ncoerce = vars(t)["cast"]\n',
        'import typing\ncoerce = typing.__getattribute__("cast")\n',
    ],
)
def test_proves_indirect_static_typing_cast_access(source: str) -> None:
    findings = indirect_typing_cast_accesses(Path("app.py"), source)

    assert len(findings) == 1
    assert findings[0].qualified_api in {"typing.cast", "typing_extensions.cast"}


@pytest.mark.parametrize(
    "source",
    [
        "from typing import cast\n",  # Native Ruff already owns ordinary import/member access.
        'def read(typing):\n    return getattr(typing, "cast")\n',
        'import typing\ndef read(getattr):\n    return getattr(typing, "cast")\n',
        'import typing\ndef read():\n    getattr = first\n    getattr = second\n    return getattr(typing, "cast")\n',
        'import typing\ntyping = other\ncoerce = getattr(typing, "cast")\n',
        'import typing\ntyping.cast = other\ncoerce = getattr(typing, "cast")\n',
        'import typing\nconfigure(typing)\ncoerce = getattr(typing, "cast")\n',
        "import typing\ndef read(name):\n    return getattr(typing, name)\n",
        'import typing\ncoerce = getattr(typing, "cast", **options)\n',
        'import typing\ndef read():\n    global typing\n    return getattr(typing, "cast")\n',
        "broken !!!",
        'import typing\ncoerce = getattr(typing, f"ca{suffix}")\n',
        "import typing\ndef read(name):\n    return typing.__dict__[name]\n",
        'import typing\nvars = custom\ncoerce = vars(typing)["cast"]\n',
        'import typing\ntyping.__dict__["cast"] = other\ncoerce = vars(typing)["cast"]\n',
        'import typing\nnamespace = vars(typing)\ncoerce = getattr(typing, "cast")\n',
        'import typing\ncoerce = getattr(typing, "cast", vars(other))\n',
        'import typing\nother.__dict__["cast"]\ncoerce = getattr(typing, "cast")\n',
    ],
)
def test_abstains_without_a_stable_native_api_identity(source: str) -> None:
    assert indirect_typing_cast_accesses(Path("app.py"), source) == ()


def test_shadowing_in_an_unrelated_scope_does_not_hide_proven_cast_access() -> None:
    source = 'import typing\ndef custom(getattr):\n    return getattr\ncoerce = getattr(typing, "cast")\n'

    assert len(indirect_typing_cast_accesses(Path("app.py"), source)) == 1
