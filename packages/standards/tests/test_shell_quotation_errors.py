from __future__ import annotations

from collections import Counter
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from sarj_standards import api
from sarj_standards.libs.diagnostics import Completion, Severity, TrustMode, baseline
from sarj_standards.libs.linting.analysis import report_from_tools
from sarj_standards.libs.linting.external import analyze_external


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("rule", "source", "allowed", "fingerprints"),
    [
        pytest.param(
            "SC1001",
            "#!/bin/bash\nprintf '%s\\n' \\q\n",
            "#!/bin/bash\nprintf '%s\\n' q\n",
            ("23a214b9ae9e4794f12744cf62c8a655e16370ef60ca523cddb74ae4db501307",),
            id="SC1001",
        ),
        pytest.param(
            "SC1003",
            "#!/bin/bash\nprintf '%s\\n' 'abc\\'\n",
            "#!/bin/bash\nprintf '%s\\n' 'abc'\\\\\n",
            ("12428e3f7dc28edb0c4f83ad78259df09a7299576b6b71b9427701cd608dcb5b",),
            id="SC1003",
        ),
        pytest.param(
            "SC1007",
            '#!/bin/bash\nLANGUAGE= sh -c \'printf "<%s>\\n" "$LANGUAGE"\'\n',
            "#!/bin/bash\nLANGUAGE='' sh -c 'printf \"<%s>\\n\" \"$LANGUAGE\"'\n",
            ("1f882d0b7c77ece2d2f1f9f1627b37afefcc5552bd8f969c960afc6f4e188a7b",),
            id="SC1007",
        ),
        pytest.param(
            "SC1010",
            "#!/bin/bash\nprintf '%s\\n' done\n",
            "#!/bin/bash\nprintf '%s\\n' 'done'\n",
            ("04d38f87c6d5f8414da029ecd92ad850f29fc1366c8e047ef423c52b1f351158",),
            id="SC1010",
        ),
        pytest.param(
            "SC1011",
            "#!/bin/bash\nprintf '%s\\n' 'abc'def\n",
            "#!/bin/bash\nprintf '%s\\n' 'abcdef'\n",
            ("9f7bb5c308fca4623ad4d015b1b4165d6e11e262d7e773c01aab064417c0035d",),
            id="SC1011",
        ),
        pytest.param(
            "SC1012",
            "#!/bin/bash\nprintf '%s\\n' a\\nb\n",
            "#!/bin/bash\nprintf '%s\\n' anb\n",
            ("a334fb173cdf9649d2d1ef3bd4f95bea93082785d748b4bfc8a4af9538645754",),
            id="SC1012",
        ),
        pytest.param(
            "SC1014",
            '#!/bin/bash\nname=${1:-grep}\n[ grep = "$name" ] && printf "same\\n"\n',
            '#!/bin/bash\nname=${1:-grep}\n[ \'grep\' = "$name" ] && printf "same\\n"\n',
            ("891852db3d1785f55ed9dd18d6647b51eeb1b989dfc2a24b8c8a308d5186d533",),
            id="SC1014",
        ),
        pytest.param(
            "SC1078",
            "#!/bin/bash\nprintf '%s\\n' \"line1\nline2\"suffix\n",
            "#!/bin/bash\nprintf '%s\\n' \"line1\nline2suffix\"\n",
            ("fa31d7d826f9b885ca6beacb12838961d258e1c2b32563ba6bf814d40c045a14",),
            id="SC1078",
        ),
        pytest.param(
            "SC1079",
            "#!/bin/bash\nprintf '%s\\n' \"line1\nline2\"suffix\n",
            "#!/bin/bash\nprintf '%s\\n' \"line1\nline2suffix\"\n",
            ("7ea2132a5f7a2c72b8e1626e605f39780585ff9a963305ca151766ae28f366a0",),
            id="SC1079",
        ),
        pytest.param(
            "SC1083",
            "#!/bin/bash\nprintf '%s\\n' a{b}\n",
            "#!/bin/bash\nprintf '%s\\n' 'a{b}'\n",
            (
                "f2cae314db03480cef5d1018cb51ca4c3090fe720d51b4994f6c84dc0035580d",
                "fb9f44bc69fe5d539913765c66bb8aa2a2841b8a897507cfc707c546b441e5ad",
            ),
            id="SC1083",
        ),
        pytest.param(
            "SC1107",
            '#!/bin/bash\n# shellcheck unrecognized=directive\nprintf "ready\\n"\n',
            '#!/bin/bash\n# shellcheck shell=bash\nprintf "ready\\n"\n',
            ("1f15da2ac2b495a44290ca863f9017ba1f3e6e265bdb67e25aaa0843b7d8f9f5",),
            id="SC1107",
        ),
        pytest.param(
            "SC1110",
            "#!/bin/bash\nprintf '%s\\n' “value”\n",
            "#!/bin/bash\nprintf '%s\\n' '“value”'\n",
            (
                "7707739552cf85d5a471226f38a16e8ad7d0737b6330594e9d6d7a9d492e4da4",
                "7707739552cf85d5a471226f38a16e8ad7d0737b6330594e9d6d7a9d492e4da4",
            ),
            id="SC1110",
        ),
        pytest.param(
            "SC1111",
            "#!/bin/bash\nname=value\nprintf '%s\\n' \"“$name”\"\n",
            "#!/bin/bash\nname=value\nprintf '%s\\n' '“'\"$name\"'”'\n",
            (
                "2817aef4a74fa0c5faee753e81e7549faa59b92b68650bda39ed6e8ad052d5bb",
                "2817aef4a74fa0c5faee753e81e7549faa59b92b68650bda39ed6e8ad052d5bb",
            ),
            id="SC1111",
        ),
        pytest.param(
            "SC1112",
            "#!/bin/bash\nprintf '%s\\n' 'can’t'\n",
            "#!/bin/bash\nprintf '%s\\n' \"can’t\"\n",
            ("a241f4e64c4a955712fcb9d19191a9eb5396d5622855e04c9ab87045e6ceedba",),
            id="SC1112",
        ),
        pytest.param(
            "SC1132",
            "#!/bin/bash\nprintf 'done\\n'&wait\n",
            "#!/bin/bash\nprintf 'done\\n' & wait\n",
            ("fd01a729ecac47cbeafbfbc98dabc3ef4ad49101ab31978a5cb9557f67de4e03",),
            id="SC1132",
        ),
    ],
)
def test_shell_quotation_errors_preserve_exact_debt_and_native_suppressions(
    tmp_path: Path, rule: str, source: str, allowed: str, fingerprints: tuple[str, ...]
) -> None:
    path = tmp_path / "case.sh"
    path.write_text(source)
    [tool] = analyze_external((str(path),), root=tmp_path, trust=TrustMode.SAFE, capabilities=frozenset({"shellcheck"}))
    report = report_from_tools(tmp_path, (tool,))
    findings = tuple(item for item in report.diagnostics if item.rule_id == rule)
    assert report.completion is Completion.COMPLETE
    assert report.exit_code == 1
    assert tuple(item.fingerprint for item in findings) == fingerprints
    assert all(item.severity is Severity.ERROR for item in findings)
    # Accepted warning debt uses the same occurrence counts after promotion.
    old = tuple(replace(item, severity=Severity.WARNING) for item in findings)
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        baseline.render(
            old,
            bundle_version=api.__version__,
            consumer_base_sha="0" * 40,
            catalog_digest=baseline.bundled_catalog_digest(),
        )
    )
    counts = baseline.load(baseline_path)
    assert sum(counts.values()) == len(findings)
    assert counts == Counter(fingerprints)
    path.write_text(allowed)
    [allowed_tool] = analyze_external(
        (str(path),), root=tmp_path, trust=TrustMode.SAFE, capabilities=frozenset({"shellcheck"})
    )
    assert allowed_tool.completion is Completion.COMPLETE
    assert not allowed_tool.diagnostics
    path.write_text(source.replace("#!/bin/bash\n", f"#!/bin/bash\n# shellcheck disable={rule}\n", 1))
    [suppressed] = analyze_external(
        (str(path),), root=tmp_path, trust=TrustMode.SAFE, capabilities=frozenset({"shellcheck"})
    )
    assert suppressed.completion is Completion.COMPLETE
    # ShellCheck reports an unknown directive before processing its annotations.
    assert any(item.rule_id == rule for item in suppressed.diagnostics) is (rule == "SC1107")
