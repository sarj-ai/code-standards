from typing import Final


SHELLCHECK_ARGS: Final = (
    "--norc",
    "--extended-analysis=true",
    "--enable=check-extra-masked-returns,check-set-e-suppressed",
    "--severity=info",
    "--source-path=SCRIPTDIR",
    "--format=json1",
)
ACTION_EXCLUSIONS: Final = "SC1091,SC2194,SC2050,SC2153,SC2154,SC2157,SC2043"
WARNING_RULES: Final = frozenset({"SC2310", "SC2311"})
ERROR_RULES: Final = frozenset(
    {
        "SC1001",
        "SC1003",
        "SC1007",
        "SC1010",
        "SC1011",
        "SC1012",
        "SC1014",
        "SC1078",
        "SC1079",
        "SC1083",
        "SC1107",
        "SC1110",
        "SC1111",
        "SC1112",
        "SC1132",
    }
)
