# SARJ085 `redundant-class-docstring` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_redundant_class_docstring.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

    @dataclass
    class ShipmentCreateData:
        """Data for creating a shipment."""

        origin: str
        weight_kg: Decimal

Every content word is already in `class ShipmentCreateData`. SARJ050 makes this
judgement for functions and never sees a class: its walker recurses *through* a
`ClassDef` to reach the methods and inspects the class's own docstring nowhere.
That blind spot is this rule.

**The fix is to delete the docstring.** A class with none is clean under this
repo's strict ruff config (D101 is off), and there is no `Returns:`/`Raises:`
analogue left stranded by the deletion.

**Never flagged**

- **Anything whose docstring becomes a published schema description.** This is
  the largest exemption and it decides most of the corpus. A pydantic model's
  class docstring is emitted as its JSON-Schema `description` — verified
  directly, not assumed:

      class ShipmentResponse(pydantic.BaseModel):
          """Shipment response."""
          tracking_id: str

      >>> ShipmentResponse.model_json_schema()["description"]
      'Shipment response.'

  FastAPI publishes that string in `/openapi.json`, and an LLM tool or
  structured-output schema built from the same model ships it to the model. The
  identical thing happens to an `Enum` subclass and to a `TypedDict` pydantic
  validates. Deleting the text edits an artefact someone else reads — the same
  argument SARJ050 makes for `@function_tool` and route handlers, and the same
  hard exemption. It costs **28 of the 34** otherwise-flaggable first-party
  findings, every one a request/response model, a status `StrEnum`, or a
  `TypedDict` result. Recall is not the thing to optimise when the failure mode
  is silently rewriting an API document.
- **A class whose body IS the docstring** — the whole exception-class idiom.
  Deleting it leaves an empty suite, so the advice would not compile. (A class
  that writes `pass` after the docstring keeps compiling and stays flagged;
  `django/django/contrib/sessions/exceptions.py:17` is that shape.)
- **Value markers and the nine-signal protected class** from `_comments`, so a
  one-line class docstring carrying a URL, an RFC, a status code, a unit or a
  causal connective stays.
- **Prompt / CLI / route decorators**, and the schema decorators
  (`@pydantic.dataclasses.dataclass`, `@strawberry.type`) that place a
  docstring in a schema the way a `BaseModel` base does.
- **Generated code.**
- **Base class names count as signature.** `class NotRegistered(KeyError, TaskError)`
  reads "The task is not registered" as a restatement, because every content
  word — including the `not` that the comment rules treat as a stopword and this
  family deliberately does not — is spelled in the class name or a base. A base
  that contributes a genuinely new word protects the docstring instead: under
  `class Handler(RetryPolicy)`, "retry" and "policy" are free, and anything else
  is not.

**Measured.** 34 of 1,147 first-party class docstrings (3.0%) restate their own
name. After the schema exemption **6** remain, and all 6 were read: **6 true
positives, 0 false** — four `TestX` classes documented as "Tests for X", two
plain `@dataclass` data holders.

Over 14 OSS repos the predicate finds **536** (airflow 192, prefect 108,
litellm 104, langchain 84, superset 80, django 20, dagster 17, saleor 13, celery
6, warehouse 6, mlflow 4, sentry-python 2, fastapi/zulip 0). 30 were sampled
across six of them and read: **30 true positives, 0 false**, e.g.
`celery/celery/utils/collections.py:766` ("Map of buffers." on `class BufferMap`),
`superset/superset/db_engine_specs/firebird.py:28` ("Engine for Firebird"),
`saleor/saleor/graphql/attribute/utils/type_handlers.py:678` ("Handler for Rich
Text attribute type."), `django/tests/gis_tests/test_measure.py:13` ("Testing the
Distance object"). The volume is in libraries because their model and enum
modules — the shapes first-party code writes most — are what the schema
exemption removes here.

This ships as a low-volume ratchet for first-party code, deliberately. The
precedent is SARJ051, which ships with zero Python findings: a rule that holds a
line the corpus has mostly cleared is still worth the code when it has no
failure mode surviving its exemptions.

Suppress an intentional case with `# sarj-noqa: SARJ085 — <reason>`.
