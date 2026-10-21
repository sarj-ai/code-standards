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


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            't = object()\nclass Reader:\n    import typing as t\n    def read(self):\n        return getattr(t, "cast", None)\n',
            0,
        ),
        (
            'import typing as t\nclass Reader:\n    t = object()\n    def read(self):\n        return getattr(t, "cast")\n',
            1,
        ),
        (
            'import typing as t\nclass Reader:\n    getattr = custom\n    def read(self):\n        return getattr(t, "cast")\n',
            1,
        ),
        (
            't = object()\nclass Outer:\n    import typing as t\n    class Inner:\n        value = getattr(t, "cast", None)\n',
            0,
        ),
        ('t = object()\nclass Reader:\n    import typing as t\n    read = lambda: getattr(t, "cast", None)\n', 0),
        (
            't = object()\nclass Reader:\n    import typing as t\n    values = [getattr(t, "cast", None) for _ in (1,)]\n',
            0,
        ),
        ('class Reader:\n    import typing as t\n    value = getattr(t, "cast")\n', 1),
        ('class Reader:\n    import typing as t\n    values = [t for t in (getattr(t, "cast"),)]\n', 1),
        ('import typing as t\nread = lambda: getattr(t, "cast")\n', 1),
    ],
    ids=(
        "method-skips-class-import",
        "method-skips-class-shadow",
        "method-skips-class-builtin-shadow",
        "nested-class-skips-outer-class-import",
        "lambda-skips-class-import",
        "comprehension-skips-class-import",
        "class-body-sees-class-import",
        "comprehension-first-iterable-sees-class-import",
        "module-lambda-sees-module-import",
    ),
)
def test_reflection_follows_python_class_scope_boundaries(source: str, expected: int) -> None:
    assert len(indirect_typing_cast_accesses(Path("app.py"), source)) == expected


@pytest.mark.parametrize(
    "source",
    [
        'import typing as t\ndef read[t]():\n    return getattr(t, "cast")\n',
        'import typing as t\ndef read[getattr]():\n    return getattr(t, "cast")\n',
        'import typing as t\nclass Reader[t]:\n    def read(self):\n        return getattr(t, "cast")\n',
        'import typing as t\ntype Result[t] = getattr(t, "cast")\n',
    ],
    ids=("generic-function-receiver", "generic-function-builtin", "generic-class-receiver", "generic-type-alias"),
)
def test_type_parameters_do_not_resolve_as_module_or_builtin_names(source: str) -> None:
    assert indirect_typing_cast_accesses(Path("app.py"), source) == ()


@pytest.mark.parametrize(
    "source",
    [
        'import typing as t\ndef read[t](value=getattr(t, "cast")):\n    return value\n',
        'import typing as t\ndef read[t](*, value=getattr(t, "cast")):\n    return value\n',
        'import typing as t\n@getattr(t, "cast")(object, lambda function: function)\ndef read[t]():\n    pass\n',
        'import typing as t\n@getattr(t, "cast")(object, lambda cls: cls)\nclass Reader[t]:\n    pass\n',
    ],
    ids=("function-default", "function-keyword-default", "function-decorator", "class-decorator"),
)
def test_type_parameters_do_not_shadow_outer_evaluation_scopes(source: str) -> None:
    assert len(indirect_typing_cast_accesses(Path("app.py"), source)) == 1
