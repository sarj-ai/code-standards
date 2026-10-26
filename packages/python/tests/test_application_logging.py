from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language

from sarj_python_lint import application_logging_uses


_CASES = (
    (
        EvaluationCase(
            case_id="root-application-event",
            language=Language.PYTHON,
            source=('import logging\nlogging.warning("failed")\n'),
            expected=ExpectedOutcome.MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        1,
    ),
    (
        EvaluationCase(
            case_id="module-alias-event",
            language=Language.PYTHON,
            source=('import logging as events\nevents.error("failed")\n'),
            expected=ExpectedOutcome.MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        1,
    ),
    (
        EvaluationCase(
            case_id="from-import-event",
            language=Language.PYTHON,
            source=('from logging import warning as warn\nwarn("failed")\n'),
            expected=ExpectedOutcome.MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        1,
    ),
    (
        EvaluationCase(
            case_id="immediate-factory-even-sdk-name",
            language=Language.PYTHON,
            source=('import logging\nlogging.getLogger("livekit.agents").warning("application message")\n'),
            expected=ExpectedOutcome.MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        1,
    ),
    (
        EvaluationCase(
            case_id="stable-local-factory-binding",
            language=Language.PYTHON,
            source=(
                "import logging\n"
                "def run():\n"
                "    events = logging.getLogger(__name__)\n"
                '    events.info("application message")\n'
            ),
            expected=ExpectedOutcome.MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        1,
    ),
    (
        EvaluationCase(
            case_id="stable-module-factory-binding",
            language=Language.PYTHON,
            source=(
                "import logging\n"
                "events = logging.getLogger(__name__)\n"
                "def run():\n"
                '    events.info("application message")\n'
            ),
            expected=ExpectedOutcome.MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        1,
    ),
    (
        EvaluationCase(
            case_id="direct-Logger-instance",
            language=Language.PYTHON,
            source=('from logging import Logger\nevents = Logger("app")\nevents.info("application message")\n'),
            expected=ExpectedOutcome.MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        1,
    ),
    (
        EvaluationCase(
            case_id="public-emitter-in-mixed-adapter-module",
            language=Language.PYTHON,
            source=(
                "import logging\n"
                "from loguru import logger\n"
                "class Bridge(logging.Handler):\n"
                "    def emit(self, record):\n"
                "        logger.info(record.getMessage())\n"
                'logging.warning("unrelated application event")\n'
            ),
            expected=ExpectedOutcome.MATCH,
            path=PurePosixPath("app/bridge.py"),
        ),
        1,
    ),
    (
        EvaluationCase(
            case_id="standalone-default-basicConfig",
            language=Language.PYTHON,
            source=("import logging\nlogging.basicConfig()\n"),
            expected=ExpectedOutcome.MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        1,
    ),
    (
        EvaluationCase(
            case_id="standalone-file-basicConfig",
            language=Language.PYTHON,
            source=('import logging\nlogging.basicConfig(filename="application.log")\n'),
            expected=ExpectedOutcome.MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        1,
    ),
    (
        EvaluationCase(
            case_id="direct-stdlib-StreamHandler",
            language=Language.PYTHON,
            source=("import logging\nhandler = logging.StreamHandler()\n"),
            expected=ExpectedOutcome.MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        1,
    ),
    (
        EvaluationCase(
            case_id="explicit-handler-still-built-in-sink",
            language=Language.PYTHON,
            source=("import logging\nlogging.basicConfig(handlers=[logging.StreamHandler()])\n"),
            expected=ExpectedOutcome.MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        1,
    ),
    (
        EvaluationCase(
            case_id="types-levels-adapter",
            language=Language.PYTHON,
            source=(
                "import logging\n"
                "from loguru import logger\n"
                "class Bridge(logging.Handler):\n"
                "    def emit(self, record: logging.LogRecord):\n"
                "        logger.opt(exception=record.exc_info).log(record.levelname, record.getMessage())\n"
            ),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/bridge.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="root-routing-only",
            language=Language.PYTHON,
            source=(
                "import logging as stdlib\n"
                "root=stdlib.getLogger()\n"
                "root.handlers=[x for x in root.handlers if isinstance(x, Bridge)]\n"
            ),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/bridge.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="explicit-custom-handler-configuration",
            language=Language.PYTHON,
            source=("import logging\nlogging.basicConfig(handlers=[Bridge()],level=logging.INFO,force=True)\n"),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/bridge.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="SDK-accepts-real-Logger",
            language=Language.PYTHON,
            source=(
                "import logging\n"
                "from vendor import log_exceptions\n"
                "@log_exceptions(logger=logging.getLogger(__name__))\n"
                "def callback():\n"
                '    raise RuntimeError("failed")\n'
            ),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/interop.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="stdlib-conformance-event-test",
            language=Language.PYTHON,
            source=(
                "import logging\n"
                "def test_bridge(caplog):\n"
                '    logging.getLogger("sdk").warning("test stimulus")\n'
                "    assert caplog.records\n"
            ),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("tests/test_bridge.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="same-event-in-production",
            language=Language.PYTHON,
            source=('import logging\ndef perform():\n    logging.getLogger("sdk").warning("test stimulus")\n'),
            expected=ExpectedOutcome.MATCH,
            path=PurePosixPath("app/bridge.py"),
        ),
        1,
    ),
    (
        EvaluationCase(
            case_id="test-calls-production-function",
            language=Language.PYTHON,
            source=('import logging\ndef perform():\n    logging.warning("event")\n'),
            expected=ExpectedOutcome.MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        1,
    ),
    (
        EvaluationCase(
            case_id="unknown-receiver-not-stdlib",
            language=Language.PYTHON,
            source=('from vendor import logger\nlogger.info("event")\n'),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="shadowed-module-name",
            language=Language.PYTHON,
            source=('import logging\ndef perform(logging):\n    logging.warning("event")\n'),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="nonemitting-import-alone",
            language=Language.PYTHON,
            source=("import logging\n"),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="rebound-logger-identity",
            language=Language.PYTHON,
            source=(
                "import logging\n"
                "from vendor import other\n"
                "events = logging.getLogger(__name__)\n"
                "events = other\n"
                'events.info("event")\n'
            ),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="shadowed-factory-binding",
            language=Language.PYTHON,
            source=(
                'import logging\nevents = logging.getLogger(__name__)\ndef run(events):\n    events.info("event")\n'
            ),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="escaped-logger-argument",
            language=Language.PYTHON,
            source=(
                "import logging\n"
                "from vendor import configure\n"
                "events = logging.getLogger(__name__)\n"
                "configure(events)\n"
                'events.warning("event")\n'
            ),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="escaped-logger-return",
            language=Language.PYTHON,
            source=(
                "import logging\n"
                "def build():\n"
                "    events = logging.getLogger(__name__)\n"
                '    events.warning("event")\n'
                "    return events\n"
            ),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="conditional-factory-binding",
            language=Language.PYTHON,
            source=('import logging\nif enabled:\n    events = logging.getLogger(__name__)\nevents.info("event")\n'),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="match-rebind-logger",
            language=Language.PYTHON,
            source=(
                "import logging\n"
                "events = logging.getLogger(__name__)\n"
                "match replacement:\n"
                "    case events:\n"
                '        events.info("event")\n'
            ),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="deleted-logger-binding",
            language=Language.PYTHON,
            source=('import logging\nevents = logging.getLogger(__name__)\ndel events\nevents.info("event")\n'),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="patched-module-emitter",
            language=Language.PYTHON,
            source=('import logging\nfrom vendor import send\nlogging.warning = send\nlogging.warning("event")\n'),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="patched-bound-emitter",
            language=Language.PYTHON,
            source=(
                "import logging\n"
                "from vendor import send\n"
                "events = logging.getLogger(__name__)\n"
                "events.warning = send\n"
                'events.warning("event")\n'
            ),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="escaped-module-namespace",
            language=Language.PYTHON,
            source=('import logging\nfrom vendor import configure\nconfigure(logging)\nlogging.warning("event")\n'),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="escaped-module-dictionary-namespace",
            language=Language.PYTHON,
            source=(
                'import logging\nfrom vendor import configure\nconfigure(logging.__dict__)\nlogging.warning("event")\n'
            ),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="patched-module-dictionary-emitter",
            language=Language.PYTHON,
            source=(
                "import logging\n"
                "from vendor import send\n"
                'logging.__dict__["warning"] = send\n'
                'logging.warning("event")\n'
            ),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="escaped-renamed-module-dictionary-namespace",
            language=Language.PYTHON,
            source=(
                "import logging as events\n"
                "from vendor import configure\n"
                "configure(events.__dict__)\n"
                'events.error("event")\n'
            ),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="ordinary-module-level-constant-keeps-emitter-provenance",
            language=Language.PYTHON,
            source=('import logging\nlevel = logging.WARNING\nlogging.log(level, "event")\n'),
            expected=ExpectedOutcome.MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        1,
    ),
    (
        EvaluationCase(
            case_id="ordinary-module-routing-keeps-nearby-emitter-provenance",
            language=Language.PYTHON,
            source=('import logging\nlogging.getLogger().setLevel(logging.WARNING)\nlogging.warning("event")\n'),
            expected=ExpectedOutcome.MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        1,
    ),
    (
        EvaluationCase(
            case_id="unknown-wildcard-rebinding",
            language=Language.PYTHON,
            source=('import logging\nfrom vendor import *\nlogging.warning("event")\n'),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="explicit-import-after-wildcard",
            language=Language.PYTHON,
            source=('from vendor import *\nimport logging\nlogging.warning("event")\n'),
            expected=ExpectedOutcome.MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        1,
    ),
    (
        EvaluationCase(
            case_id="builtin-sink-alias",
            language=Language.PYTHON,
            source=('from logging import FileHandler as Sink\nSink("app.log")\n'),
            expected=ExpectedOutcome.MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        1,
    ),
    (
        EvaluationCase(
            case_id="immediate-constructor-event",
            language=Language.PYTHON,
            source=('import logging\nlogging.Logger("app").error("event")\n'),
            expected=ExpectedOutcome.MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        1,
    ),
    (
        EvaluationCase(
            case_id="no-sink-null-handler",
            language=Language.PYTHON,
            source=("import logging\nlogging.NullHandler()\n"),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="opaque-basicConfig-options",
            language=Language.PYTHON,
            source=("import logging\nlogging.basicConfig(**options)\n"),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="type-name-not-provenance",
            language=Language.PYTHON,
            source=('from vendor import Logger\nevents = Logger("app")\nevents.warning("event")\n'),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="strings-not-events",
            language=Language.PYTHON,
            source=("import logging\nsource = \"logging.warning('event')\"\n"),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="patched-factory-result-emitter",
            language=Language.PYTHON,
            source=(
                "import logging\n"
                "from vendor import send\n"
                'logging.getLogger("app").warning = send\n'
                'logging.getLogger("app").warning("event")\n'
            ),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="setattr-factory-result-emitter",
            language=Language.PYTHON,
            source=(
                "import logging\n"
                "from vendor import send\n"
                'setattr(logging.getLogger("app"), "warning", send)\n'
                'logging.getLogger("app").warning("event")\n'
            ),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="escaped-bound-logger-namespace",
            language=Language.PYTHON,
            source=(
                "import logging\n"
                "from vendor import configure\n"
                'events = logging.getLogger("app")\n'
                "configure(events.__dict__)\n"
                'events.warning("event")\n'
            ),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="routing-members-do-not-waive-nearby-event",
            language=Language.PYTHON,
            source=(
                "import logging\n"
                'events = logging.getLogger("app")\n'
                "events.setLevel(logging.INFO)\n"
                "events.handlers = [Bridge()]\n"
                'events.warning("event")\n'
            ),
            expected=ExpectedOutcome.MATCH,
            path=PurePosixPath("app/bridge.py"),
        ),
        1,
    ),
    (
        EvaluationCase(
            case_id="patched-root-singleton-emitter",
            language=Language.PYTHON,
            source=(
                'import logging\nfrom vendor import send\nlogging.root.warning = send\nlogging.root.warning("event")\n'
            ),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="setattr-root-singleton-emitter",
            language=Language.PYTHON,
            source=(
                "import logging\n"
                "from vendor import send\n"
                'setattr(logging.root, "warning", send)\n'
                'logging.root.warning("event")\n'
            ),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="escaped-imported-root-SDK-argument",
            language=Language.PYTHON,
            source=('from logging import root\nfrom vendor import sdk\nsdk(root)\nroot.warning("event")\n'),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="escaped-renamed-imported-root-SDK-argument",
            language=Language.PYTHON,
            source=(
                'from logging import root as events\nfrom vendor import sdk\nsdk(events)\nevents.warning("event")\n'
            ),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="escaped-imported-root-assignment-alias",
            language=Language.PYTHON,
            source=('from logging import root\nother = root\nroot.warning("event")\n'),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="escaped-imported-root-return",
            language=Language.PYTHON,
            source=('from logging import root\ndef expose():\n    return root\nroot.warning("event")\n'),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="escaped-imported-root-namespace",
            language=Language.PYTHON,
            source=('from logging import root\nfrom vendor import sdk\nsdk(root.__dict__)\nroot.warning("event")\n'),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="proven-imported-root-emission",
            language=Language.PYTHON,
            source=('from logging import root\nroot.warning("event")\n'),
            expected=ExpectedOutcome.MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        1,
    ),
    (
        EvaluationCase(
            case_id="proven-factory-alias-emission",
            language=Language.PYTHON,
            source=('from logging import getLogger as factory\nfactory("app").warning("event")\n'),
            expected=ExpectedOutcome.MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        1,
    ),
    (
        EvaluationCase(
            case_id="related-root-namespace-escaped",
            language=Language.PYTHON,
            source=(
                "import logging\n"
                "from vendor import configure\n"
                "configure(logging.root.__dict__)\n"
                'logging.root.warning("event")\n'
            ),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="related-root-namespace-replaced",
            language=Language.PYTHON,
            source=(
                "import logging\n"
                "from vendor import send\n"
                'logging.root.__dict__["warning"] = send\n'
                'logging.root.warning("event")\n'
            ),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="related-factory-namespace-escaped",
            language=Language.PYTHON,
            source=(
                "import logging\n"
                "from vendor import configure\n"
                'configure(logging.getLogger("app").__dict__)\n'
                'logging.getLogger("app").warning("event")\n'
            ),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="related-factory-namespace-replaced",
            language=Language.PYTHON,
            source=(
                "import logging\n"
                "from vendor import send\n"
                'logging.getLogger("app").__dict__["warning"] = send\n'
                'logging.getLogger("app").warning("event")\n'
            ),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="related-module-alias-namespace-cross-alias",
            language=Language.PYTHON,
            source=(
                "import logging as primary\n"
                "import logging as secondary\n"
                "from vendor import configure\n"
                "configure(primary.__dict__)\n"
                'secondary.warning("event")\n'
            ),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="related-ordinary-root-routing",
            language=Language.PYTHON,
            source=('import logging\nlogging.root.setLevel(logging.WARNING)\nlogging.root.warning("event")\n'),
            expected=ExpectedOutcome.MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        1,
    ),
    (
        EvaluationCase(
            case_id="related-ordinary-factory-routing",
            language=Language.PYTHON,
            source=(
                "import logging\n"
                'logging.getLogger("app").setLevel(logging.WARNING)\n'
                'logging.getLogger("app").warning("event")\n'
            ),
            expected=ExpectedOutcome.MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        1,
    ),
    (
        EvaluationCase(
            case_id="related-unrelated-namespace",
            language=Language.PYTHON,
            source=(
                "import logging\n"
                "import unrelated\n"
                "from vendor import configure\n"
                "configure(unrelated.__dict__)\n"
                'logging.warning("event")\n'
            ),
            expected=ExpectedOutcome.MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        1,
    ),
    (
        EvaluationCase(
            case_id="related-existing-module-namespace-escape",
            language=Language.PYTHON,
            source=(
                'import logging\nfrom vendor import configure\nconfigure(logging.__dict__)\nlogging.warning("event")\n'
            ),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="related-imported-root-escape-then-module-root",
            language=Language.PYTHON,
            source=(
                "import logging\n"
                "from logging import root as events\n"
                "from vendor import configure\n"
                "configure(events.__dict__)\n"
                'logging.root.warning("event")\n'
            ),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        0,
    ),
    (
        EvaluationCase(
            case_id="related-module-root-escape-then-imported-root",
            language=Language.PYTHON,
            source=(
                "import logging\n"
                "from logging import root as events\n"
                "from vendor import configure\n"
                "configure(logging.root.__dict__)\n"
                'events.warning("event")\n'
            ),
            expected=ExpectedOutcome.NO_MATCH,
            path=PurePosixPath("app/service.py"),
        ),
        0,
    ),
)


@pytest.mark.parametrize(("case", "expected_count"), _CASES, ids=[case.case_id for case, _count in _CASES])
def test_proven_application_uses_preserve_interoperability_and_test_scope(
    tmp_path: Path,
    case: EvaluationCase,
    expected_count: int,
) -> None:
    uses = application_logging_uses(tmp_path / case.path, case.source, root=tmp_path)

    assert len(uses) == expected_count
    assert bool(uses) is (case.expected is ExpectedOutcome.MATCH)
    assert all(use.line > 0 and use.column > 0 for use in uses)


def test_explicit_none_handlers_still_requests_a_default_builtin_sink(tmp_path: Path) -> None:
    uses = application_logging_uses(
        tmp_path / "service.py",
        "import logging\nlogging.basicConfig(handlers=None)\n",
        root=tmp_path,
    )

    assert [(use.operation, use.kind) for use in uses] == [("logging.basicConfig", "sink")]


@pytest.mark.parametrize(
    "relative", ["conftest.py", "test_bridge.py", "bridge_test.py", "tests/bridge.py", "integration_tests/bridge.py"]
)
def test_preference_uses_the_unchanged_native_test_path_scope(tmp_path: Path, relative: str) -> None:
    assert (
        application_logging_uses(tmp_path / relative, 'import logging\nlogging.warning("stimulus")\n', root=tmp_path)
        == ()
    )


def test_test_support_spelling_does_not_exempt_application_code(tmp_path: Path) -> None:
    uses = application_logging_uses(
        tmp_path / "testing/helpers.py", 'import logging\nlogging.warning("event")\n', root=tmp_path
    )

    assert len(uses) == 1


def test_selected_type_stubs_do_not_claim_runtime_application_events(tmp_path: Path) -> None:
    assert (
        application_logging_uses(tmp_path / "service.pyi", 'import logging\nlogging.warning("stub")\n', root=tmp_path)
        == ()
    )


@pytest.mark.parametrize("relative", ["vendor/client.py", "generated/client.py", ".venv/client.py"])
def test_native_generated_and_vendor_scopes_are_preserved(tmp_path: Path, relative: str) -> None:
    assert (
        application_logging_uses(tmp_path / relative, 'import logging\nlogging.warning("event")\n', root=tmp_path) == ()
    )


def test_generator_header_and_ai_attribution_have_distinct_native_meanings(tmp_path: Path) -> None:
    event = 'import logging\nlogging.warning("event")\n'

    assert application_logging_uses(tmp_path / "generated.py", "# Generated by protoc\n" + event, root=tmp_path) == ()
    assert len(application_logging_uses(tmp_path / "service.py", "# Generated by AI\n" + event, root=tmp_path)) == 1


def test_positions_are_unicode_codepoint_columns(tmp_path: Path) -> None:
    uses = application_logging_uses(
        tmp_path / "service.py", 'import logging\n"é"; logging.warning("event")\n', root=tmp_path
    )

    assert [(use.line, use.column, use.operation) for use in uses] == [(2, 6, "logging.warning")]


def test_source_and_root_are_explicit_and_confined(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="escapes repository root"):
        application_logging_uses(tmp_path.parent / "outside.py", "import logging\n", root=tmp_path)
    with pytest.raises(ValueError, match="canonical absolute"):
        application_logging_uses(Path("service.py"), "import logging\n", root=tmp_path)
    with pytest.raises(ValueError, match="bounded selected Python"):
        application_logging_uses(tmp_path / "service.txt", "import logging\n", root=tmp_path)


def test_selected_malformed_and_oversized_source_cannot_become_success(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="could not be parsed"):
        application_logging_uses(tmp_path / "service.py", "def broken(\n", root=tmp_path)
    with pytest.raises(ValueError, match="bounded selected Python"):
        application_logging_uses(tmp_path / "service.py", "x" * 500_001, root=tmp_path)
