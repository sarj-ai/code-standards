from pathlib import Path
import textwrap

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.inline_single_use_local import InlineSingleUseLocal


def _check(source: str, path: str = "service.py"):
    return InlineSingleUseLocal().check(Path(path), textwrap.dedent(source))


def test_documented_examples() -> None:
    verify_native_rule(InlineSingleUseLocal, analyze)


def test_flags_single_use_call_argument() -> None:
    diagnostics = _check(
        """
        async def store(objects, path, audio):
            payload = encode(audio)
            await objects.upload(path=path, data=payload)
        """
    )

    assert len(diagnostics) == 1
    assert diagnostics[0].code == "SARJ592"
    assert diagnostics[0].severity is Severity.WARNING
    assert diagnostics[0].line == 3
    assert "inline `encode(audio)`" in diagnostics[0].message


def test_suggests_walrus_for_pr_constructor_identifier() -> None:
    diagnostics = _check(
        """
        async def prepare(request, audio):
            file_id = FileId(str(uuid7()))
            file = CreateFile(
                id=file_id,
                storage_path=f"tts-cache/{request.id}/{file_id}.wav",
                content_type="audio/wav",
                byte_size=len(audio),
            )
            uploads.append(file)
            return file
        """
    )

    assert len(diagnostics) == 1
    assert "`(file_id := FileId(str(uuid7())))`" in diagnostics[0].message


def test_reused_audio_value_is_not_reported() -> None:
    assert not _check(
        """
        async def prepare(synthesizer, objects, request):
            audio = await synthesizer.synthesize(request.utterance)
            file = CreateFile(byte_size=len(audio))
            await objects.upload(data=audio)
            return file
        """
    )


@pytest.mark.parametrize(
    "consumer",
    [
        "if is_ready(state):\n        start()",
        "for item in state:\n        handle(item)",
        "with state:\n        handle()",
        "match state:\n        case _:\n            handle()",
        "result = transform(state)\n    log(result)\n    publish(result)",
        "yield state",
    ],
)
def test_flags_supported_headers(consumer: str) -> None:
    source = f"def run(source):\n    state = load(source)\n    {consumer}\n"
    assert len(InlineSingleUseLocal().check(Path("service.py"), source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        # Annotated, augmented and unpacking assignments are excluded.
        "def run(source):\n    state: int = load(source)\n    publish(state)\n",
        "def run(source):\n    state, other = load(source)\n    publish(state)\n",
        # Module scope is not a function local.
        "state = load()\npublish(state)\n",
        # Literal constants and aliases keep their names.
        "def run():\n    timeout = 30\n    wait(timeout)\n",
        "def run():\n    timeout = -1\n    wait(timeout)\n",
        "def run(source):\n    state = source\n    publish(state)\n",
        # Multi-line values are not inlined.
        "def run(source):\n    state = load(\n        source,\n    )\n    publish(state)\n",
        # Ruff RET504 owns direct returns.
        "def run(source):\n    state = load(source)\n    return state\n",
        # Assertions disappear under -O.
        "def run(source):\n    state = load(source)\n    assert check(state)\n",
        # Ruff EM101/EM102 require the message variable.
        "def run(source):\n    message = f'bad {source}'\n    raise ValueError(message)\n",
        # Reads after the next statement.
        "def run(source):\n    state = load(source)\n    publish(state)\n    log(state)\n",
        # Reads in compound-statement bodies.
        "def run(source, flag):\n    state = load(source)\n    if flag:\n        publish(state)\n",
        # While tests are re-evaluated.
        "def run(source):\n    state = load(source)\n    while poll(state):\n        pass\n",
        # Lambdas, comprehensions and nested functions change evaluation.
        "def run(source):\n    state = load(source)\n    register(lambda: state)\n",
        "def run(source, items):\n    state = load(source)\n    publish([state for _ in items])\n",
        "def run(source):\n    state = load(source)\n    def inner():\n        return state\n    publish(inner)\n",
        # Conditional operands.
        "def run(source, flag):\n    state = load(source)\n    publish(flag and state)\n",
        "def run(source, flag):\n    state = load(source)\n    publish(state if flag else None)\n",
        # Side effects before the read would be reordered.
        "def run(source):\n    state = load(source)\n    publish(prepare(), state)\n",
        "async def run(source):\n    state = load(source)\n    publish(await prepare(), state)\n",
        "def run(source, counter):\n    state = counter.increment()\n    publish(counter.value, state)\n",
        "def run(source, items):\n    state = items.pop()\n    publish(items[0], state)\n",
        # Name bound more than once or declared global/nonlocal.
        "def run(source):\n    state = load(source)\n    publish(state)\n    state = load(source)\n",
        "def run(source):\n    global state\n    state = load(source)\n    publish(state)\n",
        # Parameters are not new locals.
        "def run(state):\n    state = load(state)\n    publish(state)\n",
        # Comments between statements document the name.
        "def run(source):\n    state = load(source)  # snapshot before publish\n    publish(state)\n",
        "def run(source):\n    state = load(source)\n    # snapshot before publish\n    publish(state)\n",
        # Suppressions are respected.
        "def run(source):\n    state = load(source)  # sarj-noqa: SARJ592 -- tracing boundary for debugging\n    publish(state)\n",
        # Explanatory variables keep their names.
        "def run(count):\n    last = count - 1\n    scroll(last)\n",
        "def run(item):\n    shown = item.source is not None\n    publish(shown)\n",
        "def run(item, flag):\n    label = item.name if flag else ''\n    publish(label)\n",
        "def run(items):\n    names = [item.name for item in items]\n    publish(names)\n",
        "def run(items):\n    first = next((item for item in items if item.ok), None)\n    publish(first)\n",
        "def run(metrics):\n    meta = as_object(metrics.get('m'))\n    if isinstance(name := meta.get('name'), str):\n        publish(name)\n",
        # A blank line is an intentional paragraph boundary.
        "def run(source):\n    state = load(source)\n\n    publish(state)\n",
        # Awaited values used as attribute targets would need parentheses.
        "async def run(source):\n    state = await load(source)\n    publish(state.value)\n",
        # Calls with arguments are not nested into f-strings.
        "def run(source):\n    state = load(source)\n    publish(f'state={state}')\n",
        # The inlined line must fit 120 columns.
        "def run(source):\n    state = load_the_complete_state_snapshot(source, include_history=True, include_metadata=True)\n    publish_everything_now(destination='primary', state=state)\n",
        # Long values and augmented accumulation keep their names.
        "def run(source):\n    state = load(source, alpha=True, beta=True, gamma=True, delta=True, epsilon=True, zeta=True)\n    publish(state)\n",
        "async def run(store, tasks, total):\n    created = await store.create_many(tasks)\n    total += len(created)\n",
        # Delete consumers.
        "def run(source, mapping):\n    key = load(source)\n    del mapping[key]\n",
    ],
)
def test_excluded_shapes(source: str) -> None:
    assert not InlineSingleUseLocal().check(Path("service.py"), source)


def test_raise_of_built_exception_is_reported() -> None:
    assert len(_check("def run(source):\n    error = build_error(source)\n    raise error\n")) == 1


def test_callee_attributes_before_read_are_safe() -> None:
    assert (
        len(_check("async def run(self, source):\n    state = load(source)\n    await self._files.upsert(state)\n"))
        == 1
    )


def test_walrus_requires_direct_argument_of_top_call() -> None:
    assert not _check(
        """
        def run(source):
            state = load(source)
            publish(wrap(state), state)
        """
    )


def test_walrus_limits_read_count() -> None:
    assert not _check(
        """
        def run(source):
            state = load(source)
            publish(state, state, state, state)
        """
    )


def test_walrus_rejects_reads_outside_top_call() -> None:
    assert not _check(
        """
        def run(source):
            state = load(source)
            items[state] = publish(state, state)
        """
    )


def test_skips_stub_and_generated_files() -> None:
    source = "def run(source):\n    state = load(source)\n    publish(state)\n"
    assert not InlineSingleUseLocal().check(Path("service.pyi"), source)
    assert not InlineSingleUseLocal().check(Path("service.py"), "# @generated\n" + source)


def test_test_modules_keep_arrange_and_act_steps() -> None:
    source = "def test_run(source):\n    state = load(source)\n    publish(state)\n"
    assert not InlineSingleUseLocal().check(Path("tests/test_service.py"), source)


def test_attribute_values_may_enter_f_strings() -> None:
    assert len(_check("def run(item):\n    name = item.name\n    publish(f'name={name}')\n")) == 1
