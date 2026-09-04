from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.redundant_docstring import RedundantDocstring


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


_PUBLIC_EXAMPLES = RedundantDocstring.public_examples()


def _check(source: str) -> list[Diagnostic]:
    return RedundantDocstring().check(Path("<t>.py"), source)


@pytest.mark.parametrize(
    "example",
    _PUBLIC_EXAMPLES,
    ids=tuple(example.example_id for example in _PUBLIC_EXAMPLES),
)
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file

    findings = RedundantDocstring().check(Path(focus.path), focus.source)

    assert len(findings) == example.expected_count


def _fn(signature: str, docstring: str) -> list[Diagnostic]:
    return _check(f'def {signature}:\n    """{docstring}"""\n    return None\n')


RESTATEMENTS = [
    ("get_profile_by_national_id(national_id: str)", "Get profile by national ID."),
    ("create_version_tag(rl_version: str)", "Create a version tag."),
    ("update_message(task_id: str, message: Message)", "Update task message."),
    ("list_by_organization(org_id: str)", "List by organization."),
    ("_refresh_ttl(key: str)", "Refresh key TTL."),
    ("log_tts_generation(text: str)", "Log TTS generation."),
    ("test_verify_otp_invalid_token(client: TestClient)", "Test verify OTP invalid token."),
]


@pytest.mark.parametrize(("signature", "docstring"), RESTATEMENTS)
def test_flags_name_restating_docstring(signature: str, docstring: str):
    diags = _fn(signature, docstring)
    assert len(diags) == 1
    assert diags[0].code == "SARJ050"
    assert (diags[0].line, diags[0].col) == (2, 5)
    assert "only repeats its declaration" in diags[0].message


def test_one_novel_word_keeps_the_docstring():
    assert _fn("update_message(task_id: str)", "Update the task message, clobbering any draft.") == []


@pytest.mark.parametrize("provider", ["LLM", "STT", "TTS"])
def test_update_is_filler_for_setter_docstrings(provider: str):
    assert len(_fn(f"set_{provider.lower()}_provider(provider: str)", f"Update {provider} provider.")) == 1


def test_setter_docstring_with_lifecycle_detail_is_kept():
    assert _fn("set_llm_provider(provider: str)", "Update LLM provider after model creation.") == []


def test_negation_counts_as_content():
    # `not` is a stopword for the comment rules and deliberately NOT one here:
    # contradicting the obvious reading of a name is the most useful thing a
    # docstring can do.
    assert _fn("close_stream(stream: Stream)", "Close the stream. Does NOT close the socket.") == []


def test_class_name_counts_towards_the_signature():
    src = 'class TaskStore:\n    def create(self, task: Task):\n        """Create a task."""\n        return None\n'
    assert len(_check(src)) == 1


def test_annotation_tokens_count_towards_the_signature():
    assert len(_fn("build(spec: InstructionSpec) -> Instructions", "Build spec instructions.")) == 1


@pytest.mark.parametrize(
    "docstring",
    [
        "Get a task by ID.\\n\\n    Raises:\\n        KeyError: when absent.",
        "Get a task by ID. See https://example.com/tasks.",
        "Get a task by ID within 30 seconds.",
        "Get a task by ID. Should return 401 with an invalid token.",
        "Get a task by ID (RFC 7231).",
        "Get a task by ID.\\n\\n    >>> get_task('a')",
        "Get a task by ID.\\n\\n    .. note:: Get a task by ID.",
        "Get a task by ID — never on the write path.",
        "Get a task by ID, because the cache is authoritative.",
    ],
)
def test_docstrings_carrying_value_are_kept(docstring: str):
    body = docstring.replace("\\n", "\n")
    assert _check(f'def get_task(task_id: str):\n    """{body}"""\n    return None\n') == []


def test_function_tool_docstring_is_a_prompt():
    # The docstring is shipped to the model as the tool description; deleting it
    # changes what the agent does at runtime.
    src = 'from x import function_tool\n\n@function_tool\ndef get_balance(account_id: str):\n    """Get the balance for an account."""\n    return None\n'
    assert _check(src) == []


@pytest.mark.parametrize(
    "decorator",
    [
        pytest.param("@click.command()", id="click-help"),
        pytest.param("@typer.command()", id="typer-help"),
        pytest.param("@mcp.tool()", id="fastmcp-tool-prompt"),
        pytest.param("@agent.tool()", id="agent-tool-prompt"),
        pytest.param("@tool", id="langchain-tool-prompt"),
        pytest.param("@router.post('/tasks')", id="fastapi-openapi"),
        pytest.param("@blueprint.route('/tasks')", id="flask-route"),
    ],
)
def test_consumed_docstring_decorators_are_exempt(decorator: str):
    src = f'{decorator}\ndef create_tag(tag: str):\n    """Create a tag."""\n    return None\n'
    assert _check(src) == []


def test_stub_whose_body_is_the_docstring_is_exempt():
    # "Delete the whole docstring" would leave an empty suite.
    src = 'class Guard(Protocol):\n    def check(self, content: str) -> bool:\n        """Check the content."""\n'
    assert _check(src) == []


def test_generated_file_is_skipped():
    src = '# Code generated by openapi-generator. DO NOT EDIT.\ndef get_task(task_id: str):\n    """Get a task."""\n    return None\n'
    assert _check(src) == []


def test_function_without_a_docstring_is_ignored():
    assert _check("def get_task(task_id: str):\n    return None\n") == []


def test_module_and_class_docstrings_are_out_of_scope():
    src = '"""Task store."""\n\n\nclass TaskStore:\n    """Task store."""\n\n    x = 1\n'
    assert _check(src) == []


def test_google_args_block_is_owned_by_sarj086():
    src = (
        "def get_task(task_id: str):\n"
        '    """Get a task.\n\n'
        "    Args:\n"
        "        task_id: The task ID.\n"
        '    """\n'
        "    return None\n"
    )
    assert _check(src) == []


def test_override_copy_is_owned_by_sarj084():
    src = (
        "class BaseStore:\n"
        "    def get_task(self, task_id: str):\n"
        '        """Use the base store transaction policy."""\n'
        "        return None\n\n"
        "class Store(BaseStore):\n"
        "    @override\n"
        "    def get_task(self, task_id: str):\n"
        '        """Use the base store transaction policy."""\n'
        "        return None\n"
    )
    assert _check(src) == []


def test_unparseable_source_returns_nothing():
    assert _check("def (:\n") == []


def test_nested_function_is_checked():
    src = 'def outer():\n    def get_task(task_id: str):\n        """Get a task."""\n        return None\n    return get_task\n'
    assert len(_check(src)) == 1


def test_fastapi_route_docstring_is_the_openapi_description():
    # A first-party `@router.post("/desk/create-ticket")` handler — the text is what
    # an API consumer reads in the generated schema.
    src = (
        '@router.post("/desk/create-ticket")\n'
        "async def create_ticket(request: CreateTicketRequest):\n"
        '    """Create a ticket."""\n'
        "    return None\n"
    )
    assert _check(src) == []


# Numbers are not words.                                                      #


@pytest.mark.parametrize(
    "docstring",
    [
        pytest.param("Test that retry_limit=5 is valid.", id="boundary-value"),
        pytest.param("Create a version tag, capped at 200 characters.", id="cap"),
    ],
)
def test_a_literal_value_the_signature_does_not_carry_is_content(docstring: str):
    assert _fn("test_retry_limit_valid(retry_limit: int)", docstring) == []


def test_a_number_the_signature_already_carries_still_fires():
    diags = _fn("test_retry_limit_5_valid(retry_limit: int)", "Test retry limit 5 valid.")
    assert len(diags) == 1
    assert diags[0].code == "SARJ050"


def test_an_annotation_carrying_the_number_counts_as_the_signature():
    assert len(_fn("cap(value: Literal[5])", "Cap value 5.")) == 1


@pytest.mark.parametrize(
    ("signature", "docstring"),
    [
        ("get_user()", "Get the current user."),
        ("get_config()", "Get the default config."),
        ("list_formats()", "List supported formats."),
        ("get_fields()", "Get required fields."),
        ("list_users()", "List all users."),
    ],
)
def test_semantic_qualifier_keeps_docstring(signature: str, docstring: str) -> None:
    assert _fn(signature, docstring) == []


def test_main_is_not_filler():
    assert len(_check('def main():\n    """Main function."""\n    return None\n')) == 1


def test_nested_function_does_not_inherit_enclosing_class_name() -> None:
    source = '''
class User:
    def build(self):
        def get():
            """Get user."""
            return None

        return get
'''

    assert _check(source) == []


@pytest.mark.parametrize(
    "consumer",
    [
        "get_user.__doc__",
        "inspect.getdoc(get_user)",
        "pydoc.render_doc(get_user)",
        'getattr(get_user, "__doc__")',
        "help(get_user)",
        'get_user.__dict__["__doc__"]',
        'vars(get_user)["__doc__"]',
        "reader = get_user\nREGISTRY = reader.__doc__",
        "reader = get_user\nREGISTRY = reader.__doc__\nreader = other",
    ],
)
def test_recognized_runtime_docstring_read_is_exempt(consumer: str) -> None:
    source = f'''\
def get_user():
    """Get user."""
    return None

{consumer}
'''

    assert _check(source) == []


def test_arbitrary_decorator_is_conservatively_exempt() -> None:
    source = '''
@register
def get_user():
    """Get user."""
    return None
'''

    assert _check(source) == []


@pytest.mark.parametrize("class_header", ["Store(BaseStore)", "Store", "Store(TestCase)"])
def test_inherited_or_decorated_class_methods_are_exempt(class_header: str) -> None:
    decorator = "@registered\n" if class_header == "Store" else ""
    source = f'''\
{decorator}class {class_header}:
    def get_user(self):
        """Get user."""
        return None
'''

    assert _check(source) == []


@pytest.mark.parametrize(
    "docstring",
    ["Return fallback when primary.", "Return primary when fallback."],
)
def test_relational_word_keeps_potentially_meaningful_prose(docstring: str) -> None:
    assert _fn("return_value(primary: str, fallback: str)", docstring) == []


def test_selection_among_multiple_parameters_is_preserved() -> None:
    assert _fn("choose(primary: str, fallback: str)", "Choose fallback.") == []


@pytest.mark.parametrize(
    ("signature", "docstring"),
    [
        ("choose(primary_value: str, fallback_value: str)", "Choose fallback value."),
        ("copy(source_path: str, target_path: str)", "Copy target path."),
    ],
)
def test_shared_parameter_stem_does_not_fake_full_coverage(signature: str, docstring: str) -> None:
    assert _fn(signature, docstring) == []


def test_distinguishing_stem_from_each_parameter_allows_restatement() -> None:
    diagnostics = _fn(
        "copy(source_path: str, target_path: str)",
        "Copy source path target path.",
    )

    assert len(diagnostics) == 1


def test_enclosing_class_words_do_not_make_method_prose_redundant() -> None:
    source = '''
class PrimaryFallback:
    def choose(self):
        """Choose fallback."""
        return None
'''

    assert _check(source) == []


@pytest.mark.parametrize("term", ["سريع", "سياسة", "例外"])
def test_non_latin_semantic_term_is_preserved(term: str) -> None:
    assert _fn("retry_policy()", f"Retry policy {term}.") == []


def test_inline_suppression_is_honored() -> None:
    source = 'def get_user():\n    """Get user."""  # sarj-noqa: SARJ050\n    return None\n'

    assert _check(source) == []
