#!/usr/bin/env bash
set -euo pipefail
title="[Standards rollout] $VERSION"
log="$RUNNER_TEMP/standards-rollout.log"
body="$RUNNER_TEMP/standards-rollout-issue.md"
issues="$(gh issue list --repo "$GITHUB_REPOSITORY" --state all --limit 100 --json number,title,state)"
issue_number="$(jq -r --arg title "$title" '[.[] | select(.title == $title)][0].number // empty' <<<"$issues")"
issue_state="$(jq -r --arg title "$title" '[.[] | select(.title == $title)][0].state // empty' <<<"$issues")"

# The backticks below are intentional Markdown literals.
# shellcheck disable=SC2016
{
  printf 'Automated rollout of `code-standards==%s` is **%s**.\n\n' "$VERSION" "$RESULT"
  printf -- '- Workflow: %s\n' "$GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID"
  printf -- '- Operation exit status: `%s`\n' "$OPERATION_STATUS"
  printf -- '- Fleet status exit status: `%s`\n\n' "$STATUS_STATUS"
  printf '```text\n'
  tail -c 40000 "$log"
  printf '\n```\n'
} >"$body"
cat "$body" >>"$GITHUB_STEP_SUMMARY"

if [[ "$RESULT" == success && "$STATUS_STATUS" == 0 ]]; then
  if [[ -n "$issue_number" ]]; then
    gh issue edit "$issue_number" --repo "$GITHUB_REPOSITORY" --body-file "$body"
    if [[ "$issue_state" == OPEN ]]; then
      gh issue comment "$issue_number" --repo "$GITHUB_REPOSITORY" \
        --body "Every registered consumer has adopted the release in run $GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID."
      gh issue close "$issue_number" --repo "$GITHUB_REPOSITORY" --reason completed
    fi
  fi
elif [[ -n "$issue_number" ]]; then
  gh issue edit "$issue_number" --repo "$GITHUB_REPOSITORY" --body-file "$body"
  if [[ "$issue_state" == CLOSED ]]; then
    gh issue reopen "$issue_number" --repo "$GITHUB_REPOSITORY"
  fi
else
  gh issue create --repo "$GITHUB_REPOSITORY" --title "$title" --body-file "$body"
fi
