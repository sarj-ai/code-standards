# Client/server boundary

Use the [audit protocol](../skills/audit-protocol/SKILL.md).

Review remaining boundary mistakes: secret-bearing or privileged client work,
large uploads unnecessarily buffered by the application, database-suitable
filtering/aggregation and policy hidden in presentation. Recommend movement only
when the detected framework/datastore supports it and security, correctness or
measured cost improves; preserve access and transaction contracts.
