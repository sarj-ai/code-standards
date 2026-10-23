# Test judgment

- Oracles must independently reject a plausible wrong result; deliberate registry
  exhaustiveness is an exception. Scalar `pytest.approx` can broadcast NumPy
  arrays; assert promised shape separately.
- Start negative cases valid with one fault unless interaction/precedence matters.
  Keep tables sparse after paths rejoin.
- Prefer native schema/build/smoke checks. Source assertions need a reviewed
  security, packaging or compatibility contract.
- Test the claimed boundary: fakes prove orchestration, not SQL/commit visibility
  or collaborator behavior. Freshly read durable effects; check rejection absence,
  rollback after an effect and retry multiplicity where promised. Wire claims
  need transport.
- Compare fixture visibility/configuration/fidelity/isolation/cleanup. Reuse must
  not precompute action/oracle; cleanup covers partial setup/teardown failure;
  async resources retain their loop.
- Remove inactive fixtures only after complete owned runs across supported
  profiles with `pytest-unused-fixtures==0.3.1 --unused-fixtures -v`. Check
  autouse, indirect/dynamic requests, dependencies and plugin registration.
  Focused/skipped/sharded runs are inconclusive. The observer's BasedPyright
  `reportUnusedFunction` is advisory for private helpers.
- Preserve invocation-time mock values despite later mutation, identity/noncopyable
  contracts, framework overrides, async/hoisting/order ownership and restoration.
  Replacing `vi.stubEnv` with assignment loses restoration tracking.

Equal current results or coverage do not prove equivalent failure detection.
