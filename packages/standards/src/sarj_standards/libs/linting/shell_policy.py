from typing import Final


SHELLCHECK_ARGS: Final = (
    "--norc",
    "--extended-analysis=true",
    "--enable=check-extra-masked-returns",
    "--severity=info",
    "--source-path=SCRIPTDIR",
    "--format=json1",
)
# These upstream actionlint exclusions apply only to Actions execution environments.
ACTION_EXCLUSIONS: Final = "SC1091,SC2194,SC2050,SC2153,SC2154,SC2157,SC2043"
