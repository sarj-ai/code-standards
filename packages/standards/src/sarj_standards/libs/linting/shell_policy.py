from typing import Final


SHELLCHECK_ARGS: Final = (
    "--norc",
    "--extended-analysis=true",
    "--enable=check-extra-masked-returns,check-set-e-suppressed",
    "--severity=info",
    "--source-path=SCRIPTDIR",
    "--format=json1",
)
# These upstream actionlint exclusions apply only to Actions execution environments.
ACTION_EXCLUSIONS: Final = "SC1091,SC2194,SC2050,SC2153,SC2154,SC2157,SC2043"
WARNING_RULES: Final = frozenset({"SC2310", "SC2311"})
