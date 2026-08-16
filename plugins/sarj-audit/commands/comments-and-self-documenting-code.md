# Comments and self-documenting code

Audit comments and docstrings for information the code and types cannot carry
using the shared [audit protocol](../skills/audit-protocol/SKILL.md#audit-protocol).
Run deterministic comment/docstring rules first and do not duplicate them.

## Valuable comments

Keep prose that records at least one hidden fact:

- a causal invariant or failure mechanism;
- an external protocol, runtime, security, privacy, or compatibility constraint;
- why ordering, timing, locking, or a particular observation point matters;
- cross-system coordination, with the executable parity check or canonical
  source named;
- a scoped lint/type suppression whose concrete mismatch and safety invariant
  are auditable.

## Findings

Report confirmed cases where prose:

- restates the adjacent identifier, assertion, branch, literal, or test name;
- narrates history (`fixed`, `regression`, `wave`, `future lane`) without a
  current invariant that still constrains the code;
- copies the same explanation beside sibling tests instead of naming one shared
  contract/helper;
- says `must match`, `mirrors`, or `stay in sync` while no generator, shared
  source, or executable drift test enforces the relationship;
- uses a ticket ID, urgency word, or generic suppression phrase as a substitute
  for the reason.

Ticket/spec references are not violations by themselves. Preserve them when
they locate an external constraint or explain why the current non-obvious code
must remain. Likewise, do not flag causal/counterfactual explanations merely
because they sit next to an assertion.

## Remediation and reporting

Delete pure restatement/history. Prefer a name, type, helper, named constant, or
executable parity test when it can carry the fact. Otherwise retain one local
sentence describing the hidden invariant. Each finding must quote only the
minimum evidence, explain the drift/maintenance impact, and identify the
smallest credible remediation.
