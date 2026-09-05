from pathlib import Path, PurePosixPath

import pytest

from sarj_standards.libs.linting import textlint
from sarj_standards.libs.rules.contracts import (
    EvaluationCase,
    ExampleFile,
    ExpectedOutcome,
    Language,
    RuleExample,
)


SHELL_IAC_EVALUATION_CASES = (
    EvaluationCase(
        "grep-pattern-looks-like-terraform-path",
        Language.CONFIG,
        "grep -q main.tf audit.log\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath("tests/policy.test.sh"),
    ),
    EvaluationCase(
        "rg-pattern-looks-like-terraform-path",
        Language.CONFIG,
        "rg main.tf audit.log\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath("tests/policy.test.sh"),
    ),
    EvaluationCase(
        "sed-expression-looks-like-terraform-path",
        Language.CONFIG,
        "sed -e main.tf audit.log\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath("tests/policy.test.sh"),
    ),
    EvaluationCase(
        "awk-program-looks-like-terraform-path",
        Language.CONFIG,
        "awk main.tf audit.log\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath("tests/policy.test.sh"),
    ),
    EvaluationCase(
        "pipeline-prints-terraform-filename",
        Language.CONFIG,
        "printf main.tf | grep -q main\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath("tests/policy.test.sh"),
    ),
    EvaluationCase(
        "terraform-path-variable-input",
        Language.CONFIG,
        'source_path=iac/main.tf\ngrep -q resource "$source_path"\n',
        ExpectedOutcome.MATCH,
        PurePosixPath("tests/policy.test.sh"),
    ),
    EvaluationCase(
        "continued-terraform-input",
        Language.CONFIG,
        "grep -q resource \\\n  iac/main.tf\n",
        ExpectedOutcome.MATCH,
        PurePosixPath("tests/policy.test.sh"),
    ),
    EvaluationCase(
        "terraform-path-variable-content-flow",
        Language.CONFIG,
        'source_path=iac/main.tf\nsource_text="$(cat "$source_path")"\n[[ "$source_text" == *resource* ]]\n',
        ExpectedOutcome.MATCH,
        PurePosixPath("tests/policy.test.sh"),
    ),
    EvaluationCase(
        "direct-command-substitution-in-double-bracket",
        Language.CONFIG,
        "[[ $(cat iac/main.tf) == *resource* ]]\n",
        ExpectedOutcome.MATCH,
        PurePosixPath("tests/policy.test.sh"),
    ),
    EvaluationCase(
        "direct-command-substitution-in-test",
        Language.CONFIG,
        'test -n "$(cat iac/main.tf)"\n',
        ExpectedOutcome.MATCH,
        PurePosixPath("tests/policy.test.sh"),
    ),
    EvaluationCase(
        "unrelated-command-substitution-with-iac-looking-pattern",
        Language.CONFIG,
        "[[ $(cat audit.log) == *main.tf* ]]\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath("tests/policy.test.sh"),
    ),
    EvaluationCase(
        "structured-plan-command-substitution",
        Language.CONFIG,
        'test -n "$(terraform show -json plan.out)"\n',
        ExpectedOutcome.NO_MATCH,
        PurePosixPath("tests/policy.test.sh"),
    ),
)

MARKDOWN_HIDDEN_COMMENT_CASES = (
    EvaluationCase(
        "hidden-heading-block",
        Language.MARKDOWN,
        "<!--\n## Legacy setup\nUse the retired command.\n-->\n",
        ExpectedOutcome.MATCH,
        PurePosixPath("README.md"),
    ),
    EvaluationCase(
        "hidden-heading-single-line",
        Language.MARKDOWN,
        "<!-- ## Legacy setup -->\n",
        ExpectedOutcome.MATCH,
        PurePosixPath("README.md"),
    ),
    EvaluationCase(
        "ordinary-hidden-template-instruction",
        Language.MARKDOWN,
        "<!-- Explain why this change is needed. -->\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath(".github/pull_request_template.md"),
    ),
    EvaluationCase(
        "heading-example-in-fence",
        Language.MARKDOWN,
        "```markdown\n<!-- ## Legacy setup -->\n```\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath("README.md"),
    ),
    EvaluationCase(
        "heading-example-in-indented-code",
        Language.MARKDOWN,
        "    <!-- ## Legacy setup -->\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath("README.md"),
    ),
    EvaluationCase(
        "unclosed-html-comment",
        Language.MARKDOWN,
        "<!--\n## Legacy setup\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath("README.md"),
    ),
    EvaluationCase(
        "protected-external-constraint",
        Language.MARKDOWN,
        "<!--\n## Compatibility workaround\nRequired by https://vendor.example/spec.\n-->\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath("README.md"),
    ),
    EvaluationCase(
        "markdownlint-directive",
        Language.MARKDOWN,
        "<!-- markdownlint-disable MD025\n# Generated title\n-->\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath("README.md"),
    ),
)

EXACT_CONFIG_RESTATEMENT_CASES = (
    EvaluationCase(
        "toml-exact-restatement",
        Language.CONFIG,
        "# Retry count is 3\nretry_count = 3\n",
        ExpectedOutcome.MATCH,
        PurePosixPath("config.toml"),
    ),
    EvaluationCase(
        "yaml-exact-restatement",
        Language.CONFIG,
        "# Deploy environment equals production\ndeploy-environment: production\n",
        ExpectedOutcome.MATCH,
        PurePosixPath("config.yaml"),
    ),
    EvaluationCase(
        "quoted-scalar-restatement",
        Language.CONFIG,
        '# Environment is production\nenvironment = "production"\n',
        ExpectedOutcome.MATCH,
        PurePosixPath("config.toml"),
    ),
    EvaluationCase(
        "rationale-adds-information",
        Language.CONFIG,
        "# Keep three retries because the upstream API is eventually consistent.\nretry_count = 3\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath("config.toml"),
    ),
    EvaluationCase(
        "value-does-not-match",
        Language.CONFIG,
        "# Retry count is 5\nretry_count = 3\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath("config.toml"),
    ),
    EvaluationCase(
        "comment-has-extra-fact",
        Language.CONFIG,
        "# Retry count is 3 for transient failures\nretry_count = 3\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath("config.toml"),
    ),
    EvaluationCase(
        "blank-line-breaks-attachment",
        Language.CONFIG,
        "# Retry count is 3\n\nretry_count = 3\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath("config.toml"),
    ),
    EvaluationCase(
        "collection-value-is-out-of-scope",
        Language.CONFIG,
        "# Ports are 80 443\nports: [80, 443]\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath("config.yaml"),
    ),
    EvaluationCase(
        "yaml-block-scalar-is-out-of-scope",
        Language.CONFIG,
        "# Script is echo ready\nscript: |\n  echo ready\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath("config.yaml"),
    ),
)

COMMAND_ARGUMENT_CASES = (
    EvaluationCase(
        "unquoted-shell-argument",
        Language.MARKDOWN,
        "```bash\nscripts/config-diff.sh $ARGUMENTS\n```\n",
        ExpectedOutcome.MATCH,
        PurePosixPath(".claude/commands/config-diff.md"),
    ),
    EvaluationCase(
        "sql-query-interpolation",
        Language.MARKDOWN,
        "```sql\nSELECT id FROM account WHERE id = '$ARGUMENTS';\n```\n",
        ExpectedOutcome.MATCH,
        PurePosixPath(".claude/commands/account.md"),
    ),
    EvaluationCase(
        "sql-inside-wrapper-string",
        Language.MARKDOWN,
        "```bash\nscripts/db.sh \"SELECT id FROM account WHERE id = '$ARGUMENTS';\"\n```\n",
        ExpectedOutcome.MATCH,
        PurePosixPath(".claude/commands/account.md"),
    ),
    EvaluationCase(
        "log-query-interpolation",
        Language.MARKDOWN,
        '```logql\n{job="worker"} |= "$ARGUMENTS"\n```\n',
        ExpectedOutcome.MATCH,
        PurePosixPath(".claude/commands/trace.md"),
    ),
    EvaluationCase(
        "quoted-wrapper-argument",
        Language.MARKDOWN,
        '```bash\nscripts/logs.sh "$ARGUMENTS" 1000\n```\n',
        ExpectedOutcome.NO_MATCH,
        PurePosixPath(".claude/commands/logs.md"),
    ),
    EvaluationCase(
        "argument-in-prose",
        Language.MARKDOWN,
        "Run this command for **$ARGUMENTS**.\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath(".claude/commands/help.md"),
    ),
    EvaluationCase(
        "non-command-document",
        Language.MARKDOWN,
        "```bash\nscripts/config-diff.sh $ARGUMENTS\n```\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath("docs/command-authoring.md"),
    ),
)

SECRET_PERMISSION_CASES = (
    EvaluationCase(
        "gcloud-wildcard-secret-read",
        Language.CONFIG,
        '{"permissions":{"allow":["Bash(gcloud secrets versions access:*)"]}}\n',
        ExpectedOutcome.MATCH,
        PurePosixPath(".claude/settings.json"),
    ),
    EvaluationCase(
        "aws-wildcard-secret-read",
        Language.CONFIG,
        '{"permissions":{"allow":["Bash(aws secretsmanager get-secret-value:*)"]}}\n',
        ExpectedOutcome.MATCH,
        PurePosixPath(".claude/settings.local.json"),
    ),
    EvaluationCase(
        "project-secret-wrapper",
        Language.CONFIG,
        '{"permissions":{"allow":["Bash(make pull-development-secrets)"]}}\n',
        ExpectedOutcome.NO_MATCH,
        PurePosixPath(".claude/settings.json"),
    ),
    EvaluationCase(
        "unrelated-gcloud-read",
        Language.CONFIG,
        '{"permissions":{"allow":["Bash(gcloud logging read:*)"]}}\n',
        ExpectedOutcome.NO_MATCH,
        PurePosixPath(".claude/settings.json"),
    ),
    EvaluationCase(
        "non-claude-json",
        Language.CONFIG,
        '{"permissions":{"allow":["Bash(gcloud secrets versions access:*)"]}}\n',
        ExpectedOutcome.NO_MATCH,
        PurePosixPath("config/settings.json"),
    ),
    EvaluationCase(
        "invalid-settings-json",
        Language.CONFIG,
        "{not json}\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath(".claude/settings.json"),
    ),
)

WORKFLOW_EMBEDDED_PROGRAM_CASES = (
    EvaluationCase(
        "shell-if-program",
        Language.CONFIG,
        "jobs:\n  test:\n    steps:\n      - run: |\n          if make probe; then\n            make test\n          fi\n",
        ExpectedOutcome.MATCH,
        PurePosixPath(".github/workflows/ci.yml"),
    ),
    EvaluationCase(
        "shell-loop-program",
        Language.CONFIG,
        "jobs:\n  test:\n    steps:\n      - run: |\n          for item in api worker; do\n            make test-package PACKAGE=$item\n          done\n",
        ExpectedOutcome.MATCH,
        PurePosixPath(".github/workflows/ci.yml"),
    ),
    EvaluationCase(
        "shell-case-program",
        Language.CONFIG,
        "jobs:\n  test:\n    steps:\n      - run: |\n          case $MODE in\n            fast) make test-fast ;;\n          esac\n",
        ExpectedOutcome.MATCH,
        PurePosixPath(".github/workflows/ci.yml"),
    ),
    EvaluationCase(
        "shell-function-program",
        Language.CONFIG,
        "jobs:\n  test:\n    steps:\n      - run: |\n          retry() {\n            make probe\n          }\n          retry\n",
        ExpectedOutcome.MATCH,
        PurePosixPath(".github/workflows/ci.yml"),
    ),
    EvaluationCase(
        "python-inline-program",
        Language.CONFIG,
        "jobs:\n  test:\n    steps:\n      - run: python3 -c 'import json; print(json.dumps({}))'\n",
        ExpectedOutcome.MATCH,
        PurePosixPath(".github/workflows/ci.yml"),
    ),
    EvaluationCase(
        "absolute-python-inline-program",
        Language.CONFIG,
        "jobs:\n  test:\n    steps:\n      - run: /usr/bin/python3 -c 'print(1)'\n",
        ExpectedOutcome.MATCH,
        PurePosixPath(".github/workflows/ci.yml"),
    ),
    EvaluationCase(
        "node-inline-program",
        Language.CONFIG,
        "jobs:\n  test:\n    steps:\n      - run: node -e 'process.stdout.write(`ok`)'\n",
        ExpectedOutcome.MATCH,
        PurePosixPath(".github/workflows/ci.yml"),
    ),
    EvaluationCase(
        "shell-inline-program",
        Language.CONFIG,
        "jobs:\n  test:\n    steps:\n      - run: bash -c 'if make probe; then make test; fi'\n",
        ExpectedOutcome.MATCH,
        PurePosixPath(".github/workflows/ci.yml"),
    ),
    EvaluationCase(
        "php-inline-program",
        Language.CONFIG,
        "jobs:\n  test:\n    steps:\n      - run: php -r 'echo json_encode([]);'\n",
        ExpectedOutcome.MATCH,
        PurePosixPath(".github/workflows/ci.yml"),
    ),
    EvaluationCase(
        "interpreter-heredoc-program",
        Language.CONFIG,
        "jobs:\n  test:\n    steps:\n      - run: |\n          python3 - <<'PY'\n          print('ok')\n          PY\n",
        ExpectedOutcome.MATCH,
        PurePosixPath(".github/workflows/ci.yml"),
    ),
    EvaluationCase(
        "combined-bash-inline-program",
        Language.CONFIG,
        "jobs:\n  test:\n    steps:\n      - run: bash -lc 'make test'\n",
        ExpectedOutcome.MATCH,
        PurePosixPath(".github/workflows/ci.yml"),
    ),
    EvaluationCase(
        "combined-python-inline-program",
        Language.CONFIG,
        "jobs:\n  test:\n    steps:\n      - run: python3 -Bc 'print(1)'\n",
        ExpectedOutcome.MATCH,
        PurePosixPath(".github/workflows/ci.yml"),
    ),
    EvaluationCase(
        "attached-node-inline-program",
        Language.CONFIG,
        "jobs:\n  test:\n    steps:\n      - run: node -pe'process.version'\n",
        ExpectedOutcome.MATCH,
        PurePosixPath(".github/workflows/ci.yml"),
    ),
    EvaluationCase(
        "workflow-if-expression",
        Language.CONFIG,
        "jobs:\n  test:\n    if: github.ref == 'refs/heads/main'\n    steps:\n      - run: make test\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath(".github/workflows/ci.yml"),
    ),
    EvaluationCase(
        "manual-wrapper-workflow",
        Language.CONFIG,
        "on: workflow_dispatch\njobs:\n  capture:\n    steps:\n      - run: ./scripts/capture.sh\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath(".github/workflows/capture.yml"),
    ),
    EvaluationCase(
        "interpreter-script-argument",
        Language.CONFIG,
        "jobs:\n  test:\n    steps:\n      - run: python3 scripts/check.py -c strict\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath(".github/workflows/ci.yml"),
    ),
    EvaluationCase(
        "interpreter-script-stdin",
        Language.CONFIG,
        "jobs:\n  test:\n    steps:\n      - run: python3 scripts/check.py <<'DATA'\n          input\n          DATA\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath(".github/workflows/ci.yml"),
    ),
    EvaluationCase(
        "bash-errexit-script",
        Language.CONFIG,
        "jobs:\n  test:\n    steps:\n      - run: bash -e scripts/check.sh\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath(".github/workflows/ci.yml"),
    ),
    EvaluationCase(
        "node-check-script",
        Language.CONFIG,
        "jobs:\n  test:\n    steps:\n      - run: node -c scripts/check.js\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath(".github/workflows/ci.yml"),
    ),
    EvaluationCase(
        "data-heredoc-control-word",
        Language.CONFIG,
        "jobs:\n  test:\n    steps:\n      - run: |\n          cat > report.txt <<'DATA'\n          if this is data\n          DATA\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath(".github/workflows/ci.yml"),
    ),
    EvaluationCase(
        "numeric-data-heredoc",
        Language.CONFIG,
        "jobs:\n  test:\n    steps:\n      - run: |\n          cat <<123\n          if this is data\n          123\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath(".github/workflows/ci.yml"),
    ),
    EvaluationCase(
        "dashed-data-heredoc",
        Language.CONFIG,
        "jobs:\n  test:\n    steps:\n      - run: |\n          cat <<'END-DATA'\n          for this is data\n          END-DATA\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath(".github/workflows/ci.yml"),
    ),
    EvaluationCase(
        "dynamic-looking-data-heredoc",
        Language.CONFIG,
        "jobs:\n  test:\n    steps:\n      - run: |\n          cat <<'$END'\n          while this is data\n          $END\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath(".github/workflows/ci.yml"),
    ),
    EvaluationCase(
        "multiple-data-heredocs-before-program",
        Language.CONFIG,
        "jobs:\n  test:\n    steps:\n      - run: |\n          cat <<ONE <<'TWO'\n          if this is data\n          ONE\n          for this is also data\n          TWO\n          while make probe; do make test; done\n",
        ExpectedOutcome.MATCH,
        PurePosixPath(".github/workflows/ci.yml"),
    ),
    EvaluationCase(
        "tab-stripped-data-heredoc",
        Language.CONFIG,
        "jobs:\n  test:\n    steps:\n      - run: |\n          cat <<-'DATA'\n\tif this is data\n\tDATA\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath(".github/workflows/ci.yml"),
    ),
    EvaluationCase(
        "escaped-data-heredoc",
        Language.CONFIG,
        "jobs:\n  test:\n    steps:\n      - run: |\n          cat <<END\\-DATA\n          case this is data\n          END-DATA\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath(".github/workflows/ci.yml"),
    ),
    EvaluationCase(
        "quoted-heredoc-operator-before-program",
        Language.CONFIG,
        "jobs:\n  test:\n    steps:\n      - run: |\n          echo '<<DATA'\n          if make probe; then make test; fi\n",
        ExpectedOutcome.MATCH,
        PurePosixPath(".github/workflows/ci.yml"),
    ),
    EvaluationCase(
        "here-string-before-program",
        Language.CONFIG,
        "jobs:\n  test:\n    steps:\n      - run: |\n          cat <<< 'if this is data'\n          while make probe; do make test; done\n",
        ExpectedOutcome.MATCH,
        PurePosixPath(".github/workflows/ci.yml"),
    ),
    EvaluationCase(
        "ordinary-multiline-orchestration",
        Language.CONFIG,
        "jobs:\n  test:\n    steps:\n      - run: |\n          make lint\n          make test\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath(".github/workflows/ci.yml"),
    ),
    EvaluationCase(
        "simple-shell-guard",
        Language.CONFIG,
        'jobs:\n  test:\n    steps:\n      - run: test -n "$TOKEN" || exit 1\n',
        ExpectedOutcome.NO_MATCH,
        PurePosixPath(".github/workflows/ci.yml"),
    ),
    EvaluationCase(
        "quoted-control-flow-word",
        Language.CONFIG,
        "jobs:\n  test:\n    steps:\n      - run: echo 'if this were procedural'\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath(".github/workflows/ci.yml"),
    ),
    EvaluationCase(
        "control-word-executable-path",
        Language.CONFIG,
        "jobs:\n  test:\n    steps:\n      - run: ./if --check\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath(".github/workflows/ci.yml"),
    ),
    EvaluationCase(
        "nested-control-word-executable-path",
        Language.CONFIG,
        "jobs:\n  test:\n    steps:\n      - run: tools/for --check\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath(".github/workflows/ci.yml"),
    ),
    EvaluationCase(
        "commented-control-flow-word",
        Language.CONFIG,
        "jobs:\n  test:\n    steps:\n      - run: |\n          # if this were procedural\n          make test\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath(".github/workflows/ci.yml"),
    ),
    EvaluationCase(
        "multiline-jq-program",
        Language.CONFIG,
        "jobs:\n  test:\n    steps:\n      - run: |\n          jq '\n            .items |\n            select(.active)\n          ' report.json\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath(".github/workflows/ci.yml"),
    ),
    EvaluationCase(
        "external-action",
        Language.CONFIG,
        "jobs:\n  test:\n    steps:\n      - uses: actions/checkout@v7\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath(".github/workflows/ci.yml"),
    ),
    EvaluationCase(
        "reusable-workflow-job",
        Language.CONFIG,
        "jobs:\n  test:\n    uses: ./.github/workflows/reusable.yml\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath(".github/workflows/ci.yml"),
    ),
    EvaluationCase(
        "malformed-workflow",
        Language.CONFIG,
        "jobs: [unterminated\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath(".github/workflows/ci.yml"),
    ),
    EvaluationCase(
        "non-workflow-yaml",
        Language.CONFIG,
        "steps:\n  - run: |\n      if make probe; then make test; fi\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath("config/pipeline.yml"),
    ),
    EvaluationCase(
        "nested-non-workflow-yaml",
        Language.CONFIG,
        "jobs:\n  test:\n    steps:\n      - run: if make probe; then make test; fi\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath(".github/workflows/archive/ci.yml"),
    ),
    EvaluationCase(
        "action-command-input",
        Language.CONFIG,
        "jobs:\n  test:\n    steps:\n      - uses: vendor/action@v1\n        with:\n          command: if make probe\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath(".github/workflows/ci.yml"),
    ),
)


def _codes(path: Path, *, root: Path | None = None) -> list[str]:
    return [finding.code for finding in textlint.check_paths([str(path)], root=root)]


@pytest.mark.parametrize(
    ("relative", "source"),
    [
        (".github/workflows/deploy.yml", "steps:\n  - run: gcloud run deploy api --image $IMAGE --memory=1Gi\n"),
        (
            ".github/workflows/jobs.yml",
            "steps:\n  - run: gcloud run jobs update migrate --image image --set-secrets=TOKEN=token:latest\n",
        ),
        ("cloudbuild/database.yml", "gcloud sql instances patch main --activation-policy=ALWAYS\n"),
        ("deploy/scheduler.sh", "gcloud scheduler jobs create http cleanup --uri=https://example.test\n"),
        ("iac/state.sh", "terraform -chdir=stack state replace-provider old/provider new/provider\n"),
        (
            "iac/example/envs.json",
            '{"dev":{"safety_boundary":{"allowed_change_addresses":["module.service"]}}}\n',
        ),
        ("k8s/cluster.sh", "if ! kubectl -n agent annotate deployment/api owner=terraform; then exit 1; fi\n"),
        ("scripts/secrets.sh", "gcloud secrets versions add api-key --data-file=-\n"),
        ("tools/state.sh", "tofu state rm module.legacy\n"),
        ("deploy/function.sh", "gcloud functions deploy api\n"),
        ("deploy/services.sh", "gcloud services enable run.googleapis.com\n"),
        ("deploy/build-trigger.sh", "gcloud builds triggers create github --name=deploy\n"),
        ("cloudbuild/release.cloudbuild.yaml", "gcloud deploy releases create release-1 --region=us\n"),
        ("deploy/workflow.sh", "gcloud workflows deploy sync --source=workflow.yaml\n"),
        ("deploy/job.sh", "gcloud run jobs update migrate --image=image --service-account=runtime@example.test\n"),
        ("deploy/schedule.sh", "gcloud scheduler jobs update http cleanup --uri=https://example.test\n"),
        ("tools/database.sh", "wrangler --env dev d1 create app\n"),
        ("iac/import.sh", "opentofu import google_project.main project\n"),
        ("iac/taint.sh", "terraform taint google_project.main\n"),
        ("iac/untaint.sh", "tofu untaint google_project.main\n"),
        ("deploy/command.sh", "command -- gcloud run deploy api\n"),
    ],
)
def test_declarative_deployment_boundary_flags_parallel_mutation(tmp_path: Path, relative: str, source: str) -> None:
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding="utf-8")
    assert _codes(path, root=tmp_path) == ["SARJ309"]


@pytest.mark.parametrize(
    "source",
    [
        "steps:\n  - run: terraform apply saved.tfplan\n",
        "steps:\n  - run: terraform show -json saved.tfplan\n",
        "steps:\n  - run: terraform state list\n",
        "steps:\n  - run: gcloud run services describe api\n",
        "steps:\n  - run: gcloud storage cp gs://artifacts/input.json input.json\n",
        "steps:\n  - run: kubectl get deployment api\n",
        "steps:\n  - run: kubectl -n agent rollout status deployment/api\n",
        "steps:\n  - run: yarn exec wrangler deploy --env dev --dry-run\n",
        "steps:\n  - run: pnpm exec wrangler deploy --tag $GITHUB_SHA\n",
        "steps:\n  - run: yarn exec wrangler versions deploy abc@100 --yes\n",
        "steps:\n  - run: npx --yes wrangler deploy\n",
        "steps:\n  - run: gcloud run deploy api --image $IMAGE --region us --platform managed --quiet\n",
        "steps:\n  - run: gcloud run deploy api --source . --region us --no-traffic --tag candidate\n",
        "steps:\n  - run: gcloud run services update api --image=$IMAGE --region=us --no-traffic\n",
        "steps:\n  - run: gcloud --project platform beta run jobs update migrate --image image --region us --wait\n",
        "steps:\n  - run: gcloud run services update api --image=$IMAGE --region=us --project=platform\n",
        (
            "steps:\n  - run: gcloud run jobs update ${{ matrix.job }} --image ${{ needs.build.outputs.image }} "
            "--project=${{ vars.PROJECT }} --region=${{ vars.REGION }}\n"
        ),
        "steps:\n  - run: gcloud workflows run sync\n",
        "steps:\n  - run: gcloud run jobs execute migrate --wait\n",
        "steps:\n  - run: gcloud scheduler jobs run cleanup\n",
        "steps:\n  - run: gcloud builds triggers run deploy\n",
        "steps:\n  - run: gcloud builds cancel build-id\n",
        "steps:\n  - run: gcloud compute instances stop worker\n",
        "steps:\n  - run: gcloud sql instances restart database\n",
        "steps:\n  - run: gcloud tasks queues pause jobs\n",
        "steps:\n  - run: kubectl rollout restart deployment/api\n",
        "steps:\n  - run: kubectl drain node-1\n",
        'steps:\n  - name: "Example: run: gcloud run deploy api"\n',
        "steps:\n  - run: echo 'gcloud run deploy api'\n",
    ],
)
def test_declarative_deployment_boundary_allows_plan_apply_and_diagnostics(tmp_path: Path, source: str) -> None:
    path = tmp_path / ".github" / "workflows" / "deploy.yml"
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding="utf-8")
    assert "SARJ309" not in _codes(path, root=tmp_path)


@pytest.mark.parametrize(
    "source",
    [
        'steps:\n  - run: "gcloud run deploy api"\n',
        "steps:\n  - run: >\n      gcloud run\n      deploy api\n",
    ],
)
def test_declarative_deployment_boundary_parses_yaml_run_scalar_semantics(tmp_path: Path, source: str) -> None:
    path = tmp_path / ".github" / "workflows" / "deploy.yml"
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding="utf-8")

    assert _codes(path, root=tmp_path) == ["SARJ309"]


@pytest.mark.parametrize(
    "source",
    [
        "steps:\n  - uses: google-github-actions/deploy-cloud-functions@v4\n",
    ],
)
def test_declarative_deployment_boundary_flags_direct_deployment_actions(tmp_path: Path, source: str) -> None:
    path = tmp_path / ".github" / "workflows" / "deploy.yml"
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding="utf-8")

    assert _codes(path, root=tmp_path) == ["SARJ309"]


def test_declarative_deployment_boundary_allows_cloud_run_application_publish_action(tmp_path: Path) -> None:
    path = tmp_path / ".github" / "workflows" / "deploy.yml"
    path.parent.mkdir(parents=True)
    path.write_text("steps:\n  - uses: google-github-actions/deploy-cloudrun@v3\n", encoding="utf-8")

    assert "SARJ309" not in _codes(path, root=tmp_path)


def test_declarative_deployment_boundary_allows_worker_application_publish_action(tmp_path: Path) -> None:
    path = tmp_path / ".github" / "workflows" / "deploy.yml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "steps:\n  - uses: cloudflare/wrangler-action@v3\n    with:\n      command: versions deploy abc@100\n",
        encoding="utf-8",
    )

    assert "SARJ309" not in _codes(path, root=tmp_path)


def test_declarative_deployment_boundary_ignores_application_commands(tmp_path: Path) -> None:
    path = tmp_path / "packages" / "cloud-client" / "commands.sh"
    path.parent.mkdir(parents=True)
    path.write_text("gcloud run deploy api --image $IMAGE\n", encoding="utf-8")
    assert "SARJ309" not in _codes(path, root=tmp_path)


def test_declarative_deployment_boundary_ignores_operational_markdown(tmp_path: Path) -> None:
    path = tmp_path / "iac" / "README.md"
    path.parent.mkdir()
    path.write_text("```sh\nkubectl apply -f deployment.yaml\n```\n", encoding="utf-8")
    assert "SARJ309" not in _codes(path, root=tmp_path)


def test_declarative_deployment_boundary_reports_once_per_file(tmp_path: Path) -> None:
    path = tmp_path / "scripts" / "deploy.sh"
    path.parent.mkdir()
    path.write_text("gcloud run deploy api\nkubectl apply -f deployment.yaml\n", encoding="utf-8")
    assert _codes(path, root=tmp_path).count("SARJ309") == 1


def test_workflow_embedded_program_reports_once_per_run_scalar_at_run_line(
    tmp_path: Path,
) -> None:
    path = tmp_path / ".github" / "workflows" / "ci.yml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "jobs:\n  test:\n    steps:\n      - name: procedural\n        run: |\n"
        "          if make probe; then\n            for item in api worker; do\n"
        "              make test-package PACKAGE=$item\n            done\n          fi\n",
        encoding="utf-8",
    )

    findings = [finding for finding in textlint.check_paths([str(path)], root=tmp_path) if finding.code == "SARJ310"]

    assert [(finding.line, finding.code) for finding in findings] == [(5, "SARJ310")]


def test_workflow_embedded_program_deduplicates_yaml_aliases(tmp_path: Path) -> None:
    path = tmp_path / ".github" / "workflows" / "ci.yml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "jobs:\n  test:\n    steps:\n"
        "      - &procedural\n"
        "        run: if make probe; then make test; fi\n"
        "      - *procedural\n",
        encoding="utf-8",
    )

    findings = [finding for finding in textlint.check_paths([str(path)], root=tmp_path) if finding.code == "SARJ310"]

    assert [(finding.line, finding.code) for finding in findings] == [(5, "SARJ310")]


def test_deployment_boundary_takes_precedence_over_embedded_program(tmp_path: Path) -> None:
    path = tmp_path / ".github" / "workflows" / "deploy.yml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "jobs:\n  deploy:\n    steps:\n      - run: |\n"
        '          if test -n "$IMAGE"; then\n'
        '            gcloud run deploy api --image "$IMAGE" --memory 1Gi\n'
        "          fi\n",
        encoding="utf-8",
    )

    assert _codes(path, root=tmp_path) == ["SARJ309"]

    selected = textlint.check_paths(
        [str(path)],
        root=tmp_path,
        rule_ids=frozenset({"workflow-embedded-program"}),
    )
    assert [finding.code for finding in selected] == ["SARJ310"]


def test_heredoc_data_does_not_create_deployment_precedence(tmp_path: Path) -> None:
    path = tmp_path / ".github" / "workflows" / "report.yml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "jobs:\n  report:\n    steps:\n      - run: |\n"
        "          if make report; then echo ready; fi\n"
        "          cat > report.txt <<'DATA'\n"
        "          gcloud run deploy api --memory 1Gi\n"
        "          DATA\n",
        encoding="utf-8",
    )

    assert _codes(path, root=tmp_path) == ["SARJ310"]


def test_workflow_embedded_program_is_warning_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / ".github" / "workflows" / "ci.yml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "jobs:\n  test:\n    steps:\n      - run: |\n          while make probe; do make test; done\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    assert textlint.run([str(path)]) == 0
    assert "SARJ310 warning:" in capsys.readouterr().out


def test_declarative_deployment_boundary_reads_real_plan_allowlist_fixture(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "textlint" / "envs.json"
    path = tmp_path / "iac" / "example" / "envs.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(fixture.read_bytes())

    assert _codes(path, root=tmp_path) == ["SARJ309"]


def test_plan_allowlist_matches_structured_camel_case_key_without_matching_prose(tmp_path: Path) -> None:
    prose = tmp_path / "iac" / "prose.json"
    prose.parent.mkdir()
    prose.write_text('{"note":"allowed_change_addresses explains the retired design"}\n', encoding="utf-8")
    config = tmp_path / "iac" / "envs.json"
    config.write_text('{"dev":{"allowedChangeAddresses":[]}}\n', encoding="utf-8")

    assert "SARJ309" not in _codes(prose, root=tmp_path)
    assert _codes(config, root=tmp_path) == ["SARJ309"]


def test_declarative_deployment_boundary_does_not_resolve_wrappers(tmp_path: Path) -> None:
    workflow = tmp_path / ".github" / "workflows" / "deploy.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("steps:\n  - run: ./scripts/deploy.sh\n", encoding="utf-8")
    wrapper = tmp_path / "scripts" / "deploy.sh"
    wrapper.parent.mkdir()
    wrapper.write_text("gcloud run deploy api --image image --memory 1Gi\n", encoding="utf-8")

    assert "SARJ309" not in _codes(workflow, root=tmp_path)
    assert _codes(wrapper, root=tmp_path) == ["SARJ309"]


@pytest.mark.parametrize(
    "case",
    SHELL_IAC_EVALUATION_CASES,
    ids=tuple(case.case_id for case in SHELL_IAC_EVALUATION_CASES),
)
def test_shell_iac_labeled_evaluation_cases(case: EvaluationCase, tmp_path: Path) -> None:
    path = tmp_path / case.path
    path.parent.mkdir(parents=True)
    path.write_text(case.source, encoding="utf-8")

    findings = [finding for finding in textlint.check_paths([str(path)], root=tmp_path) if finding.code == "SARJ304"]

    assert bool(findings) is (case.expected is ExpectedOutcome.MATCH)


@pytest.mark.parametrize(
    "case",
    MARKDOWN_HIDDEN_COMMENT_CASES,
    ids=tuple(case.case_id for case in MARKDOWN_HIDDEN_COMMENT_CASES),
)
def test_markdown_hidden_comment_labeled_evaluation_cases(case: EvaluationCase, tmp_path: Path) -> None:
    path = tmp_path / case.path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(case.source, encoding="utf-8")

    findings = [finding for finding in textlint.check_paths([str(path)], root=tmp_path) if finding.code == "SARJ305"]

    assert bool(findings) is (case.expected is ExpectedOutcome.MATCH)


@pytest.mark.parametrize(
    "case",
    COMMAND_ARGUMENT_CASES,
    ids=tuple(case.case_id for case in COMMAND_ARGUMENT_CASES),
)
def test_command_argument_labeled_evaluation_cases(case: EvaluationCase, tmp_path: Path) -> None:
    path = tmp_path / case.path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(case.source, encoding="utf-8")

    findings = [finding for finding in textlint.check_paths([str(path)], root=tmp_path) if finding.code == "SARJ307"]

    assert bool(findings) is (case.expected is ExpectedOutcome.MATCH)


@pytest.mark.parametrize(
    "case",
    SECRET_PERMISSION_CASES,
    ids=tuple(case.case_id for case in SECRET_PERMISSION_CASES),
)
def test_secret_permission_labeled_evaluation_cases(case: EvaluationCase, tmp_path: Path) -> None:
    path = tmp_path / case.path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(case.source, encoding="utf-8")

    findings = [finding for finding in textlint.check_paths([str(path)], root=tmp_path) if finding.code == "SARJ308"]

    assert bool(findings) is (case.expected is ExpectedOutcome.MATCH)


@pytest.mark.parametrize(
    "case",
    WORKFLOW_EMBEDDED_PROGRAM_CASES,
    ids=tuple(case.case_id for case in WORKFLOW_EMBEDDED_PROGRAM_CASES),
)
def test_workflow_embedded_program_labeled_cases(case: EvaluationCase, tmp_path: Path) -> None:
    path = tmp_path / case.path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(case.source, encoding="utf-8")

    findings = [finding for finding in textlint.check_paths([str(path)], root=tmp_path) if finding.code == "SARJ310"]

    assert bool(findings) is (case.expected is ExpectedOutcome.MATCH)


@pytest.mark.parametrize(
    "case",
    EXACT_CONFIG_RESTATEMENT_CASES,
    ids=tuple(case.case_id for case in EXACT_CONFIG_RESTATEMENT_CASES),
)
def test_exact_config_restatement_labeled_evaluation_cases(case: EvaluationCase, tmp_path: Path) -> None:
    path = tmp_path / case.path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(case.source, encoding="utf-8")

    findings = [finding for finding in textlint.check_paths([str(path)], root=tmp_path) if finding.code == "SARJ306"]

    assert bool(findings) is (case.expected is ExpectedOutcome.MATCH)


def test_shell_iac_source_rule_blocks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "tests" / "policy.test.sh"
    path.parent.mkdir(parents=True)
    path.write_text("grep -q resource iac/main.tf\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert textlint.run(["tests/policy.test.sh"]) == 1
    assert "SARJ304 warning:" not in capsys.readouterr().out


def test_shell_iac_source_rule_runs_when_selected_explicitly(tmp_path: Path) -> None:
    path = tmp_path / "tests" / "policy.test.sh"
    path.parent.mkdir(parents=True)
    path.write_text("grep -q resource iac/main.tf\n", encoding="utf-8")

    findings = textlint.check_paths(
        [str(path)],
        root=tmp_path,
        rule_ids=frozenset({"iac-source-coupled-test"}),
    )

    assert [(finding.line, finding.code) for finding in findings] == [(1, "SARJ304")]


@pytest.mark.parametrize(
    "command",
    [
        "grep -q resource iac/main.tf",
        "rg resource iac/main.hcl",
        "sed -n /resource/p iac/main.tfvars",
        "awk /resource/ iac/main.tf.json",
        "cat iac/main.tf | grep -q resource",
    ],
)
def test_shell_iac_source_rule_flags_direct_labeled_cases(tmp_path: Path, command: str) -> None:
    path = tmp_path / "tests" / "policy.test.sh"
    path.parent.mkdir()
    path.write_text(f"#!/bin/sh\n{command}\n", encoding="utf-8")
    findings = [finding for finding in textlint.check_paths([str(path)], root=tmp_path) if finding.code == "SARJ304"]
    assert [(finding.line, finding.code) for finding in findings] == [(2, "SARJ304")]


def test_shell_iac_source_rule_follows_local_cat_to_assertion_flow(tmp_path: Path) -> None:
    path = tmp_path / "tests" / "policy.test.sh"
    path.parent.mkdir()
    path.write_text(
        '#!/bin/sh\nsource_text="$(cat iac/main.tf)"\n[[ "$source_text" == *resource* ]]\n',
        encoding="utf-8",
    )
    findings = [finding for finding in textlint.check_paths([str(path)], root=tmp_path) if finding.code == "SARJ304"]
    assert [(finding.line, finding.code) for finding in findings] == [(3, "SARJ304")]


@pytest.mark.parametrize(
    "source",
    [
        "terraform show -json plan.out | jq -e '.resource_changes | length > 0'\n",
        "curl -fsS https://service.test/health | jq -e '.healthy == true'\n",
        "grep -q permissions workflow.yml\n",
        "# grep -q resource iac/main.tf\n",
    ],
)
def test_shell_iac_source_rule_allows_structured_runtime_near_misses(tmp_path: Path, source: str) -> None:
    path = tmp_path / "tests" / "policy.test.sh"
    path.parent.mkdir()
    path.write_text(source, encoding="utf-8")
    assert "SARJ304" not in _codes(path, root=tmp_path)


def test_shell_iac_source_rule_ignores_non_test_and_malformed_shell(tmp_path: Path) -> None:
    helper = tmp_path / "scripts" / "deploy.sh"
    helper.parent.mkdir()
    helper.write_text("grep resource iac/main.tf\n", encoding="utf-8")
    malformed = tmp_path / "tests" / "bad.test.sh"
    malformed.parent.mkdir()
    malformed.write_text("grep 'unterminated iac/main.tf\n", encoding="utf-8")
    assert "SARJ304" not in _codes(helper, root=tmp_path)
    assert "SARJ304" not in _codes(malformed, root=tmp_path)


@pytest.mark.parametrize(("substantive", "expected"), [(199, False), (200, True), (201, True)])
def test_large_shell_program_uses_a_fixed_substantive_line_boundary(
    tmp_path: Path, substantive: int, expected: bool
) -> None:
    path = tmp_path / "release.sh"
    path.write_text(
        "#!/bin/sh\n# rationale\n\n" + "run_step\n" * substantive,
        encoding="utf-8",
    )

    findings = [item for item in textlint.check_paths([str(path)], root=tmp_path) if item.code == "SARJ311"]

    assert bool(findings) is expected
    if findings:
        assert findings[0].line == 4
        assert "fully annotated Python" in findings[0].message


def test_large_shell_program_excludes_heredoc_bodies_and_supports_extensionless_shebangs(tmp_path: Path) -> None:
    path = tmp_path / "release"
    path.write_text(
        "#!/usr/bin/env -S bash -eu\ncat <<'FIRST' <<- SECOND\n"
        + "payload\n" * 250
        + "FIRST\n"
        + "\tpayload\n" * 250
        + '\tSECOND\nexec python -m tools.release "$@"\n',
        encoding="utf-8",
    )

    assert textlint.shell_dialect(path) == "bash"
    assert "SARJ311" not in _codes(path, root=tmp_path)


def test_large_shell_program_is_warning_only(tmp_path: Path) -> None:
    path = tmp_path / "release.zsh"
    path.write_text("#!/bin/zsh\n" + "run_step\n" * 200, encoding="utf-8")

    finding = next(item for item in textlint.check_paths([str(path)], root=tmp_path) if item.code == "SARJ311")

    assert " warning:" in finding.render()


def test_registry_exposes_complete_neutral_rule_metadata() -> None:
    assert set(textlint.REGISTRY) == {
        "commented-out-config",
        "config-comment-wall",
        "declarative-deployment-boundary",
        "ephemeral-execution-artifact",
        "exact-config-comment-restatement",
        "hidden-markdown-heading",
        "iac-source-coupled-test",
        "large-shell-program",
        "no-unsafe-command-argument-interpolation",
        "no-wildcard-secret-read-permission",
        "workflow-embedded-program",
    }

    for rule_id, meta in textlint.REGISTRY.items():
        spec = meta.native_spec(rule_id)
        assert spec.key == f"text:{rule_id}"
        assert spec.code == meta.code
        assert spec.summary == meta.description
        assert spec.rationale
        assert spec.remediation
        assert spec.languages
        assert spec.file_patterns
        assert spec.autofix == "none"
        assert spec.message_ids == ()
        assert {example.outcome for example in meta.public_examples} == {"match", "no-match"}


def test_mutable_github_action_is_no_longer_a_textlint_finding(tmp_path: Path) -> None:
    workflow = tmp_path / ".github/workflows/ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "jobs:\n  test:\n    steps:\n      - uses: actions/checkout@v4\n",
        encoding="utf-8",
    )

    assert "SARJ303" not in _codes(workflow, root=tmp_path)


def test_historical_text_aliases_are_documentation_only() -> None:
    aliases = {alias: rule_id for rule_id, meta in textlint.REGISTRY.items() for alias in meta.aliases}

    assert aliases["ephemeral-ai-artifact"] == "ephemeral-execution-artifact"
    assert set(aliases).isdisjoint(textlint.REGISTRY)


def test_rule_examples_are_private_by_default_and_path_safe() -> None:
    source = ExampleFile(path=PurePosixPath("config.toml"), source="enabled = true\n")
    example = RuleExample(
        example_id="private-config",
        title="Private config fixture",
        outcome=ExpectedOutcome.NO_MATCH,
        files=(source,),
        focus_path=source.path,
        expected_count=0,
    )

    assert example.public is False
    with pytest.raises(ValueError, match="safe relative paths"):
        ExampleFile(path=PurePosixPath("../private.toml"), source="enabled = true\n")


@pytest.mark.parametrize("selected_only", [False, True], ids=["all-rules", "selected-rule"])
def test_public_rule_examples_execute_against_the_real_checker(tmp_path: Path, *, selected_only: bool) -> None:
    for rule_id, meta in textlint.REGISTRY.items():
        for example in meta.public_examples:
            root = tmp_path / rule_id / example.example_id
            paths: list[str] = []
            for example_file in example.files:
                path = root / example_file.path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(example_file.source, encoding="utf-8")
                paths.append(str(path))

            findings = textlint.check_paths(paths, root=root, rule_ids=frozenset({rule_id}) if selected_only else None)
            codes = [finding.code for finding in findings]
            expected = [meta.code] * example.expected_count
            assert codes == expected, f"{rule_id}:{example.example_id}"


def test_flags_commented_out_yaml(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yml"
    path.write_text("# timeout-minutes: 30\nname: CI\n")
    assert _codes(path) == ["SARJ301"]


def test_flags_indented_commented_out_yaml(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yml"
    path.write_text("jobs:\n  # timeout-minutes: 30\n  build: {}")
    assert _codes(path) == ["SARJ301"]


@pytest.mark.parametrize(
    ("filename", "comment"),
    [
        ("config.toml", "# timeout = 30\n"),
        ("config.jsonc", "// timeout: 30\n"),
        ("Makefile", "# RELEASE = true\n"),
        ("Dockerfile", "# RUN make build\n"),
    ],
    ids=["toml", "jsonc", "make", "docker"],
)
def test_flags_commented_out_syntax_in_each_supported_config_format(
    tmp_path: Path, filename: str, comment: str
) -> None:
    path = tmp_path / filename
    path.write_text(comment)
    assert _codes(path) == ["SARJ301"]


def test_ignores_documented_config_examples_and_docker_prose(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text("# Default:\n# timeout = 30\ntimeout = 10\n")
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("# Copy workspace files\nCOPY . /app\n")
    assert _codes(config) == []
    assert _codes(dockerfile) == []


def test_protects_config_rationale_and_tool_directives(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yml"
    path.write_text(
        "# yamllint disable rule:line-length\n"
        "# Keep one worker because upstream rejects parallel uploads\n"
        "concurrency: 1\n"
    )
    assert _codes(path) == []


def test_ignores_comments_inside_yaml_block_scalars(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yml"
    path.write_text("script: |\n  # timeout-minutes: 30\n  # retries: 2\nname: CI\n")
    assert _codes(path) == []


def test_collapses_a_commented_out_config_block(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yml"
    path.write_text("# timeout-minutes: 30\n# retries: 2\nname: CI\n")
    assert _codes(path) == ["SARJ301"]


def test_collapses_repeated_config_narration(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yml"
    path.write_text(
        "# Set build name\nname: build\n"
        "# Run build command\nrun: make build\n"
        "# Set deploy image\nimage: app\n"
        "# Run deploy command\ncommand: deploy\n"
    )
    assert _codes(path) == ["SARJ300"]


def test_config_wall_requires_four_attached_comments(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yml"
    path.write_text(
        "# Set build name\nname: build\n# Run build command\nrun: make build\n# Set deploy image\nimage: app\n"
    )
    assert _codes(path) == []


def test_config_wall_requires_three_weak_comments(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yml"
    path.write_text(
        "# Set build name\nname: build\n"
        "# Run build command\nrun: make build\n"
        "# Application lifecycle owner\nimage: app\n"
        "# Deployment entry point\ncommand: deploy\n"
    )
    assert _codes(path) == []


def test_config_wall_requires_75_percent_weak_comments(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yml"
    path.write_text(
        "# Set build name\nname: build\n"
        "# Run build command\nrun: make build\n"
        "# Set deploy image\nimage: app\n"
        "# Deployment entry point\ncommand: deploy\n"
        "# Release lifecycle owner\ntarget: production\n"
    )
    assert _codes(path) == []


def test_config_wall_flags_three_weak_comments_out_of_four(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yml"
    path.write_text(
        "# Set build name\nname: build\n"
        "# Run build command\nrun: make build\n"
        "# Set deploy image\nimage: app\n"
        "# Deployment entry point\ncommand: deploy\n"
    )
    findings = textlint.check_paths([str(path)])
    assert [finding.code for finding in findings] == ["SARJ300"]
    assert "3 narrated entries" in findings[0].message


def test_rationale_comments_count_against_wall_ratio(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yml"
    path.write_text(
        "# Set build name\nname: build\n"
        "# Run build command\nrun: make build\n"
        "# Keep the timeout because upstream can stall\ntimeout: 30\n"
        "# Set deploy image\nimage: app\n"
        "# Run deploy command\ncommand: deploy\n"
        "# Keep one worker because uploads race\nconcurrency: 1\n"
    )
    assert _codes(path) == []


def test_groups_narration_across_multiline_sibling_entries(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yml"
    path.write_text(
        "# Set build job\n"
        "build_job:\n  image: node\n  script:\n    - npm ci\n    - npm build\n"
        "# Set test job\n"
        "test_job:\n  image: node\n  script:\n    - npm test\n"
        "# Set deploy job\n"
        "deploy_job:\n  image: node\n  script:\n    - npm deploy\n"
        "# Set publish job\n"
        "publish_job:\n  image: node\n  script:\n    - npm publish\n"
    )
    assert _codes(path) == ["SARJ300"]


def test_config_wall_requires_comments_attached_to_entries(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yml"
    path.write_text(
        "# Set build name\n\nname: build\n"
        "# Run build command\n\nrun: make build\n"
        "# Set deploy image\n\nimage: app\n"
        "# Run deploy command\n\ncommand: deploy\n"
    )
    assert _codes(path) == []


def test_config_wall_does_not_combine_different_indentation_levels(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yml"
    path.write_text(
        "# Set build name\nname: build\n"
        "# Run build command\nrun: make build\n"
        "  # Set deploy image\n  image: app\n"
        "  # Run deploy command\n  command: deploy\n"
    )
    assert _codes(path) == []


@pytest.mark.parametrize(
    "protected_comment",
    [
        "# yamllint disable rule:line-length",
        "# See RFC 9110 for retry semantics",
        "# Keep one worker because uploads are serialized",
        "# Invariant: the deployment name is immutable",
        "# The timeout is 30 sec",
        "# Compatibility with legacy runners",
        "# Upstream rejects parallel uploads",
    ],
    ids=["directive", "reference", "rationale", "invariant", "unit", "compatibility", "upstream"],
)
def test_config_wall_protects_high_signal_comments(tmp_path: Path, protected_comment: str) -> None:
    path = tmp_path / "workflow.yml"
    path.write_text(
        "# Set build name\nname: build\n"
        "# Run build command\nrun: make build\n"
        "# Application lifecycle owner\nimage: app\n"
        f"{protected_comment}\ncommand: deploy\n"
    )
    assert _codes(path) == []


def test_flags_jsonc_block_comment_and_toml_section(tmp_path: Path) -> None:
    jsonc = tmp_path / "settings.jsonc"
    jsonc.write_text('/* "debug": true */\n{}\n')
    toml = tmp_path / "settings.toml"
    toml.write_text("# [debug]\n# enabled = true\n")
    assert _codes(jsonc) == ["SARJ301"]
    assert _codes(toml) == ["SARJ301"]


def test_manifest_can_exclude_documented_template_config(tmp_path: Path) -> None:
    (tmp_path / ".sarj-standards.toml").write_text('[text]\nexclude = ["templates/**"]\n')
    templates = tmp_path / "templates"
    templates.mkdir()
    config = templates / "values.yaml"
    config.write_text("# timeout: 30\n# retries: 2\n")
    assert _codes(config, root=tmp_path) == []


def test_manifest_exclusion_applies_to_artifact_findings(tmp_path: Path) -> None:
    manifest = tmp_path / ".sarj-standards.toml"
    manifest.write_text('[text]\nexclude = ["docs/backups/**"]\n', encoding="utf-8")
    artifact = tmp_path / "docs" / "backups" / "README.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("# Archived operational reference\n", encoding="utf-8")

    assert _codes(artifact, root=tmp_path) == []


def test_manifest_is_read_once_per_textlint_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    manifest = tmp_path / ".sarj-standards.toml"
    manifest.write_text('[artifacts]\ndurable = ["docs/**"]\n[text]\nexclude = ["templates/**"]\n')
    config = tmp_path / "values.yaml"
    config.write_text("enabled: true\n")
    real_read_text = Path.read_text
    manifest_reads = 0

    def recording_read_text(path: Path, *args: object, **kwargs: object) -> str:
        nonlocal manifest_reads
        if path == manifest:
            manifest_reads += 1
        return real_read_text(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", recording_read_text)

    assert textlint.check_paths([str(config)], root=tmp_path) == []
    assert manifest_reads == 1


@pytest.mark.parametrize(
    "filename",
    ["FIX-BRIEF-V3.md", "diagnosis-handoff.md", "project-status.md", "qa-fixlist.md"],
    ids=["brief", "handoff", "status", "qa"],
)
def test_flags_named_ai_execution_artifacts(tmp_path: Path, filename: str) -> None:
    path = tmp_path / filename
    path.write_text("# Temporary execution record\n")
    assert _codes(path, root=tmp_path) == ["SARJ302"]


def test_new_artifact_rule_blocks(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    path = tmp_path / "FIX-BRIEF.md"
    path.write_text("# Temporary execution record\n")

    assert textlint.run([str(path)]) == 1
    assert "SARJ302 warning:" not in capsys.readouterr().out


def test_markdown_artifact_suppression_is_exact_code_specific(tmp_path: Path) -> None:
    path = tmp_path / "FIX-BRIEF.md"
    path.write_text("<!-- sarj-noqa: SARJ302 -->\n# Preserved external artifact\n", encoding="utf-8")
    assert _codes(path, root=tmp_path) == []

    path.write_text("<!-- sarj-noqa: SARJ301 -->\n# Temporary execution record\n", encoding="utf-8")
    assert _codes(path, root=tmp_path) == ["SARJ302"]


def test_hidden_markdown_heading_suppression_is_exact_code_specific(tmp_path: Path) -> None:
    path = tmp_path / "README.md"
    hidden = "<!-- ## Retired setup -->\n"
    path.write_text(f"<!-- sarj-noqa: SARJ305 -->\n{hidden}", encoding="utf-8")
    assert _codes(path, root=tmp_path) == []

    path.write_text(f"<!-- sarj-noqa: SARJ302 -->\n{hidden}", encoding="utf-8")
    assert _codes(path, root=tmp_path) == ["SARJ305"]


def test_hidden_markdown_heading_suppression_is_local(tmp_path: Path) -> None:
    path = tmp_path / "README.md"
    path.write_text(
        "<!-- sarj-noqa: SARJ305 -->\n<!-- ## Preserved setup -->\n\n<!-- ## Stale setup -->\n",
        encoding="utf-8",
    )
    assert _codes(path, root=tmp_path) == ["SARJ305"]


def test_exact_config_restatement_suppression_is_local_and_code_specific(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    restatement = "# Retry count is 3\nretry_count = 3\n"
    path.write_text(f"# sarj-noqa: SARJ306\n{restatement}", encoding="utf-8")
    assert _codes(path, root=tmp_path) == []

    path.write_text(f"# sarj-noqa: SARJ301\n{restatement}", encoding="utf-8")
    assert _codes(path, root=tmp_path) == ["SARJ306"]


@pytest.mark.parametrize(
    ("comment", "entry"),
    [
        ("# Retry count is 3", "retry_count = -3"),
        ("# Endpoint is api-v1", 'endpoint = "api_v1"'),
    ],
)
def test_exact_config_restatement_preserves_scalar_punctuation(tmp_path: Path, comment: str, entry: str) -> None:
    path = tmp_path / "config.toml"
    path.write_text(f"{comment}\n{entry}\n", encoding="utf-8")
    assert _codes(path, root=tmp_path) == []


def test_comment_reduction_rules_block(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    markdown = tmp_path / "README.md"
    markdown.write_text("<!-- ## Retired setup -->\n", encoding="utf-8")
    config = tmp_path / "config.toml"
    config.write_text("# Retry count is 3\nretry_count = 3\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert textlint.run([markdown.name, config.name]) == 1
    output = capsys.readouterr().out
    assert "SARJ305 " in output
    assert "SARJ306 " in output
    assert "warning:" not in output


def test_exact_restatements_take_precedence_over_generic_comment_wall(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "# Build name is build\nbuild_name: build\n"
        "# Test name is test\ntest_name: test\n"
        "# Deploy name is deploy\ndeploy_name: deploy\n"
        "# Publish name is publish\npublish_name: publish\n",
        encoding="utf-8",
    )

    assert _codes(path, root=tmp_path) == ["SARJ306", "SARJ306", "SARJ306", "SARJ306"]


@pytest.mark.parametrize(
    "example",
    [
        "```markdown\n<!-- sarj-noqa: SARJ302 -->\n```",
        "    <!-- sarj-noqa: SARJ302 -->",
        "`<!-- sarj-noqa: SARJ302 -->`",
    ],
)
def test_markdown_suppression_examples_do_not_suppress_real_findings(tmp_path: Path, example: str) -> None:
    path = tmp_path / "FIX-BRIEF.md"
    path.write_text(f"{example}\n# Temporary execution record\n", encoding="utf-8")

    assert _codes(path, root=tmp_path) == ["SARJ302"]


def test_established_text_rules_remain_blocking(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("# timeout = 30\n")

    assert textlint.run([str(path)]) == 1


def test_flags_change_diary_inside_readme(tmp_path: Path) -> None:
    path = tmp_path / "README.md"
    path.write_text("# App\n\n## Fixes + learnings\n\n## Verification passes\n")
    assert _codes(path, root=tmp_path) == ["SARJ302"]


@pytest.mark.parametrize(
    "heading",
    ["Verification pass", "Verification passes", "QA pass", "Implementation status", "Session summary"],
    ids=["verification", "verification-plural", "qa", "implementation-status", "session-status"],
)
def test_flags_repeated_execution_log_headings(tmp_path: Path, heading: str) -> None:
    path = tmp_path / "notes.md"
    path.write_text(f"# Work\n\n## {heading}\n\n## {heading}\n")
    assert _codes(path, root=tmp_path) == ["SARJ302"]


def test_allows_durable_docs_and_single_verification_section(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    path = docs / "operations.md"
    path.write_text("# Operations\n\n## Verification\nRun `make verify`.\n")
    assert _codes(path, root=tmp_path) == []


@pytest.mark.parametrize(
    "relative",
    [
        "README.md",
        "CHANGELOG.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "AGENTS.md",
        "CLAUDE.md",
        ".github/policy.md",
        "architecture/system.md",
        "adr/001-decision.md",
    ],
    ids=[
        "readme",
        "changelog",
        "contributing",
        "security",
        "agents",
        "claude",
        "github",
        "architecture",
        "adr",
    ],
)
def test_allows_durable_markdown_locations(tmp_path: Path, relative: str) -> None:
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Current design\n")
    assert _codes(path, root=tmp_path) == []


def test_changelog_issue_heading_is_durable(tmp_path: Path) -> None:
    path = tmp_path / "CHANGELOG.md"
    path.write_text("# Changelog\n\n## Issues fixed\n\n- Corrected retry behavior.\n")
    assert _codes(path, root=tmp_path) == []


@pytest.mark.parametrize(
    "filename",
    ["Dockerfile.nginx", "workflow.yaml.tftpl", "settings.ini", ".env.example", "Justfile"],
)
def test_extended_text_file_routing(filename: str) -> None:
    assert textlint.is_text_path(Path(filename))


def test_manifest_can_allow_a_durable_research_report(tmp_path: Path) -> None:
    (tmp_path / ".sarj-standards.toml").write_text('[artifacts]\ndurable = ["evidence/**"]\n')
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    report = evidence / "research-report.md"
    report.write_text("# Reproducible benchmark evidence\n")
    assert _codes(report, root=tmp_path) == []


@pytest.mark.parametrize(
    ("filename", "heading"),
    [("FIX-BRIEF.md", "# Fix brief\n"), ("END-TO-END-PLAN.md", "# End-to-end plan\n")],
    ids=["fix-brief", "end-to-end-plan"],
)
def test_durable_directory_does_not_hide_execution_artifacts(tmp_path: Path, filename: str, heading: str) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    artifact = docs / filename
    artifact.write_text(heading)
    assert _codes(artifact, root=tmp_path) == ["SARJ302"]


def test_flags_strong_change_diary_heading_without_a_second_heading(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text("# App\n\n## What changed this session\n")
    assert _codes(readme, root=tmp_path) == ["SARJ302"]


def test_markdown_fences_do_not_create_artifact_headings(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(
        "# CLI\n\n```markdown\n## Fixes + learnings\n## Verification passes\n```\n",
        encoding="utf-8",
    )

    assert _codes(readme, root=tmp_path) == []


def test_tilde_markdown_fences_do_not_create_artifact_headings(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(
        "# CLI\n\n~~~markdown\n## Fixes + learnings\n## Verification passes\n~~~\n",
        encoding="utf-8",
    )

    assert _codes(readme, root=tmp_path) == []


def test_long_markdown_fence_is_not_closed_by_a_shorter_example_fence(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(
        "# CLI\n\n````markdown\n```markdown\n## Fixes + learnings\n## Verification passes\n```\n````\n",
        encoding="utf-8",
    )

    assert _codes(readme, root=tmp_path) == []


def test_indented_markdown_code_does_not_create_artifact_headings(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(
        "# CLI\n\n    ## Fixes + learnings\n    ## Verification passes\n",
        encoding="utf-8",
    )

    assert _codes(readme, root=tmp_path) == []


def test_matching_sarj_suppression_is_code_specific(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text("# sarj-noqa: SARJ301\n# timeout = 30\n", encoding="utf-8")
    assert _codes(config) == []

    config.write_text("# sarj-noqa: SARJ999\n# timeout = 30\n", encoding="utf-8")
    assert _codes(config) == ["SARJ301"]


def test_custom_durable_paths_extend_builtin_locations(tmp_path: Path) -> None:
    (tmp_path / ".sarj-standards.toml").write_text('[artifacts]\ndurable = ["evidence/**"]\n', encoding="utf-8")
    docs = tmp_path / "docs"
    docs.mkdir()
    report = docs / "architecture-report.md"
    report.write_text("# Maintained architecture\n", encoding="utf-8")

    assert _codes(report, root=tmp_path) == []


def test_flags_large_dated_audit_inside_docs(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    audit = docs / "pagerduty-audit-2026-08.md"
    audit.write_text(
        "# PagerDuty audit — 2026-08-04\n\n"
        "## Inventory\n\n| Object | Count |\n| --- | --- |\n| Services | 4 |\n\n"
        "## Findings\n\n**1. Stale rotation.** Remove it.\n\n"
        "## What was actually changed\n\nThe rotation was replaced.\n\n"
        "## Recommended order of work\n\n1. Remove the stale rotation.\n\n"
        "## Post-change verification\n\nThe API returned the expected state.\n\n"
        + "Evidence captured during the audit.\n"
        * 180
    )
    assert _codes(audit, root=tmp_path) == ["SARJ302"]


def test_large_architecture_reference_is_not_an_execution_artifact(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    architecture = docs / "ARCHITECTURE.md"
    architecture.write_text(
        "# Architecture\n\n## Components\n\nThe API accepts requests and publishes domain events.\n\n"
        + "### Service contract\n\nEach consumer processes one versioned event schema.\n\n" * 80
    )
    assert _codes(architecture, root=tmp_path) == []


def test_large_document_needs_multiple_artifact_signals(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    operations = docs / "operations-2026-08.md"
    operations.write_text("# Operations\n\n## Inventory\n\n" + "Current service fact.\n" * 210)
    assert _codes(operations, root=tmp_path) == []


def test_large_design_findings_and_actions_need_artifact_provenance(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    design = docs / "database-design.md"
    design.write_text(
        "# Database design\n\n## Findings\n\n1. Writes need stable keys.\n2. Reads need an index.\n\n"
        "## Action Items\n\nAdd the index during implementation.\n\n"
        + "The maintained design explains a durable constraint.\n"
        * 200
    )
    assert _codes(design, root=tmp_path) == []


@pytest.mark.parametrize(
    "filename",
    ["BUGS-FOUND.md", "bugs_found.md", "bugs-found-fe.md"],
)
def test_flags_bug_hunt_artifacts_even_in_durable_locations(tmp_path: Path, filename: str) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    report = docs / filename
    report.write_text("# Bugs found during the testing initiative\n")
    assert _codes(report, root=tmp_path) == ["SARJ302"]


@pytest.mark.parametrize(
    "filename",
    ["bugs-foundation.md", "ladybugs-found.md", "debugs-foundation.md"],
)
def test_bug_hunt_name_requires_complete_filename_tokens(tmp_path: Path, filename: str) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    document = docs / filename
    document.write_text("# Maintained reference\n")
    assert _codes(document, root=tmp_path) == []
