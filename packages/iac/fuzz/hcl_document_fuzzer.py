# ruff: file-ignore[implicit-namespace-package]

from __future__ import annotations

import sys

import atheris


with atheris.instrument_imports():
    from hcl_document_target import test_one_input


def main() -> None:
    atheris.Setup(sys.argv, test_one_input)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
