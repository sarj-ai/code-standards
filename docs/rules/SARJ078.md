# SARJ078 `prefer-self-type-annotation` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_prefer_self_type_annotation.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

Python 3.11 (PEP 673) introduced `typing.Self` to annotate methods that return an instance
of their enclosing class (fluent interface builders, `__enter__`, `copy`, factory methods,
classmethod constructors, etc.).

Using string literal forward references like `"MyClass"` or explicit class name annotations
in return position is less accurate (fails on subclasses) and unnecessary in modern Python.

    # flagged
    class ConfigBuilder:
        def set_timeout(self, seconds: int) -> "ConfigBuilder":
            self.timeout = seconds
            return self

    # preferred
    from typing import Self

    class ConfigBuilder:
        def set_timeout(self, seconds: int) -> Self:
            self.timeout = seconds
            return self
