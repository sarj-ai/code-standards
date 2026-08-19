# Slack automations

Audit Slack bots and non-bot integrations using the shared
[audit protocol](../skills/audit-protocol/SKILL.md#audit-protocol). Run the
repository's Slack-automation catalog validator first when a catalog is present;
do not repeat deterministic schema, uniqueness, path, or public-field findings.

## Discover

Inventory Slack app manifests, token/configuration boundaries, OAuth scopes,
events, slash commands, interactive handlers, scheduled jobs, queues, and Slack
API clients. Map each installed app or token family to its runtime entry points,
personas, capabilities, and catalog record. Treat user-token workflows and
workspace administration as integrations, not bot identities.

Trace framework middleware and shared adapters before judging a handler in
isolation. Exclude generated manifests and catalog artifacts from prose review,
but compare them with their source-owned definitions and deployed runtime.

## Judgment checks

- **Complete inventory** — Every live Slack credential family and automation has
  exactly one catalog record, and every cataloged capability resolves to
  reachable source.
  Flag stale entries, shadow bots, and Slack side effects hidden inside a generic
  job. Do not infer deployment merely from a historical manifest or unused token
  name.
- **Identity and persona accuracy** — Installed app identities, presentation
  personas, and capabilities are modeled separately. A shared bot may expose
  several personas, but the catalog must not present those personas as separately
  installed apps or merge unrelated token families into one identity.
- **Least privilege** — Bot and user tokens use the narrowest token kind and OAuth
  scopes justified by reachable capabilities. Mutating or administrative methods
  are not available through a broader shared client merely for convenience.
  Confirm manifest, installation, and runtime behavior before reporting drift.
- **Trusted ingress** — HTTP events, commands, actions, and shortcuts verify Slack
  signatures against the raw request body and reject stale timestamps before
  parsing or dispatch. Socket Mode and framework-provided verification are valid
  when the trusted boundary is established.
- **Acknowledgement and failure behavior** — Interactive Slack traffic is
  acknowledged within Slack's deadline, while slow or failure-prone work crosses
  a durable asynchronous boundary. Acknowledgement does not silently convert a
  failed operation into success; operators and users receive an appropriate
  terminal outcome.
- **Retries and side effects** — Slack retry identifiers, event IDs, trigger IDs,
  or domain idempotency keys reach durable deduplication before messages,
  reactions, invitations, profile changes, or external writes occur. Process-local
  memory is insufficient across isolates or replicas. Multi-step mutations expose
  no unsafe partial state when a retry starts after interruption.
- **Authorization and audience** — User-initiated actions derive the actor,
  workspace, channel, and conversation context from verified Slack payloads and
  re-check required role or membership server-side. Scheduled and administrative
  workflows cannot be invoked through an unprotected alternate route.
- **Catalog exposure safety** — Human-readable summaries and trigger descriptions
  do not reveal credentials, secret-variable names, private channel or user IDs,
  internal administrative routes, customer data, or operational details that
  would make an authenticated catalog unnecessarily sensitive.
- **Executable parity** — Source-owned catalog definitions, Slack manifests, and
  runtime registration share a generator or complete drift test for identity,
  scopes, events, commands, and source paths. A comment saying values must stay in
  sync is not an enforcement mechanism.

Apply only checks supported by the detected transport and automation type. For
example, do not require HTTP signature verification for Socket Mode, bot scopes
for a user-token integration, or a separate app for each persona.

## Report

For each finding, name the installed identity or integration, the catalog and
runtime evidence compared, user or operational impact, and the smallest credible
remediation. Cite the supporting deterministic rule or tool when one exists;
otherwise mark it `judgment-only`. When no findings remain, list the credential
families, manifests, runtime entry points, and catalog records examined.
