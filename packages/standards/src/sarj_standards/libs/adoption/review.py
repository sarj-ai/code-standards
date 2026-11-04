from __future__ import annotations


START = "# BEGIN code-standards review defaults"
END = "# END code-standards review defaults"
_TEST_PATTERNS = (
    "test_*.py",
    "*_test.py",
    "conftest.py",
    "**/tests/**",
    "**/test/**",
    "**/__tests__/**",
    "**/__snapshots__/**",
    *(
        f"*.{kind}.{extension}"
        for kind in ("test", "spec")
        for extension in ("js", "jsx", "ts", "tsx", "mjs", "cjs", "mts", "cts")
    ),
)


def attributes_with_review_defaults(contents: str) -> str:
    prefix = "\ufeff" if contents.startswith("\ufeff") else ""
    contents = contents.removeprefix("\ufeff")
    newline = "\r\n" if "\r\n" in contents else "\n"
    block = newline.join(
        (
            START,
            "# Collapse tests in GitHub diffs; reviewers can expand them.",
            "# GitHub also excludes these paths from language statistics.",
            "# Keep repository overrides after this block, or in a nested .gitattributes.",
            *(f"{pattern} linguist-generated=true" for pattern in _TEST_PATTERNS),
            END,
            "",
        )
    )
    lines = contents.splitlines(keepends=True)
    starts = [index for index, line in enumerate(lines) if line.rstrip("\r\n") == START]
    ends = [index for index, line in enumerate(lines) if line.rstrip("\r\n") == END]
    if not starts and not ends:
        return prefix + block + (newline + contents if contents else "")
    if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
        msg = "malformed code-standards review defaults block in .gitattributes"
        raise ValueError(msg)
    return prefix + "".join(lines[: starts[0]]) + block + "".join(lines[ends[0] + 1 :])
