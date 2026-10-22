# Test judgment

- Name the smallest wrong result or production mutation the oracle rejects.
  Expected values must be independent of the implementation, except deliberate
  enum/registry exhaustiveness. Preserve narrow smoke and shape contracts.
  Scalar `pytest.approx` can broadcast NumPy arrays; assert promised shape separately.
- Start negative cases from valid input with one fault unless interaction or
  rejection precedence is the contract. Keep tables sparse after paths rejoin.
- Use native syntax, schema, build and smoke checks before adding operational
  tests. A source/representation assertion earns its place only when reviewed
  bytes are themselves a security, packaging or compatibility contract.
- Exercise the claimed boundary: fake persistence proves orchestration, not SQL
  or commit visibility. Read durable changes freshly; observe absent effects on
  rejection, rollback after a first effect, and multiplicity after retries when
  those are the affected promises. Wire claims need the transport adapter.
- Compare fixture providers by visibility, configuration, fidelity, isolation and
  cleanup ownership. Reuse must not precompute the action or oracle. Cleanup
  covers setup failure and independent teardown failures; async resources remain
  within their owning loop. Preserve framework overrides and dynamic requests.
- Fixture inactivity requires complete owned pytest runs across supported
  profiles with `pytest-unused-fixtures==0.3.1 --unused-fixtures -v`, bounded to
  authored support. Focused, skipped, sharded or unavailable runs are inconclusive.
  Check autouse, indirect/usefixtures, dynamic requests, dependencies and plugin
  registration before removal. Private helpers can use the observer's advisory
  BasedPyright `reportUnusedFunction` in existing test execution environments.
- Preserve invocation-time values when mock history aliases later mutation;
  preserve intentional identity/noncopyable contracts. A fake's state transition
  cannot prove the real collaborator performs it.
- Maintain async ownership, hoisting, restoration and ordering when simplifying
  setup. A grouping loop is useful only when clearer; replacing `vi.stubEnv` with
  direct environment assignment loses restoration tracking. Verify promise-chain
  ownership before acting on advisory upstream findings.

After a proposed reduction, verify the retained oracle still rejects the wrong
outcome. Equal coverage or equal current results alone does not prove equivalence.
