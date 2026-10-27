import ast
from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.autofix import fix_source
from sarj_python_lint.rules.excessive_commentary import ExcessiveCommentary


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample, Severity


_PUBLIC_EXAMPLES = ExcessiveCommentary.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(ExcessiveCommentary().check(Path(focus.path), focus.source)) == example.expected_count


def test_original_activation_rationale_is_not_mechanically_proven_noise() -> None:
    source = """def reasons_not_to_activate():
    # Everything standing between this integration and being usable.
    # Returns all the reasons rather than the first failure.
    # Someone activating a half-built integration wants the complete list.
    # That avoids discovering one problem per round trip.
    reasons = []
    reasons.extend(integration_reasons())
    reasons.extend(endpoint_reasons())
    reasons.extend(action_reasons())
    return reasons
"""
    assert ExcessiveCommentary().check(Path("activation.py"), source) == []


@pytest.mark.parametrize(
    ("path", "source"),
    [
        ("generated/client.py", "\n".join(f"# Narrative implementation sentence number {i}." for i in range(8))),
        ("app.py", "# noqa: explanation one two three four five six seven eight\nvalue = 1\n"),
        ("app.py", "# First constraint.\n# - one mode\n# - another mode\n# - fallback mode\nvalue = 1\n"),
    ],
)
def test_owned_exclusions_do_not_report(path: str, source: str) -> None:
    assert ExcessiveCommentary().check(Path(path), source) == []


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            (
                "# Keep `traceparent` because RFC-812 requires propagation.\n"
                "# The timeout is 10 ms.\n"
                "# The client reads wire_value.\n"
                "# Remove this with API-901.\nvalue = 1\n"
            ),
            [],
        ),
        (
            (
                "# Keep this ordering because cleanup can outlive the command.\n"
                "# Otherwise a background task can retain the temporary directory.\n"
                "# The cleanup must never mask the command outcome.\n"
                "# This invariant also prevents a retry race.\nvalue = 1\n"
            ),
            [],
        ),
    ],
)
def test_constraints_and_references_do_not_have_a_length_budget(source: str, expected: list[Severity]) -> None:
    assert [finding.severity for finding in ExcessiveCommentary().check(Path("app.py"), source)] == expected


def test_three_extends_are_not_a_comment_or_comprehension_violation() -> None:
    source = """reasons = []
reasons.extend(integration_reasons())
reasons.extend(endpoint_reasons())
reasons.extend(action_reasons())
"""
    assert ExcessiveCommentary().check(Path("activation.py"), source) == []


def test_long_prose_without_corresponding_action_names_is_not_proven_noise() -> None:
    source = """def render_response():
    # This paragraph describes several nearby implementation choices in detail.
    # It has enough words and lines to exceed the general prose budget used here.
    # Mature projects sometimes retain such context while a subsystem is evolving.
    # The paragraph describes another ordinary step before building the response.
    response = build_response()
    return response
"""
    assert ExcessiveCommentary().check(Path("response.py"), source) == []


def test_empty_collection_does_not_prove_ownership_of_the_paragraph() -> None:
    source = """def collect_items():
    # This paragraph describes several nearby implementation choices in detail.
    # It has enough words and lines to exceed the general prose budget used here.
    # An empty collection alone does not prove that the prose narrates accumulation.
    # Require repeated adjacent mutation calls to keep the warning high confidence.
    items = []
    return load_items(items)
"""
    assert ExcessiveCommentary().check(Path("items.py"), source) == []


def test_protocol_shape_and_rejection_contract_is_not_proven_noise() -> None:
    source = """def authentication_methods(payload):
    # Inspect this field only when the selected identity provider uses it.
    # Its value contains the RFC 8176 method names as a list of strings.
    # Another shape indicates an invalid provider response and causes rejection.
    # The validator rejects malformed data instead of interpreting it as absent.
    methods = payload.get("methods")
    return methods
"""
    assert ExcessiveCommentary().check(Path("app.py"), source) == []


def test_concise_protocol_constraint_remains_allowed() -> None:
    source = '# RFC 8176 defines these method identifiers.\n# Keep unknown identifiers opaque at this boundary.\nmethods = payload["methods"]\n'
    assert ExcessiveCommentary().check(Path("app.py"), source) == []


def test_constraint_before_accumulation_is_preserved() -> None:
    source = """def reasons():
    # Collect every failure because the caller presents the complete set.
    # Otherwise a retry reveals only the next missing prerequisite each time.
    # The operator needs every failed prerequisite from the same observed state.
    # Keep the returned order stable while the caller repairs those prerequisites.
    failures = []
    failures.extend(connection_failures())
    failures.extend(configuration_failures())
    return failures
"""
    assert ExcessiveCommentary().check(Path("app.py"), source) == []


_COMMENT_BLOCKS = (
    (
        "narration",
        "Build the complete response from the supplied input values.\nThen collect the selected fields and prepare the response values.\nFinally return the completed response to the original caller.",
        0,
    ),
    (
        "walkthrough",
        "Start by collecting the available values for this operation.\nNext convert the selected values into the expected response shape.\nThe following expression then returns those values to its caller.",
        0,
    ),
    (
        "reason",
        "Keep this copy because the downstream client retains its input.\nThe caller can modify its original values after this operation.\nA shared reference would then alter the pending response contents.",
        0,
    ),
    (
        "reference",
        "The upstream wire contract is defined by RFC-8176.\nThe registered vocabulary distinguishes a verified factor from a password.\nChanging this decision requires coordinating the issuer and its consumers.",
        0,
    ),
    (
        "directive",
        "pragma: no cover\nThis branch represents an integration failure during application startup.\nThe integration harness owns this externally triggered recovery path.",
        0,
    ),
)
_COMMENT_CONTEXTS = (
    ("module", "{block}value = build_response()\n", ""),
    ("function", "def render():\n{block}    value = build_response()\n", "    "),
    ("async", "async def render():\n{block}    value = build_response()\n", "    "),
    ("test", "def test_render():\n{block}    value = build_response()\n", "    "),
    ("method", "class Renderer:\n    def render(self):\n{block}        value = build_response()\n", "        "),
    ("loop", "for item in items:\n{block}    value = build_response()\n", "    "),
    ("branch", "if ready:\n{block}    value = build_response()\n", "    "),
    ("context", "with resource():\n{block}    value = build_response()\n", "    "),
    ("nested", "def outer():\n    def render():\n{block}        value = build_response()\n", "        "),
    ("generated", "# Generated by protoc. Do not edit.\n{block}value = build_response()\n", ""),
)


@pytest.fixture
def commentary_rule() -> ExcessiveCommentary:
    return ExcessiveCommentary()


@pytest.mark.parametrize(("kind", "text", "expected"), _COMMENT_BLOCKS, ids=[case[0] for case in _COMMENT_BLOCKS])
@pytest.mark.parametrize(
    ("context", "template", "indent"), _COMMENT_CONTEXTS, ids=[case[0] for case in _COMMENT_CONTEXTS]
)
def test_unproven_prose_is_preserved_across_owners(
    *,
    commentary_rule: ExcessiveCommentary,
    kind: str,
    text: str,
    expected: int,
    context: str,
    template: str,
    indent: str,
) -> None:
    block = "".join(indent + "# " + line + "\n" for line in text.splitlines())
    findings = commentary_rule.check(Path("app/response.py"), template.format(block=block))
    assert len(findings) == (0 if context == "generated" else expected), kind


@pytest.mark.parametrize(("parameters", "expected"), [("", 1), ("list", 0)])
def test_accumulation_proof_depends_on_the_actual_collection_binding(
    commentary_rule: ExcessiveCommentary, parameters: str, expected: int
) -> None:
    source = (
        f"def collect({parameters}):\n"
        "    # Collect current account profile activation reasons\n"
        "    # Collect current endpoint profile activation reasons\n"
        "    result = list()\n"
        "    result.extend(collect_current_account_profile_activation_reasons())\n"
        "    result.extend(collect_current_endpoint_profile_activation_reasons())\n"
        "    return result\n"
    )
    assert len(commentary_rule.check(Path("app.py"), source)) == expected


def test_two_line_generic_walkthrough_does_not_establish_exact_ownership() -> None:
    source = (
        "def prepare():\n"
        "    # The sequence selects the allowed values from the supplied input.\n"
        "    # Then it builds the response and returns the available result.\n"
        "    values = selected_values()\n"
        "    return build_response(values)\n"
    )
    assert ExcessiveCommentary().check(Path("service.py"), source) == []


def test_two_line_hidden_constraint_is_preserved() -> None:
    source = (
        "# Preserve this ordering because the receiver retains the first reference.\n"
        "# Otherwise a subsequent mutation changes the pending request after validation.\n"
        "send_request()\n"
    )
    findings = ExcessiveCommentary().check(Path("service.py"), source)
    assert findings == []


_CASES = (
    pytest.param(
        """
        # A quoted numeric value can still contain a private account identifier.
        # Diagnostic publication is broader than access to the original settings.
        printable_tags = frozenset({"boolean", "number", "null"})
        """,
        id="source-quoting-and-log-publication",
    ),
    pytest.param(
        """
        def conflicts(environments):
            # Later conflicts in one environment share the first conflict's cause.
            # One diagnostic gives the operator the same repair without duplicate reports.
            seen = set()
            return collect_conflicts(environments, seen)
        """,
        id="one-cause-one-diagnostic",
    ),
    pytest.param(
        """
        def suppressions(codes):
            # The advisory route check owns the overlapping annotation diagnosis.
            # Emitting its blocking twin would defeat the staged severity policy.
            return route_suppressions(codes) if "route-policy" in codes else set()
        """,
        id="cross-rule-severity-ownership",
    ),
    pytest.param(
        """
        def supplied_replacement(arguments):
            # The second positional argument supplies the replacement in this signature.
            # A starred argument leaves its position unknown to local syntax analysis.
            return len(arguments) > 1 and not contains_starred(arguments)
        """,
        id="external-positional-parameter-contract",
    ),
    pytest.param(
        """
        # The preview directive takes a rule name while the older directive takes a code.
        # These spellings select the same local restriction through two parser interfaces.
        selectors = frozenset({"R102", "BANNED-API"})
        """,
        id="upstream-selector-syntaxes",
    ),
    pytest.param(
        """
        def frozen(values):
            # Conflicting configuration channels have framework-defined effective precedence.
            # A local literal proof accepts agreement and leaves conflicts to that framework.
            return values == {True}
        """,
        id="framework-configuration-precedence",
    ),
    pytest.param(
        """
        def owned_field(nested):
            # A base class can supply model fields absent from this source file.
            # A base-less helper is the only deterministic local ownership mistake here.
            return None if nested.bases else direct_field(nested)
        """,
        id="unavailable-inherited-fields",
    ),
    pytest.param(
        """
        def test_key(container, asynchronous, signature, decorators):
            # Identical bodies can execute under different fixtures and decorator policies.
            # These identity components keep those tests in separate duplicate groups.
            return container, asynchronous, signature, decorators
        """,
        id="test-identity-versus-body-equivalence",
    ),
    pytest.param(
        """
        # A composition test exercises adapter wiring with its external adapters stubbed.
        # Counting those stubs as ordinary isolation mocks misidentifies the test's purpose.
        composition_names = frozenset({"bootstrap", "lifespan", "wiring"})
        """,
        id="composition-root-test-exception",
    ),
    pytest.param(
        """
        def replace_addition(parts):
            # Reflected addition on expression objects can construct an expression tree.
            # A string literal beside such an object does not establish formatting equivalence.
            return all(is_known_string(part) for part in parts)
        """,
        id="reflected-operator-semantics",
    ),
    pytest.param(
        """
        def update_role(previous, current):
            # Equivalent redeclarations retain the earlier diagnostic's authored source anchor.
            # Replacing that anchor would also change which local suppression owns the finding.
            return previous if equivalent(previous, current) else current
        """,
        id="diagnostic-anchor-and-exact-suppression",
    ),
    pytest.param(
        """
        # Single-character comparisons on scanner variables consume an open character stream.
        # Their vocabulary is not a closed application state suitable for enumeration.
        scanner_names = frozenset({"character", "glyph", "token"})
        """,
        id="tokenizer-versus-enum-domain",
    ),
    pytest.param(
        """
        def child_scope(node):
            # Comprehension targets shadow matching names in the surrounding function scope.
            # Merging their comparisons would combine variables that have distinct bindings.
            return {target: [] for target in bound_targets(node)}
        """,
        id="comprehension-binding-scope",
    ),
    pytest.param(
        """
        def class_effects(statement, inherited):
            # A class body executes immediately while its own names remain class-local.
            # Writes through an imported provider still affect decorators evaluated afterward.
            return decorators_after(statement.body, inherited).modified
        """,
        id="class-execution-and-imported-provider-effects",
    ),
    pytest.param(
        """
        def class_loads(node):
            # Class namespaces and closures used by their methods have different name lookup.
            # Flattening those bodies into the surrounding function merges unrelated bindings.
            return loads_in(node.bases, node.decorator_list)
        """,
        id="class-namespace-versus-method-closure",
    ),
    pytest.param(
        """
        def analyze(operations, jobs):
            # Multiple outer operations share one pool and use serial inner analyzers.
            # A single outer operation can spend the complete budget inside its analyzer.
            with pool(jobs) as workers:
                return list(workers.map(run_serial, operations))
        """,
        id="nested-worker-budget-boundary",
    ),
    pytest.param(
        """
        def nested_configs(selected, plan):
            # At this phase the strict config exists or is already a planned sync target.
            # Nested config checks apply only to an analyzer selected for this adoption.
            return report_nested(plan) if "analyzer" in selected else []
        """,
        id="scaffold-phase-precondition",
    ),
    pytest.param(
        """
        def insert(source, offset, value):
            # A source splice retains comments already attached to the authored array.
            # Unrelated policy tables and their exact capped exceptions retain their text too.
            return source[:offset] + value + source[offset:]
        """,
        id="lossless-configuration-edit",
    ),
    pytest.param(
        """
        def build_substitutions(source):
            # A doubled dollar escapes build substitution before shell parsing begins.
            # Shell quote characters cannot protect a single dollar from that earlier stage.
            return find_substitutions(source.replace("$$", ""))
        """,
        id="build-time-versus-shell-expansion",
    ),
    pytest.param(
        """
        def generated_separator(original_line, projected_suffix):
            # An empty optional argument can leave a generated trailing command separator.
            # Authored whitespace retains its native formatting diagnosis rather than this exemption.
            return bool(projected_suffix) and not original_line.endswith((" ", "\\t"))
        """,
        id="authored-versus-projected-whitespace",
    ),
    pytest.param(
        """
        def eligible_anchor(node):
            # The upstream analyzer establishes unusedness; this filter establishes local ownership.
            # Methods, decorators and framework callbacks retain their external invocation contracts.
            return is_module_helper(node) and not node.decorators
        """,
        id="upstream-diagnostic-proof-ownership",
    ),
    pytest.param(
        """
        def accepted(report):
            # The pinned compact protocol can include warnings even with warnings disabled.
            # Filtering follows complete report validation so discarded entries still get checked.
            validate_report(report)
            return [entry for entry in report.entries if entry.level != "warning"]
        """,
        id="pinned-protocol-and-validation-order",
    ),
    pytest.param(
        """
        def primary_location(raw_locations):
            # Every upstream location is validated even though one diagnostic is emitted.
            # Selecting the first raw location early would leave later locations unchecked.
            locations = tuple(validate_location(item) for item in raw_locations)
            return locations[0]
        """,
        id="validate-all-before-primary-selection",
    ),
    pytest.param(
        """
        def initial_publication(previous, runner):
            # An initial release has no earlier manifest in an otherwise valid tree.
            # A transport failure or invalid revision is not evidence of that absence.
            return not runner.list_tree(previous).strip()
        """,
        id="valid-absence-versus-history-failure",
    ),
    pytest.param(
        """
        def verify(prepare, checks):
            # Preparation can format files that independent verification commands later read.
            # Starting those readers first would give them an inconsistent candidate tree.
            prepare()
            return parallel_checks(checks)
        """,
        id="preparation-before-concurrent-readers",
    ),
    pytest.param(
        """
        # Sandbox observations showed the transfer pending at one second and ready at five.
        # These delays cover that transition with a bounded total polling window.
        poll_delays = (2.0, 1.0, 1.0, 2.0)
        """,
        id="observed-remote-polling-timing",
    ),
    pytest.param(
        """
        # The remote sandbox committed an operation after its advertised acceptance window.
        # The local margin prevents sending a late request that the backend still accepts.
        acceptance_margin = 5
        """,
        id="late-accept-side-effect-safety",
    ),
    pytest.param(
        """
        # The first code denotes an asset the customer does not currently hold.
        # The second denotes an asset record the provider can no longer locate.
        missing_asset_codes = frozenset({Error.REFUSED, Error.NOT_FOUND})
        """,
        id="external-error-code-meanings",
    ),
    pytest.param(
        """
        def offered(item):
            # An expired remote offer can retain the same waiting status as a live offer.
            # Its remaining window supplies the additional evidence needed for acceptance.
            return item.status == "waiting" and item.seconds_left > 0
        """,
        id="nominal-status-versus-effective-expiry",
    ),
    pytest.param(
        """
        async def reconcile(client, request):
            # A lost response can follow a successful remote write of the requested record.
            # The listing settles that uncertainty without issuing another side effect.
            return await client.find_created(request.key)
        """,
        id="uncertain-remote-write-reconciliation",
    ),
    pytest.param(
        """
        def refusal(listing, outcome):
            # A duplicate submission can encounter refusal after its first write succeeded.
            # An unread listing therefore proves neither absence nor a safe final refusal.
            return UNKNOWN if listing is None else outcome
        """,
        id="idempotent-refusal-and-unread-list",
    ),
    pytest.param(
        """
        def highest_maximum(rates, amount):
            # The caller has excluded amounts below every minimum and every eligible rate failed.
            # Each remaining rate consequently has a finite maximum below this amount.
            return max(rate.maximum for rate in rates if rate.minimum <= amount)
        """,
        id="nonlocal-proof-of-finite-maxima",
    ),
)


@pytest.mark.parametrize("source", _CASES)
def test_technical_facts_do_not_become_errors_or_advisories_from_wrapping(source: str) -> None:
    source = dedent(source)
    ast.parse(source)
    path = Path("app/service.py")
    assert ExcessiveCommentary().check(path, source) == []
    assert fix_source(path, source, rule_ids=["excessive-commentary"]) == source
