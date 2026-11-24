from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language

from sarj_python_lint.rule_base import AutofixPolicy, Severity, is_suppressed
from sarj_python_lint.rules._project_index import ProjectIndexSet
from sarj_python_lint.rules.prefer_required_constructor_parameters import PreferRequiredConstructorParameters


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


_CASES = (
    EvaluationCase(
        "empty-string-default",
        Language.PYTHON,
        "class Service:\n    def __init__(self, label: str = ''): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "nullable-default",
        Language.PYTHON,
        "class Service:\n    def __init__(self, value: str | None = None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "unannotated-default",
        Language.PYTHON,
        "class Service:\n    def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "required-nullable-domain-value",
        Language.PYTHON,
        "class Service:\n    def __init__(self, value: str | None): ...\n",
    ),
    EvaluationCase(
        "required-nullable-keyword",
        Language.PYTHON,
        "class Service:\n    def __init__(self, *, value: str | None): ...\n",
    ),
    EvaluationCase(
        "required-nested-nullable-type",
        Language.PYTHON,
        "class Service:\n    def __init__(self, values: list[str | None]): ...\n",
    ),
    EvaluationCase(
        "ordinary-method",
        Language.PYTHON,
        "class Service:\n    def run(self, value: str | None = None): ...\n",
    ),
    EvaluationCase(
        "free-init-lookalike",
        Language.PYTHON,
        "def __init__(value=None): ...\n",
    ),
    EvaluationCase(
        "nested-function-init-lookalike",
        Language.PYTHON,
        "class Service:\n    def run(self):\n        def __init__(value=None): ...\n",
    ),
    EvaluationCase(
        "dunder-new-lookalike",
        Language.PYTHON,
        "class Service:\n    def __new__(cls, value=None): ...\n",
    ),
    EvaluationCase(
        "nested-class",
        Language.PYTHON,
        "def build():\n    class Service:\n        def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "explicit-exception-constructor",
        Language.PYTHON,
        "class ServiceError(Exception):\n    def __init__(self, message='failure'): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "typing-overload",
        Language.PYTHON,
        "from typing import overload\nclass Service:\n    @overload\n    def __init__(self, value=None): ...\n",
    ),
    EvaluationCase(
        "typing-overload-import-alias",
        Language.PYTHON,
        "from typing import overload as signature\nclass Service:\n    @signature\n    def __init__(self, value=None): ...\n",
    ),
    EvaluationCase(
        "typing-overload-module-alias",
        Language.PYTHON,
        "import typing as hints\nclass Service:\n    @hints.overload\n    def __init__(self, value=None): ...\n",
    ),
    EvaluationCase(
        "typing-extensions-overload-alias",
        Language.PYTHON,
        "from typing_extensions import overload as signature\nclass Service:\n    @signature\n    def __init__(self, value=None): ...\n",
    ),
    EvaluationCase(
        "unrelated-overload-name",
        Language.PYTHON,
        "def overload(method): return method\nclass Service:\n    @overload\n    def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "shadowed-overload-import",
        Language.PYTHON,
        "from typing import overload\noverload = custom_decorator\nclass Service:\n    @overload\n    def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "builtin-staticmethod",
        Language.PYTHON,
        "class Service:\n    @staticmethod\n    def __init__(value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "builtin-classmethod",
        Language.PYTHON,
        "class Service:\n    @classmethod\n    def __init__(cls, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "builtin-descriptor-import-alias",
        Language.PYTHON,
        "from builtins import staticmethod as descriptor\nclass Service:\n    @descriptor\n    def __init__(value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "builtin-descriptor-module-alias",
        Language.PYTHON,
        "import builtins as runtime\nclass Service:\n    @runtime.classmethod\n    def __init__(cls, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "shadowed-builtin-descriptor",
        Language.PYTHON,
        "staticmethod = custom_decorator\nclass Service:\n    @staticmethod\n    def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "unrelated-qualified-descriptor",
        Language.PYTHON,
        "import decorators\nclass Service:\n    @decorators.staticmethod\n    def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "dataclass-field-default",
        Language.PYTHON,
        "from dataclasses import dataclass\n@dataclass\nclass Value:\n    label: str = ''\n",
    ),
    EvaluationCase(
        "pydantic-field-default",
        Language.PYTHON,
        "from pydantic import BaseModel\nclass Value(BaseModel):\n    label: str = ''\n",
    ),
    EvaluationCase(
        "class-if-constructor",
        Language.PYTHON,
        "class Service:\n    if True:\n        def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "class-try-constructor",
        Language.PYTHON,
        "class Service:\n    try:\n        def __init__(self, value=None): ...\n    except Exception:\n        pass\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "class-with-constructor",
        Language.PYTHON,
        "class Service:\n    with lock:\n        def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "class-for-constructor",
        Language.PYTHON,
        "class Service:\n    for _ in range(1):\n        def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "class-while-constructor",
        Language.PYTHON,
        "class Service:\n    while active:\n        def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "class-match-constructor",
        Language.PYTHON,
        "class Service:\n    match mode:\n        case 1:\n            def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "conditional-free-init-lookalike",
        Language.PYTHON,
        "if True:\n    def __init__(value=None): ...\n",
    ),
    EvaluationCase(
        "conditional-nested-function-lookalike",
        Language.PYTHON,
        "class Service:\n    def run(self):\n        if True:\n            def __init__(value=None): ...\n",
    ),
    EvaluationCase(
        "async-constructor",
        Language.PYTHON,
        "class Service:\n    async def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "abstract-constructor",
        Language.PYTHON,
        "from abc import abstractmethod\nclass Service:\n    @abstractmethod\n    def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "explicit-dataclass-constructor",
        Language.PYTHON,
        "from dataclasses import dataclass\n@dataclass\nclass Service:\n    def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "defaulted-receiver",
        Language.PYTHON,
        "class Service:\n    def __init__(self=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "class-scoped-overload-import",
        Language.PYTHON,
        "class Service:\n    from typing import overload\n    @overload\n    def __init__(self, value=None): ...\n",
    ),
    EvaluationCase(
        "function-scoped-overload-import",
        Language.PYTHON,
        "def build():\n    from typing import overload\n    class Service:\n        @overload\n        def __init__(self, value=None): ...\n",
    ),
    EvaluationCase(
        "global-overload-declaration",
        Language.PYTHON,
        "from typing import overload\ndef build():\n    global overload\n    class Service:\n        @overload\n        def __init__(self, value=None): ...\n",
    ),
    EvaluationCase(
        "global-overload-bypasses-enclosing-local",
        Language.PYTHON,
        "from typing import overload\ndef outer():\n    overload = identity\n    def build():\n        global overload\n        class Service:\n            @overload\n            def __init__(self, value=None): ...\n",
    ),
    EvaluationCase(
        "global-overload-module-alias",
        Language.PYTHON,
        "import typing as hints\ndef build():\n    global hints\n    class Service:\n        @hints.overload\n        def __init__(self, value=None): ...\n",
    ),
    EvaluationCase(
        "global-overload-rebinding",
        Language.PYTHON,
        "from typing import overload\ndef build():\n    global overload\n    overload = identity\n    class Service:\n        @overload\n        def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "global-overload-enclosing-rebinding",
        Language.PYTHON,
        "from typing import overload\ndef build():\n    global overload\n    class Service:\n        @overload\n        def __init__(self, value=None): ...\noverload = identity\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "nonlocal-overload-declaration",
        Language.PYTHON,
        "def outer():\n    from typing import overload\n    def build():\n        nonlocal overload\n        class Service:\n            @overload\n            def __init__(self, value=None): ...\n",
    ),
    EvaluationCase(
        "nonlocal-overload-module-alias",
        Language.PYTHON,
        "def outer():\n    import typing as hints\n    def build():\n        nonlocal hints\n        class Service:\n            @hints.overload\n            def __init__(self, value=None): ...\n",
    ),
    EvaluationCase(
        "nonlocal-overload-nearest-shadow",
        Language.PYTHON,
        "from typing import overload\ndef outer():\n    overload = identity\n    def build():\n        nonlocal overload\n        class Service:\n            @overload\n            def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "nonlocal-overload-rebinding",
        Language.PYTHON,
        "def outer():\n    from typing import overload\n    def build():\n        nonlocal overload\n        overload = identity\n        class Service:\n            @overload\n            def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "nonlocal-overload-enclosing-rebinding",
        Language.PYTHON,
        "def outer():\n    from typing import overload\n    def build():\n        nonlocal overload\n        class Service:\n            @overload\n            def __init__(self, value=None): ...\n    overload = identity\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "global-overload-other-function-rebinding",
        Language.PYTHON,
        "from typing import overload\ndef replace():\n    global overload\n    overload = identity\ndef build():\n    global overload\n    class Service:\n        @overload\n        def __init__(self, value=None): ...\nreplace()\nService = build()\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "nonlocal-overload-sibling-rebinding",
        Language.PYTHON,
        "def outer():\n    from typing import overload\n    def replace():\n        nonlocal overload\n        overload = identity\n    def build():\n        nonlocal overload\n        class Service:\n            @overload\n            def __init__(self, value=None): ...\n    replace()\n    return build()\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "nonlocal-overload-intermediate-rebinding",
        Language.PYTHON,
        "def outer():\n    from typing import overload\n    def middle():\n        nonlocal overload\n        overload = identity\n        def build():\n            nonlocal overload\n            class Service:\n                @overload\n                def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "nonlocal-overload-intermediate-declaration",
        Language.PYTHON,
        "def outer():\n    from typing import overload\n    def middle():\n        nonlocal overload\n        def build():\n            nonlocal overload\n            class Service:\n                @overload\n                def __init__(self, value=None): ...\n",
    ),
    EvaluationCase(
        "nonlocal-overload-unrelated-capture-rebinding",
        Language.PYTHON,
        "def independent():\n    overload = identity\n    def replace():\n        nonlocal overload\n        overload = identity\ndef outer():\n    from typing import overload\n    def build():\n        nonlocal overload\n        class Service:\n            @overload\n            def __init__(self, value=None): ...\n",
    ),
    EvaluationCase(
        "implicit-global-overload-class-after-directed-write",
        Language.PYTHON,
        "from typing import overload\ndef replace():\n    global overload\n    overload = lambda method: method\nreplace()\nclass Service:\n    @overload\n    def __init__(self, value=None): self.value = value\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "implicit-global-overload-factory-after-directed-write",
        Language.PYTHON,
        "from typing import overload\ndef replace():\n    global overload\n    overload = lambda method: method\ndef build():\n    class Service:\n        @overload\n        def __init__(self, value=None): self.value = value\n    return Service\nreplace()\nService = build()\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "implicit-nonlocal-overload-factory-after-directed-write",
        Language.PYTHON,
        "def outer():\n    from typing import overload\n    def replace():\n        nonlocal overload\n        overload = lambda method: method\n    def build():\n        class Service:\n            @overload\n            def __init__(self, value=None): self.value = value\n        return Service\n    replace()\n    return build()\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "implicit-overload-unrelated-capture-rebinding",
        Language.PYTHON,
        "def independent():\n    overload = identity\n    def replace():\n        nonlocal overload\n        overload = identity\ndef outer():\n    from typing import overload\n    def build():\n        class Service:\n            @overload\n            def __init__(self, value=None): ...\n",
    ),
    EvaluationCase(
        "immediate-overload-before-directed-writer-definition",
        Language.PYTHON,
        "from typing import overload\nclass Service:\n    @overload\n    def __init__(self, value=None): ...\ndef replace():\n    global overload\n    overload = lambda method: method\n",
    ),
    EvaluationCase(
        "immediate-global-overload-before-class-directed-write",
        Language.PYTHON,
        "from typing import overload\nclass Service:\n    global overload\n    @overload\n    def __init__(self, value=None): ...\n    overload = lambda method: method\n",
    ),
    EvaluationCase(
        "deferred-overload-after-later-directed-writer",
        Language.PYTHON,
        "from typing import overload\ndef build():\n    class Service:\n        @overload\n        def __init__(self, value=None): self.value = value\n    return Service\ndef replace():\n    global overload\n    overload = lambda method: method\nreplace()\nService = build()\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "nonlocal-comprehension-overload-write",
        Language.PYTHON,
        "def outer():\n    from typing import overload\n    def replace():\n        nonlocal overload\n        [(overload := lambda method: method) for _ in [1]]\n    def build():\n        nonlocal overload\n        class Service:\n            @overload\n            def __init__(self, value=None): self.value = value\n        return Service\n    replace()\n    return build()\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "global-comprehension-overload-write",
        Language.PYTHON,
        "from typing import overload\ndef replace():\n    global overload\n    [(overload := lambda method: method) for _ in [1]]\nreplace()\nclass Service:\n    @overload\n    def __init__(self, value=None): self.value = value\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "unrelated-comprehension-overload-capture-write",
        Language.PYTHON,
        "def independent():\n    overload = identity\n    def replace():\n        nonlocal overload\n        [(overload := identity) for _ in [1]]\ndef outer():\n    from typing import overload\n    def build():\n        nonlocal overload\n        class Service:\n            @overload\n            def __init__(self, value=None): ...\n",
    ),
    EvaluationCase(
        "conditional-overload-import",
        Language.PYTHON,
        "if True:\n    from typing import overload\nclass Service:\n    @overload\n    def __init__(self, value=None): ...\n",
    ),
    EvaluationCase(
        "unrelated-overload-parameter",
        Language.PYTHON,
        "from typing import overload\ndef run(overload): ...\nclass Service:\n    @overload\n    def __init__(self, value=None): ...\n",
    ),
    EvaluationCase(
        "method-parameter-does-not-shadow-decorator",
        Language.PYTHON,
        "from typing import overload\nclass Service:\n    @overload\n    def __init__(self, overload=None): ...\n",
    ),
    EvaluationCase(
        "class-shadowed-overload",
        Language.PYTHON,
        "from typing import overload\nclass Service:\n    overload = identity\n    @overload\n    def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "outer-class-is-not-closure",
        Language.PYTHON,
        "from typing import overload\nclass Outer:\n    overload = identity\n    class Service:\n        @overload\n        def __init__(self, value=None): ...\n",
    ),
    EvaluationCase(
        "outer-class-import-not-visible",
        Language.PYTHON,
        "class Outer:\n    from typing import overload\n    class Service:\n        @overload\n        def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "mutated-overload-namespace",
        Language.PYTHON,
        "import typing\ntyping.overload = lambda method: method\nclass Service:\n    @typing.overload\n    def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "deleted-overload-namespace",
        Language.PYTHON,
        "import typing\ndel typing.overload\nclass Service:\n    @typing.overload\n    def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "overload-namespace-setattr",
        Language.PYTHON,
        'import typing\nsetattr(typing, "overload", lambda method: method)\nclass Service:\n    @typing.overload\n    def __init__(self, value=None): ...\n',
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "overload-namespace-vars-mutation",
        Language.PYTHON,
        'import typing\nvars(typing)["overload"] = lambda method: method\nclass Service:\n    @typing.overload\n    def __init__(self, value=None): ...\n',
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "overload-namespace-alias-mutation",
        Language.PYTHON,
        "import typing\nhints = typing\nhints.overload = lambda method: method\nclass Service:\n    @typing.overload\n    def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "unrelated-scoped-namespace-mutation",
        Language.PYTHON,
        "import typing\ndef run():\n    import custom as typing\n    typing.overload = identity\nclass Service:\n    @typing.overload\n    def __init__(self, value=None): ...\n",
    ),
    EvaluationCase(
        "overload-namespace-dictionary-mutation",
        Language.PYTHON,
        'import typing\ntyping.__dict__["overload"] = lambda method: method\nclass Service:\n    @typing.overload\n    def __init__(self, value=None): ...\n',
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "overload-import-after-namespace-mutation",
        Language.PYTHON,
        "import typing\ntyping.overload = lambda method: method\nfrom typing import overload\nclass Service:\n    @overload\n    def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "captured-overload-before-namespace-mutation",
        Language.PYTHON,
        "from typing import overload\nimport typing\ntyping.overload = lambda method: method\nclass Service:\n    @overload\n    def __init__(self, value=None): ...\n",
    ),
    EvaluationCase(
        "namespace-mutation-after-declaration",
        Language.PYTHON,
        "import typing\nclass Service:\n    @typing.overload\n    def __init__(self, value=None): ...\ntyping.overload = lambda method: method\n",
    ),
    EvaluationCase(
        "class-rebinding-after-declaration",
        Language.PYTHON,
        "from typing import overload\nclass Service:\n    @overload\n    def __init__(self, value=None): ...\n    overload = identity\n",
    ),
    EvaluationCase(
        "module-rebinding-after-declaration",
        Language.PYTHON,
        "from typing import overload\nclass Service:\n    @overload\n    def __init__(self, value=None): ...\noverload = identity\n",
    ),
    EvaluationCase(
        "overload-symbol-default",
        Language.PYTHON,
        "from typing import overload\nclass Service:\n    @overload\n    def __init__(self, value=overload): ...\n",
    ),
    EvaluationCase(
        "late-global-rebinding-before-factory-call",
        Language.PYTHON,
        "from typing import overload\ndef build():\n    class Service:\n        @overload\n        def __init__(self, value=None): ...\n    return Service\noverload = lambda method: method\nService = build()\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "late-local-binding-is-not-module-import",
        Language.PYTHON,
        "from typing import overload\ndef build():\n    class Service:\n        @overload\n        def __init__(self, value=None): ...\n    overload = identity\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "overload-function-member-mutation",
        Language.PYTHON,
        'import typing\ntyping.overload.__setattr__("__code__", (lambda method: method).__code__)\nclass Service:\n    @typing.overload\n    def __init__(self, value=None): ...\n',
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "same-line-captured-overload",
        Language.PYTHON,
        "import typing\nfrom typing import overload; typing.overload = lambda method: method\nclass Service:\n    @overload\n    def __init__(self, value=None): ...\n",
    ),
    EvaluationCase(
        "late-namespace-replacement-before-factory-call",
        Language.PYTHON,
        "import typing\ndef build():\n    class Service:\n        @typing.overload\n        def __init__(self, value=None): ...\n    return Service\ntyping.overload = lambda method: method\nService = build()\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "function-import-after-runtime-replacement",
        Language.PYTHON,
        "import typing\ndef build():\n    from typing import overload\n    class Service:\n        @overload\n        def __init__(self, value=None): ...\n    return Service\ntyping.overload = lambda method: method\nService = build()\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "overload-module-member-mutation",
        Language.PYTHON,
        'import typing\ntyping.__setattr__("overload", lambda method: method)\nclass Service:\n    @typing.overload\n    def __init__(self, value=None): ...\n',
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "overload-mutated-during-default-evaluation",
        Language.PYTHON,
        'import typing\nclass Service:\n    @typing.overload\n    def __init__(self, value=(setattr(typing.overload, "__code__", (lambda method: method).__code__), "implicit")[1]): ...\n',
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "signature-mutation-uses-declaration-scope",
        Language.PYTHON,
        'import typing\nclass Service:\n    @typing.overload\n    def __init__(self, typing, value=(setattr(typing.overload, "__code__", (lambda method: method).__code__), "implicit")[1]): ...\n',
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "deferred-annotations-are-not-default-evaluation",
        Language.PYTHON,
        'from __future__ import annotations\nimport typing\nclass Service:\n    @typing.overload\n    def __init__(self, value: getattr(typing, "Any")=None): ...\n',
    ),
    EvaluationCase("malformed-input", Language.PYTHON, "class Service:\n    def __init__("),
    EvaluationCase(
        "required-nullable-constructed-fallback",
        Language.PYTHON,
        "class Service:\n    def __init__(self, timing: Timing | None):\n        self.timing = timing or Timing()\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "required-nullable-bound-method-fallback",
        Language.PYTHON,
        "from random import SystemRandom\nclass Service:\n    def __init__(self, draw: Callable[[], float] | None):\n"
        "        self.draw = draw or SystemRandom().random\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "required-nullable-conditional-fallback",
        Language.PYTHON,
        "class Service:\n    def __init__(self, *, slots: Semaphore | None):\n"
        "        self.slots = Semaphore(4) if slots is None else slots\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "required-nullable-guarded-fallback",
        Language.PYTHON,
        "class Service:\n    def __init__(self, client: Client | None):\n        if client is None:\n"
        "            client = Client()\n        self.client = client\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "required-nullable-called-class-fallback",
        Language.PYTHON,
        "class Service:\n    def __init__(self, factory: PlayerFactory | None):\n"
        "        self._factory = factory or Player\n    def start(self):\n        return self._factory()\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "required-nullable-uncalled-reference-fallback",
        Language.PYTHON,
        "class Service:\n    def __init__(self, kinds: Kinds | None):\n        self.kinds = kinds or DEFAULT_KINDS\n",
    ),
    EvaluationCase(
        "required-nullable-scalar-derived-fallback",
        Language.PYTHON,
        "import os\nclass Service:\n    def __init__(self, workers: int | None):\n        self.workers = workers or os.cpu_count()\n",
    ),
    EvaluationCase(
        "required-nullable-collection-fallback",
        Language.PYTHON,
        "class Service:\n    def __init__(self, tags: list[str] | None):\n        self.tags = tags or list(DEFAULTS)\n",
    ),
    EvaluationCase(
        "required-nullable-stdlib-value-fallback",
        Language.PYTHON,
        "from datetime import timedelta\nclass Service:\n    def __init__(self, timeout: timedelta | None):\n"
        "        self.timeout = timeout or timedelta(seconds=5)\n",
    ),
    EvaluationCase(
        "required-nullable-retained-absence",
        Language.PYTHON,
        "class Service:\n    def __init__(self, cache: Cache | None):\n        self.cache = cache\n",
    ),
    EvaluationCase(
        "required-nullable-rebound-before-fallback",
        Language.PYTHON,
        "class Service:\n    def __init__(self, client: Client | None):\n        client = lookup(client)\n"
        "        self.client = client or Client()\n",
    ),
    EvaluationCase(
        "required-nullable-fallback-in-nested-scope",
        Language.PYTHON,
        "class Service:\n    def __init__(self, client: Client | None):\n"
        "        self.make = lambda client=None: client or Client()\n",
    ),
)


def _check(source: str, path: str = "app/service.py") -> list[Diagnostic]:
    return PreferRequiredConstructorParameters().check(Path(path), source)


@pytest.mark.parametrize("case", _CASES, ids=[case.case_id for case in _CASES])
def test_labeled_cases(case: EvaluationCase) -> None:
    findings = _check(case.source)
    assert bool(findings) is (case.expected is ExpectedOutcome.MATCH)
    assert len(findings) <= 1
    assert all(finding.code == "SARJ468" and finding.severity is Severity.WARNING for finding in findings)


@pytest.mark.parametrize(
    "default",
    [
        "False",
        "0",
        "3",
        "[]",
        "{}",
        "()",
        "SENTINEL",
        "factory()",
        "...",
        "lambda: 0",
        "{**options}",
        "Service.DEFAULT",
    ],
)
def test_any_default_expression_requires_review(default: str) -> None:
    assert len(_check(f"class Service:\n    def __init__(self, value={default}): ...\n")) == 1


def test_positional_defaults_align_to_trailing_parameters() -> None:
    source = "class Service:\n    def __init__(self, required, first=1, /, second=2, *, mandatory, third=None): ...\n"
    findings = _check(source)
    line = source.splitlines()[1]
    assert [(finding.line, finding.col) for finding in findings] == [
        (2, line.index("first") + 1),
        (2, line.index("second") + 1),
        (2, line.index("third") + 1),
    ]


def test_keyword_only_required_none_annotation_differs_from_none_default() -> None:
    source = "class Service:\n    def __init__(self, *, required: str | None, optional: str | None = None): ...\n"
    findings = _check(source)
    assert len(findings) == 1
    assert findings[0].col == source.splitlines()[1].index("optional") + 1


def test_variadic_parameters_and_nullable_return_have_no_default() -> None:
    assert _check("class Service:\n    def __init__(self, *args, **kwargs) -> str | None: ...\n") == []


def test_overload_implementation_warns_once() -> None:
    source = (
        "from typing import overload\n"
        "class Service:\n"
        "    @overload\n"
        "    def __init__(self, value: str = ''): ...\n"
        "    @overload\n"
        "    def __init__(self, value: int = 0): ...\n"
        "    def __init__(self, value=None): ...\n"
    )
    assert [finding.line for finding in _check(source)] == [7]


@pytest.mark.parametrize("path", ["tests/test_service.py", "app/service.pyi"])
def test_excluded_sources(path: str) -> None:
    assert _check("class Service:\n    def __init__(self, value=None): ...\n", path) == []


def test_generated_source_is_excluded() -> None:
    assert _check("# Generated by tool\nclass Service:\n    def __init__(self, value=None): ...\n") == []


@pytest.mark.parametrize(
    "path",
    ["app/testability.py", "app/testing/service.py", "app/service_stub.py", "app/service_test_helper.py"],
)
def test_authored_production_paths_are_not_test_exclusions(path: str) -> None:
    assert len(_check("class Service:\n    def __init__(self, value=None): ...\n", path)) == 1


@pytest.mark.parametrize("comment", ["# Generated with AI assistance", "# Generate tokens for authentication"])
def test_attribution_and_runtime_generation_are_not_ownership_banners(comment: str) -> None:
    assert len(_check(f"{comment}\nclass Service:\n    def __init__(self, value=None): ...\n")) == 1


def test_descriptors_still_consume_defaults_during_construction() -> None:
    choices: list[str] = []

    class StaticService:
        @staticmethod
        def __init__(value: str = "static") -> None:
            choices.append(value)

    class ClassService:
        @classmethod
        def __init__(cls, value: str = "class") -> None:
            choices.append(value)

    StaticService()
    ClassService()
    assert choices == ["static", "class"]


def test_exact_suppression_and_manual_fix_policy() -> None:
    source = "class Service:\n    def __init__(self, value=None): ...  # sarj-noqa: SARJ468 -- library compatibility\n"
    finding = _check(source)[0]
    assert is_suppressed(source.splitlines(), finding.line, finding.code)
    assert not is_suppressed(source.splitlines(), finding.line, "SARJ095")
    documentation = PreferRequiredConstructorParameters.documentation
    assert documentation is not None
    assert documentation.autofix is AutofixPolicy.NONE


@pytest.mark.parametrize(
    ("contract", "expected"),
    [
        ("from typing import Protocol\nclass Cache(Protocol):\n    def get(self, key: str) -> str: ...\n", 1),
        ("import abc\nclass Cache(abc.ABC):\n    @abc.abstractmethod\n    def get(self, key: str) -> str: ...\n", 1),
        ("from typing import Protocol\nclass Cache(Protocol):\n    size: int\n", 0),
        ("class Cache:\n    def get(self, key: str) -> str:\n        return key\n", 0),
        ("from pydantic import BaseModel\nclass Cache(BaseModel):\n    size: int\n", 0),
    ],
    ids=["protocol", "abc", "attribute-protocol", "concrete-class", "model"],
)
def test_nullable_interface_dependency(tmp_path: Path, contract: str, expected: int) -> None:
    package = tmp_path / "project" / "app"
    package.mkdir(parents=True)
    (tmp_path / "project" / "pyproject.toml").write_text("[project]\nname = 'example'\nversion = '0.1.0'\n")
    (package / "__init__.py").write_text("")
    (package / "contracts.py").write_text(contract)
    service = package / "service.py"
    service.write_text(
        "from app.contracts import Cache\n"
        "class Service:\n"
        "    def __init__(self, cache: Cache | None, label: str | None) -> None:\n"
        "        self.cache = cache\n"
    )
    sources = {path: path.read_text() for path in (package / "contracts.py", service)}
    rule = PreferRequiredConstructorParameters()
    rule.prepare(ProjectIndexSet.build(list(sources), sources))
    findings = rule.check(service, sources[service])
    assert len(findings) == expected
    assert all("`cache` is nullable" in finding.message for finding in findings)


def test_repeated_checks_are_stable() -> None:
    source = "class Service:\n    def __init__(self, value=None): ...\n"
    rule = PreferRequiredConstructorParameters()
    assert rule.check(Path("app/service.py"), source) == rule.check(Path("app/service.py"), source)
