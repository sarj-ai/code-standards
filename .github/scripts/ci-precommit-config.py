from __future__ import annotations  # ruff: ignore[implicit-namespace-package] -- standalone entry point invoked by file path.

import json
from pathlib import Path
import sys


def main() -> None:
    repo = Path(sys.argv[2]).resolve().as_uri()
    config = {"repos": [{"repo": repo, "rev": sys.argv[3], "hooks": [{"id": "sarj-standards"}]}]}
    Path(sys.argv[1]).write_text(json.dumps(config), encoding="utf-8")


if __name__ == "__main__":
    main()
