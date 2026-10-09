from pathlib import Path

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.no_interpreter_source_arguments import NoInterpreterSourceArguments


_CASES = (
    ("subprocess-python", "import subprocess\nsubprocess.run(['python3', '-c', 'print(1)'])\n", True),
    ("subprocess-module-alias", "import subprocess as process\nprocess.Popen(('node', '--eval', '1'))\n", True),
    (
        "subprocess-symbol-alias",
        "from subprocess import check_output as capture\ncapture(args=['jq', '.items', 'data.json'])\n",
        True,
    ),
    ("python-flag-arity", "import subprocess\nsubprocess.call(['python3', '-W', 'once', '-Xdev', '-c', '1'])\n", True),
    ("awk-program", "import subprocess\nsubprocess.check_call(['awk', '{print $1}', 'data.txt'])\n", True),
    ("wrapped-python", "import subprocess\nsubprocess.run(['env', 'MODE=strict', 'python3', '-c', '1'])\n", True),
    ("module-boundary", "import subprocess\nsubprocess.run(['python3', '-m', 'tools.check', '-c', 'strict'])\n", False),
    ("file-boundary", "import subprocess\nsubprocess.run(['python3', 'scripts/check.py', '-c', 'strict'])\n", False),
    ("warning-operand", "import subprocess\nsubprocess.run(['python3', '-W', '-c', 'scripts/check.py'])\n", False),
    ("jq-file", "import subprocess\nsubprocess.run(['jq', '--arg', 'mode', 'strict', '-f', 'filter.jq'])\n", False),
    ("awk-file", "import subprocess\nsubprocess.run(['awk', '-v', 'mode=strict', '-f', 'filter.awk'])\n", False),
    (
        "shadowed-module",
        "import subprocess\ndef check(subprocess):\n    subprocess.run(['python3', '-c', '1'])\n",
        False,
    ),
    ("shadowed-symbol", "from subprocess import run\nrun = other\nrun(['python3', '-c', '1'])\n", False),
    ("replaced-method", "import subprocess\nsubprocess.run = other\nsubprocess.run(['python3', '-c', '1'])\n", False),
    ("unknown-receiver", "def check(connection):\n    connection.run(['python3', '-c', '1'])\n", False),
    ("shell-true-vector", "import subprocess\nsubprocess.run(['python3', '-c', '1'], shell=True)\n", False),
    ("shell-string", "import subprocess\nsubprocess.run('python3 -c 1', shell=True)\n", False),
    ("expanded-options", "import subprocess\nsubprocess.run(['python3', '-c', '1'], **options)\n", False),
    (
        "executable-override-data",
        "import subprocess\nsubprocess.run(['python3', '-c', '1'], executable='/bin/echo')\n",
        False,
    ),
    (
        "executable-override-python",
        "import subprocess\nsubprocess.run(['worker', '-c', '1'], executable='/usr/bin/python3')\n",
        True,
    ),
    ("dynamic-executable", "import subprocess\nsubprocess.run(['python3', '-c', '1'], executable=program)\n", False),
    ("dynamic-argv", "import subprocess\nsubprocess.run(command)\n", False),
    ("asyncio-argv", "import asyncio\nasyncio.create_subprocess_exec('python3', '-c', '1')\n", True),
    ("asyncio-alias", "from asyncio import create_subprocess_exec as launch\nlaunch('node', '-e', '1')\n", True),
    ("asyncio-module", "import asyncio\nasyncio.create_subprocess_exec('python3', '-m', 'tools.check')\n", False),
    ("os-execv", "import os\nos.execv('/usr/bin/python3', ['worker', '-c', '1'])\n", True),
    (
        "os-execvpe-env",
        "from os import execvpe as launch\nlaunch('python3', ['worker', '-c', '1'], environment)\n",
        True,
    ),
    ("os-execle-env", "import os\nos.execle('/usr/bin/python3', 'worker', '-c', '1', environment)\n", True),
    ("os-execlp-module", "import os\nos.execlp('python3', 'worker', '-m', 'tools.check', '-c', 'strict')\n", False),
    ("os-spawnv-mode", "import os\nos.spawnv(os.P_WAIT, '/usr/bin/python3', ['worker', '-c', '1'])\n", True),
    ("os-spawnlpe-mode-env", "import os\nos.spawnlpe(os.P_WAIT, 'python3', 'worker', '-c', '1', environment)\n", True),
    ("os-spawnv-external", "import os\nos.spawnv(os.P_WAIT, '/bin/echo', ['python3', '-c', '1'])\n", False),
    ("os-posix-spawn", "import os\nos.posix_spawn('/usr/bin/python3', ['worker', '-c', '1'], environment)\n", True),
    ("os-system-string-gap", "import os\nos.system('python3 -c 1')\n", False),
    ("unknown-options-gap", "import subprocess\nsubprocess.run(['python3', '--unknown', '-c', '1'])\n", False),
    ("recursive-shell-gap", "import subprocess\nsubprocess.run(['sh', '-c', 'python3 -c 1'])\n", False),
    ("malformed-input", "def check(:\n", False),
)


@pytest.mark.parametrize(("case_id", "source", "expected"), _CASES, ids=[case[0] for case in _CASES])
def test_labeled_interpreter_source_arguments(case_id: str, source: str, expected: bool) -> None:
    case = EvaluationCase(
        case_id, Language.PYTHON, source, ExpectedOutcome.MATCH if expected else ExpectedOutcome.NO_MATCH
    )
    findings = NoInterpreterSourceArguments().check(Path("tools/check.py"), case.source)
    assert bool(findings) is (case.expected is ExpectedOutcome.MATCH), case.case_id
    assert len(findings) <= 1


def test_documented_examples() -> None:
    verify_native_rule(NoInterpreterSourceArguments, analyze)


def test_exact_suppression_and_error_level() -> None:
    source = "import subprocess\nsubprocess.run(['python3', '-c', '1'])\n"
    [finding] = NoInterpreterSourceArguments().check(Path("tools/check.py"), source)
    assert (finding.line, finding.col, finding.severity) == (2, 1, Severity.ERROR)
    assert not NoInterpreterSourceArguments().check(
        Path("tools/check.py"), f"{source.rstrip()}  # sarj-noqa: SARJ484 — validate literal argv classifier boundary\n"
    )


def test_generated_sources_abstain() -> None:
    assert not NoInterpreterSourceArguments().check(Path("generated/check.py"), _CASES[0][1])


_STDIN_CASES = (
    ("default-stdin-str", "import subprocess\nsubprocess.run(['python3'], input='print(21)', text=True)\n", True),
    ("explicit-stdin-str", "import subprocess\nsubprocess.run(['python3', '-'], input='print(21)', text=True)\n", True),
    ("keyword-args", "import subprocess\nsubprocess.run(args=('python3', '-'), input='print(21)', text=True)\n", True),
    ("module-alias", "import subprocess as process\nprocess.run(['python3'], input='print(21)', text=True)\n", True),
    ("symbol-alias", "from subprocess import run as launch\nlaunch(['python3'], input='print(21)', text=True)\n", True),
    (
        "check-output",
        "from subprocess import check_output\ncheck_output(['python3'], input='print(21)', text=True)\n",
        True,
    ),
    ("bytes-stdin", "import subprocess\nsubprocess.run(['python3'], input=b'print(21)')\n", True),
    (
        "nested-call",
        "import subprocess\ndef verify():\n    return subprocess.run(['python3'], input='print(21)', text=True)\n",
        True,
    ),
    (
        "python-flags",
        "import subprocess\nsubprocess.run(['python3', '-I', '-W', 'once', '-Xdev'], input='print(21)', text=True)\n",
        True,
    ),
    (
        "python-versioned",
        "import subprocess\nsubprocess.run(['/opt/python3.14', '-'], input='print(21)', text=True)\n",
        True,
    ),
    (
        "env-wrapper",
        "import subprocess\nsubprocess.run(['env', 'MODE=strict', 'python3'], input='print(21)', text=True)\n",
        True,
    ),
    (
        "executable-override",
        "import subprocess\nsubprocess.run(['worker', '-'], executable='/opt/python3', input='print(21)', text=True)\n",
        True,
    ),
    (
        "module-data",
        "import subprocess\nsubprocess.run(['python3', '-m', 'tools.check'], input='print(21)', text=True)\n",
        False,
    ),
    (
        "file-data",
        "import subprocess\nsubprocess.run(['python3', 'tools/check.py'], input='print(21)', text=True)\n",
        False,
    ),
    (
        "option-operand",
        "import subprocess\nsubprocess.run(['python3', '-W', '-c', 'tools/check.py'], input='print(21)', text=True)\n",
        False,
    ),
    (
        "version-exit",
        "import subprocess\nsubprocess.run(['python3', '--version'], input='print(21)', text=True)\n",
        False,
    ),
    ("help-exit", "import subprocess\nsubprocess.run(['python3', '-h'], input='print(21)', text=True)\n", False),
    (
        "unknown-flags",
        "import subprocess\nsubprocess.run(['python3', '--unknown'], input='print(21)', text=True)\n",
        False,
    ),
    ("empty-string", "import subprocess\nsubprocess.run(['python3'], input='', text=True)\n", False),
    ("whitespace-input", "import subprocess\nsubprocess.run(['python3'], input=' \\n\\t\\n', text=True)\n", False),
    (
        "comment-input",
        "import subprocess\nsubprocess.run(['python3'], input='# prepared verifier\\n# no program\\n', text=True)\n",
        False,
    ),
    ("empty-bytes", "import subprocess\nsubprocess.run(['python3'], input=b'')\n", False),
    ("none-input", "import subprocess\nsubprocess.run(['python3'], input=None)\n", False),
    ("dynamic-input", "import subprocess\nsubprocess.run(['python3'], input=program, text=True)\n", False),
    (
        "file-backed-input",
        "import subprocess\nsubprocess.run(['python3'], input=Path('tools/check.py').read_text(), text=True)\n",
        False,
    ),
    (
        "bound-argv",
        "import subprocess\ncommand = ['python3']\nsubprocess.run(command, input='print(21)', text=True)\n",
        False,
    ),
    ("dynamic-argv", "import subprocess\nsubprocess.run(command, input='print(21)', text=True)\n", False),
    (
        "shadowed-module",
        "import subprocess\ndef verify(subprocess):\n    subprocess.run(['python3'], input='print(21)', text=True)\n",
        False,
    ),
    (
        "reassigned-import",
        "from subprocess import run\nrun = launch\nrun(['python3'], input='print(21)', text=True)\n",
        False,
    ),
    (
        "replaced-method",
        "import subprocess\nsubprocess.run = launch\nsubprocess.run(['python3'], input='print(21)', text=True)\n",
        False,
    ),
    ("unknown-method", "connection.run(['python3'], input='print(21)', text=True)\n", False),
    ("shell-true", "import subprocess\nsubprocess.run(['python3'], input='print(21)', text=True, shell=True)\n", False),
    ("shell-string", "import subprocess\nsubprocess.run('python3', input='print(21)', text=True)\n", False),
    (
        "expanded-options",
        "import subprocess\nsubprocess.run(['python3'], input='print(21)', text=True, **options)\n",
        False,
    ),
    ("non-interpreter", "import subprocess\nsubprocess.run(['cat'], input='print(21)', text=True)\n", False),
    (
        "overridden-to-data",
        "import subprocess\nsubprocess.run(['python3'], executable='/bin/cat', input='print(21)', text=True)\n",
        False,
    ),
    (
        "popen-unsupported-input",
        "import subprocess\nsubprocess.Popen(['python3'], input='print(21)', text=True)\n",
        False,
    ),
    (
        "call-unsupported-input",
        "import subprocess\nsubprocess.call(['python3'], input='print(21)', text=True)\n",
        False,
    ),
    (
        "asyncio-unsupported-input",
        "import asyncio\nasyncio.create_subprocess_exec('python3', input='print(21)', text=True)\n",
        False,
    ),
    (
        "receiver-communicate",
        "import subprocess\np = subprocess.Popen(['python3'], stdin=subprocess.PIPE)\np.communicate(b'print(21)')\n",
        False,
    ),
    ("malformed-outer", "def verify(:\n", False),
    ("str-without-text", "import subprocess\nsubprocess.run(['python3'], input='print(21)')\n", False),
    ("str-with-false-text", "import subprocess\nsubprocess.run(['python3'], input='print(21)', text=False)\n", False),
    ("bytes-with-text", "import subprocess\nsubprocess.run(['python3'], input=b'print(21)', text=True)\n", False),
    (
        "stdin-conflict",
        "import subprocess\nsubprocess.run(['python3'], input=b'print(21)', stdin=subprocess.PIPE)\n",
        False,
    ),
    (
        "mode-conflict",
        "import subprocess\nsubprocess.run(['python3'], input='print(21)', text=True, universal_newlines=False)\n",
        False,
    ),
    ("literal-encoding", "import subprocess\nsubprocess.run(['python3'], input='print(21)', encoding='utf-8')\n", True),
    ("literal-errors", "import subprocess\nsubprocess.run(['python3'], input='print(21)', errors='strict')\n", True),
    (
        "universal-newlines",
        "import subprocess\nsubprocess.run(['python3'], input='print(21)', universal_newlines=True)\n",
        True,
    ),
    ("stdin-none", "import subprocess\nsubprocess.run(['python3'], input=b'print(21)', stdin=None)\n", True),
    ("dynamic-text-mode", "import subprocess\nsubprocess.run(['python3'], input='print(21)', text=text_mode)\n", False),
    (
        "dynamic-encoding",
        "import subprocess\nsubprocess.run(['python3'], input='print(21)', encoding=encoding)\n",
        False,
    ),
    ("existing-inline", "import subprocess\nsubprocess.run(['python3', '-c', 'print(21)'])\n", True),
    (
        "invalid-encoding",
        "import subprocess\nsubprocess.run(['python3'], input='print(21)', encoding='missing-codec')\n",
        False,
    ),
    (
        "nontext-encoding",
        "import subprocess\nsubprocess.run(['python3'], input='print(21)', encoding='base64')\n",
        False,
    ),
    (
        "unencodable-input",
        "import subprocess\nsubprocess.run(['python3'], input='print(\"🌍\")', encoding='ascii')\n",
        False,
    ),
)


@pytest.mark.parametrize(("case_id", "source", "expected"), _STDIN_CASES, ids=[case[0] for case in _STDIN_CASES])
def test_literal_interpreter_stdin_source(case_id: str, source: str, *, expected: bool) -> None:
    case = EvaluationCase(
        case_id, Language.PYTHON, source, ExpectedOutcome.MATCH if expected else ExpectedOutcome.NO_MATCH
    )
    findings = NoInterpreterSourceArguments().check(Path("tools/check.py"), case.source)
    assert bool(findings) is (case.expected is ExpectedOutcome.MATCH), case.case_id
    assert len(findings) <= 1
