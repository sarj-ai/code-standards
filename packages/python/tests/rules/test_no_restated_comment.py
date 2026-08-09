from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.no_restated_comment import NoRestatedComment


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


_PUBLIC_EXAMPLES = NoRestatedComment.public_examples()


def _check(source: str) -> list[Diagnostic]:
    return NoRestatedComment().check(Path("<t>.py"), source)


@pytest.mark.parametrize(
    "example",
    _PUBLIC_EXAMPLES,
    ids=tuple(example.example_id for example in _PUBLIC_EXAMPLES),
)
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file

    findings = NoRestatedComment().check(Path(focus.path), focus.source)

    assert len(findings) == example.expected_count


def _pair(comment: str, code: str) -> list[Diagnostic]:
    """Wrap a pair with a differently shaped trailing statement."""
    return _check(f"def f():\n    # {comment}\n    {code}\n    return None\n")


RESTATEMENTS = [
    ("Get profile by national ID", "profile = self._store.get_profile_by_national_id(national_id, bank_id)"),
    ("Update last login", "await self.user_store.update_last_login(user_id)"),
    ("Create token pair", "tokens = self.jwt_service.create_token_pair(user)"),
    ("Complete onboarding", "_complete_onboarding(client, national_id)"),
    ("Format amounts for voice", "formatted = format_currency_for_voice(amount)"),
    ("set_inheritable", "s1.set_inheritable(False)"),
    ("return the user", "return get_user(user_id)"),
]


@pytest.mark.parametrize(("comment", "code"), RESTATEMENTS)
def test_flags_zero_information_comment(comment: str, code: str):
    diags = _pair(comment, code)
    assert len(diags) == 1
    assert diags[0].code == "SARJ049"
    assert (diags[0].line, diags[0].col) == (2, 5)


def test_one_unmatched_word_keeps_the_comment():
    # `bank` appears nowhere on the line — the comment carries something.
    assert _pair("Get bank profile by national ID", "profile = self._store.get_profile_by_national_id(nid)") == []


def test_no_prefix_matching():
    # Identifier parts count, but arbitrary prefixes do not.
    assert _pair("valid config", "validate(configure_all())") == []


def test_plural_folds_to_singular():
    assert len(_pair("format amounts", "format_amount(x)")) == 1


@pytest.mark.parametrize(
    ("comment", "code"),
    [
        ("Get current user", "user: User = get_current_user()"),
        ("Get current user", "user: User = await get_current_user()"),
        ("Create user token", "user, token = create_user_token()"),
        ("Create user token", "(user, token) = await create_user_token()"),
        ("Create user token", "[user, token] = create_user_token()"),
    ],
)
def test_flags_restatement_above_typed_or_destructuring_action_assignment(comment: str, code: str):
    assert len(_pair(comment, code)) == 1


@pytest.mark.parametrize(
    "code",
    [
        "user: User",
        "user: User = cached_user",
        "user, token = cached_pair",
        "[user, token] = cached_pair",
    ],
)
def test_typed_or_destructuring_data_assignment_is_not_an_action(code: str):
    assert _pair("current user token", code) == []


def test_novel_context_keeps_typed_assignment_comment():
    assert _pair("Get admin current user", "user: User = get_current_user()") == []


def test_multiline_typed_action_uses_the_whole_ast_statement():
    src = (
        "def f():\n"
        "    # Get current user\n"
        "    user: User = await (\n"
        "        get_current_user()\n"
        "    )\n"
        "    return user\n"
    )
    assert len(_check(src)) == 1


def test_multiline_action_with_novel_context_keeps_comment():
    src = (
        "def f():\n"
        "    # Get admin current user\n"
        "    user: User = await (\n"
        "        get_current_user()\n"
        "    )\n"
        "    return user\n"
    )
    assert _check(src) == []


def test_destructuring_group_label_is_kept():
    src = (
        "def f():\n"
        "    # Create user tokens\n"
        "    user, token = create_user_token()\n"
        "    admin, admin_token = create_admin_token()\n"
    )
    assert _check(src) == []


def test_destructuring_region_label_is_kept():
    src = (
        "def f():\n"
        "    # Create user token\n"
        "    user, token = create_user_token()\n"
        "    persist(user)\n"
        "    persist(token)\n"
    )
    assert _check(src) == []


@pytest.mark.parametrize(
    "header",
    [
        "def build_instructions():",
        "class Instructions:",
        "if build_instructions():",
        "for instruction in instructions:",
        "while build_instructions():",
        "with build_instructions():",
        "try:",
    ],
)
def test_comment_above_a_block_is_a_region_label(header: str):
    assert _check(f"# build instructions\n{header}\n    pass\n") == []


@pytest.mark.parametrize(
    "src",
    [
        "def f():\n    # register secrets\n    register_secret(a)\n    register_secret(b)\n",
        "# load config\nconfig = load_config()\nother = load_config()\n",
        "# import profile\nimport profile\nimport account\n",
        'values = {\n    # load profile\n    "profile": load_profile(),\n    "account": load_account(),\n}\n',
        "def f():\n    # assert profile\n    assert profile()\n    assert account()\n",
    ],
)
def test_group_label_over_same_shape_siblings_is_kept(src: str):
    assert _check(src) == []


def test_group_label_skips_a_multiline_first_statement():
    src = "def f():\n    # register secrets\n    register_secret(\n        a,\n    )\n    register_secret(b)\n"
    assert _check(src) == []


def test_multi_line_comment_run_is_a_paragraph():
    src = "def f():\n    # why we do this at all\n    # update last login\n    await update_last_login(user)\n"
    assert _check(src) == []


def test_data_declaration_is_a_labelled_group_not_narration():
    # One first-party enum module — `# Profile` sits between `# MFA/OTP` and
    # `# Account`, labelling one enum member each.
    assert _check('class E:\n    # profile not found\n    PROFILE_NOT_FOUND = "PROFILE_NOT_FOUND"\n') == []


def test_kwarg_group_label_is_kept():
    src = "x = build(\n    a=1,\n    # onboarding stage\n    onboarding_stage=stage,\n)\n"
    assert _check(src) == []


@pytest.mark.parametrize(
    "src",
    [
        pytest.param(
            "await reproduce(\n"
            "    hass,\n"
            "    [\n"
            "        # Test invalid state\n"
            '        State("input_number.test_number", "invalid_state"),\n'
            "    ],\n"
            ")\n",
            id="list-element-label",
        ),
        pytest.param(
            "responses = [\n"
            "    # Stream URL 1\n"
            "    make_stream_url_response(expiration, token_num=1),\n"
            "    # Stream URL 2\n"
            "    make_stream_url_response(expiration, token_num=2),\n"
            "]\n",
            id="repeated-element-labels",
        ),
    ],
)
def test_comment_inside_a_bracketed_expression_labels_an_element(src: str):
    # home-assistant tests/components/input_number/test_reproduce_state.py:63 and
    # tests/components/nest/test_camera.py:379 — the element's own words are what
    # the label names, and deleting the label loses which case is which.
    assert _check(src) == []


@pytest.mark.parametrize(
    "code",
    [
        "assert not executor.task_queue.empty()",
        'assert state.attributes.get("task_queue") is None',
        "assert task_queue != empty",
    ],
)
def test_negation_in_the_code_makes_a_positive_comment_informative(code: str):
    # The positive comment translates code expressed as a negative.
    assert _pair("the task queue", code) == []


@pytest.mark.parametrize(
    "comment",
    [
        "update last login (PROJ-249)",
        "update last login — see https://example.com/docs",
        "update last login every 30 seconds",
        "update last login because the session store is authoritative",
        "update last login, never on a read path",
        "update last login? ",
        "can also update last login",
        "should update last login",
        "update last login:",
        "update *last* login",
        "update `last_login`",
        "TODO: update last login",
        "noqa: update last login",
        "sarj-noqa: SARJ049 — deliberate",
    ],
)
def test_protected_and_directive_comments_are_kept(comment: str):
    assert _pair(comment, "await self.user_store.update_last_login(user_id)") == []


def test_arabic_prose_is_never_flagged():
    # The tokenizer cannot read it, so the zero-information test would be
    # vacuously true.
    assert _pair("تحديث آخر تسجيل دخول", "await self.user_store.update_last_login(user_id)") == []


def test_single_content_word_is_a_label_not_a_restatement():
    assert _pair("Hashing", "hash(b)") == []


def test_long_comment_is_not_a_restatement():
    comment = "update the last login timestamp for the user record on every call"
    assert _pair(comment, "await self.user_store.update_last_login(user_id)") == []


def test_commented_out_code_belongs_to_sarj016():
    assert _check("x = 1\n# assert v.to_python(value) == v\nassert v.to_python(value, mode='json') == v\n") == []


def test_banner_is_not_a_restatement():
    assert _check("x = 1\n# ==== update ====\nupdate(x)\n") == []


def test_generated_file_is_skipped():
    src = "# Code generated by openapi-generator. DO NOT EDIT.\ndef f():\n    # update user\n    update_user(u)\n    return None\n"
    assert _check(src) == []


def test_unparseable_source_returns_nothing():
    assert _check("def (:\n") == []


def test_comment_at_end_of_file_is_safe():
    assert _check("x = 1\n# update user\n") == []


def test_comment_above_a_blank_line_is_not_about_the_next_statement():
    assert _check("def f():\n    # update user\n\n    update_user(u)\n") == []


# A section label heading a multi-statement region.                           #


def test_a_label_heading_a_three_line_region_is_not_narration():
    source = (
        "def f():\n"
        "    # Create token pair\n"
        "    tokens = self.jwt_service.create_token_pair(user)\n"
        "    persist(tokens)\n"
        "    audit(tokens)\n"
    )
    assert _check(source) == []


def test_a_label_heading_a_two_line_region_still_fires():
    source = (
        "def f():\n    # Create token pair\n    tokens = self.jwt_service.create_token_pair(user)\n    assert tokens\n"
    )
    assert len(_check(source)) == 1


def test_a_blank_line_ends_the_region():
    source = (
        "def f():\n"
        "    # Create token pair\n"
        "    tokens = self.jwt_service.create_token_pair(user)\n"
        "\n"
        "    persist(tokens)\n"
        "    audit(tokens)\n"
    )
    assert len(_check(source)) == 1


def test_the_next_label_ends_the_region():
    source = (
        "def f():\n"
        "    # Create token pair\n"
        "    tokens = self.jwt_service.create_token_pair(user)\n"
        "    # Act\n"
        "    response = call(tokens)\n"
        "    # Assert\n"
        "    check(response)\n"
    )
    assert len(_check(source)) == 1


def test_matching_only_a_string_literal_still_fires():
    assert len(_pair("set false", 'variables_set(["variables", "set", "false"])')) == 1


def test_nearby_comment_with_shared_vocabulary_does_not_hide_restatement():
    source = (
        "def f():\n"
        "    # Update user profile\n"
        "    update_user_profile(user)\n"
        "    # Audit user profile\n"
        "    audit_user_profile(user)\n"
    )
    assert [diagnostic.line for diagnostic in _check(source)] == [2, 4]


def test_consistently_numbered_walkthrough_run_is_preserved():
    source = """\
def write_report(table):
    # 1. Source reconciliation
    add("Source reconciliation")
    if table.source:
        reconcile(table)
    # 2. Key integrity
    add("Key integrity")
    for key in table.keys:
        validate(key)
    # 3. Dead columns
    add("Dead columns")
    if table.dead_columns:
        report(table.dead_columns)
"""
    assert _check(source) == []


def test_isolated_numbered_restatement_still_fires():
    source = """\
def write_report(table):
    # 6. Dead columns
    add("## 6. Dead columns")
    if table.dead_columns:
        report(table.dead_columns)
"""
    assert len(_check(source)) == 1


def test_non_monotonic_numbered_comments_are_not_a_walkthrough_run():
    source = """\
def write_report(table):
    # 1. Source reconciliation
    add("## 1. Source reconciliation")
    if table.source:
        reconcile(table)
    # 3. Key integrity
    add("## 3. Key integrity")
    for key in table.keys:
        validate(key)
    # 4. Dead columns
    add("## 4. Dead columns")
    if table.dead_columns:
        report(table.dead_columns)
"""
    assert len(_check(source)) == 3
