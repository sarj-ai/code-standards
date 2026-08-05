# Client/server boundary

Audit misplaced work across client, server, and database layers using the shared [audit protocol](../README.md#audit-protocol).

## Judgment checks

- Data loading, authorization, secret-bearing work, or stable computation performed in client code when the framework supports a server boundary.
- Large uploads proxied through application memory when a secure direct-upload flow is available.
- Filtering, aggregation, pagination, or atomic updates performed in application code when the database can do them more safely and efficiently.
- Business rules hidden in presentation components or SQL when they belong in an explicit service/domain boundary.

Do not recommend server components, server actions, or SQL movement unless the detected framework and datastore support them and the move improves security, correctness, or measured performance.
