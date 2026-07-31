# SARJ006 `prefer-str-enum` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_prefer_str_enum.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

`Literal["a", "b", "c"]` is acceptable — that's a proper closed set. After a
real-world sweep (Flask, requests, httpx, FastAPI, Django) the rule was tightened
to two corroborated triggers only:

1. **Sibling choices attribute** — a class with a string-collection attribute
   named `choices`/`states`/`statuses`/`values`/`allowed` flags its raw-`str`
   fields (the collection is the enum that should exist). A bare `status: str`
   with no such corroboration does NOT fire: a field name alone is too weak a
   signal (a free-form HTTP `status` string is still `str`).
2. **Equality comparison cluster** — within one function, the same *plain
   variable* (not an attribute of a value the module doesn't own) is compared
   with `==`/`!=` (or matched with `case`) against 2+ distinct short lowercase
   string literals. A lone `x in {...}` / `x not in {...}` membership test is
   NOT enough on its own — it is usually a guard over an external vocabulary
   (URL schemes, file modes, reflection keys), not an app-owned enum. A field
   whose name matches such a cluster is corroborated and also flagged.

   The 2+ literals must be enumerated by ONE operator (`x == "a" ... elif
   x == "b"`, or `x != "a" and x != "b"`), optionally corroborated by a
   membership set over the same variable (`assert x in ("a", "b")` next to
   `if x == "a"`). `==` and `!=` literals are never summed with each other: an
   `x == "a"` plus `x != "b"` pair is two independent guards, not a dispatch
   over a domain. Four of the famous-repo sweep's 31 hits were that pair
   (`fastapi/docs_src/dependencies/tutorial008c_py310.py:19` and its three
   siblings: `if item_id == "laser-gun": ... if item_id != "plumbus": ...`).

Deliberately NOT flagged (real-world false positives the sweep surfaced):
- Attribute comparands whose root the module does not own (`url.scheme`,
  `field.mode`, `self.__dict__` reflection keys) — you cannot turn someone
  else's attribute into a StrEnum.
- Lone membership guards over external vocabularies.
- Single-character tokenizer scans (`last_char == "g"`) and language-keyword
  tokenizers (`token in ("is", "not", "in")`).
- Variables that are already a closed `Literal` — either annotated inline
  (`x: Literal["a", "b"]`) or via a module-level alias (`Mode = Literal[...]`;
  `x: Mode`), or whose compared literals are all members of such an in-module
  alias (Rich's `align = self.align` where `AlignMethod = Literal[...]`). The
  closed set already exists; recommending a StrEnum is redundant.
- Open-domain code variables (`language`, `country`, `currency`, `timezone`,
  `locale`, `region`, `code`, ...): special-casing a few ISO codes is not a
  closed enum.
- Variables bound from a subscript or `.get(...)` lookup in the same function
  (`schema_type = schema['type']`, `extra = cfg.get('behavior')`): the value
  comes off a dict-shaped wire format owned by someone else (pydantic-core
  schemas were the motivating sweep case) — you cannot impose a StrEnum on
  another system's payload keys.

The famous-repo sweep (31 hits over fastapi / pydantic / rich / flask / black)
retired four more classes, all of them "the domain is not this comparison's to
define":

- **Separately-typed variables.** Anything annotated with a named type other
  than `str` — `justify: JustifyMethod` (`rich/rich/containers.py:129`),
  `align: AlignMethod` (`rich/rich/text.py:955`),
  `vertical: VerticalAlignMethod` (`rich/rich/table.py:859`),
  `mode: FieldValidatorModes` (`pydantic/pydantic/_internal/_decorators.py:563`).
  All four are `Literal` aliases the rule cannot see, because they are declared
  in the module that owns them and imported here; what it CAN see is that the
  domain already has a name and a definition site. Opacity propagates through
  assignment, so `_overflow = overflow or self.overflow or DEFAULT_OVERFLOW`
  (`rich/rich/text.py:874`) is opaque too. Same for a local bound from a
  same-module function that returns a `Literal`
  (`pydantic/pydantic/_internal/_generate_schema.py:2833`).
- **Foreign reads, extended to loops and attributes.** The direct form
  (`token.type == "text"`) never fired; binding it to a local first must not
  change the answer. So `node_type = token.type` (`rich/rich/markdown.py:605`),
  `v = leaf.value` (`black/src/black/nodes.py:940`),
  `copy_on_model_validation = cls.__config__.copy_on_model_validation`
  (`pydantic/pydantic/v1/main.py:711`, a chain that has left `self`),
  `event = os.getenv("GITHUB_EVENT_NAME")`
  (`black/scripts/diff_shades_gha_helper.py:125`), `word = next(words, "")`
  (`rich/rich/style.py:522`, a token scan) and every `for` target over somebody
  else's mapping or attribute — `for k, v in obj.items()`
  (`pydantic/pydantic/_internal/_core_utils.py:117`), `for ann_name, _ in
  type_hints.items()` (`.../_fields.py:273`), `for arg, name in zip(expr.args,
  expr.arg_names)` (`pydantic/pydantic/mypy.py:1096`,
  `pydantic/pydantic/v1/mypy.py:616`), `for field in sorted(node._fields)`
  (`black/src/black/parsing.py:218`) — are all reflection over an external
  vocabulary.
- **`open()` modes.** A variable named `mode` / `_mode` / `*_mode` compared only
  against 1-3 characters drawn from `rwxab+t` is the stdlib file-mode
  vocabulary (`flask/src/flask/app.py:437`,
  `flask/src/flask/blueprints.py:120`, `rich/rich/progress.py:1345`). Matching
  on the name AND the shape keeps single-character enums elsewhere
  (`grade == "a"` / `grade == "b"`) firing.
- **`self` / `cls`**, added to `EXTERNAL_VOCAB`: comparing against those
  inspects a function signature (`pydantic/pydantic/v1/class_validators.py:268`),
  it does not dispatch over a domain.

Replace a genuine hit with:
    class Status(StrEnum):
        ACTIVE = "active"
        INACTIVE = "inactive"

References:
- https://docs.python.org/3/library/enum.html#enum.StrEnum
- https://docs.pydantic.dev/latest/concepts/types/#enums

## Implementation notes

### `_extract_compare`

Handles `x == "a"`, `"a" == x` (yoda), `x != "a"`, and
`x in ("a", "b")` / `x not in {...}` where every element is a string
constant. The compared variable must be a plain *name* — subscripts (dict
keys), calls, f-strings, and attribute chains (`url.scheme`, `field.mode`,
reflection keys) are excluded: the module cannot turn a value it doesn't
own into a StrEnum. `is_equality` is True only for `==` / `!=`; a bare
membership test is not on its own strong enough to fire.

### `_literal_string_values`

A `Literal[...]` with only non-string members yields an empty list (still a
Literal); a non-`Literal` node yields None.

### `_is_foreign_attribute`

`token.type` is somebody else's field; `self.mode` is this class's own, but
`self._config_wrapper.extra` has left `self` and reached a collaborator.

### `_is_wire_lookup`

Subscripts, `.get()` / `.items()` / `next()` / `os.getenv()` style reads,
attribute reads off another object, and any of those behind one iterable
wrapper (`zip(...)`, `sorted(...)`, `enumerate(...)`).

### `_wire_bound_names`

`schema_type = schema['type']` / `extra = cfg.get('behavior')` read a value
off a dict-shaped wire format; `for k, v in obj.items()` and
`for arg, name in zip(expr.args, expr.arg_names)` iterate somebody else's
keys; `event = os.getenv(...)` reads the environment; `word = next(words,
"")` pulls a token off a scan. Clusters on such names are
external-vocabulary dispatch, not an app enum — and the direct form
(`obj.attr == "a"`) never fired either, so binding it to a local first must
not change the answer. Nested functions/classes own their scope and are not
descended into.

### `_literal_returning_functions`

A local bound from such a call already has a closed domain, declared at the
function that produced it (pydantic's `_inlining_behavior(...) ->
Literal['inline', 'keep', 'preserve_metadata']`).

### `_is_foreign_annotation`

`str`, `str | None` and `Optional[str]` are the shapes this rule is about
and are NOT foreign; a bare name or dotted reference to anything else is.

### `_foreign_typed_names`

Rich's `justify: JustifyMethod` / pydantic's `mode: FieldValidatorModes` are
already closed sets — declared as `Literal` aliases in the module that owns
them — but the alias is imported, so it cannot be resolved from here. What
IS visible is that the value is not a bare `str`: its domain has a name and
a definition site, and "define a StrEnum" belongs there, not here.

### `_local_bindings`

Nested functions/classes own their scope and are not descended into.

### `_opaque_names`

Three families, then closed under assignment (a name derived from an opaque
name is itself opaque — Rich's `_overflow = overflow or self.overflow or
DEFAULT_OVERFLOW`):

* already-closed domains — a `Literal` annotation, or a call to a
  same-module function that returns one;
* separately-typed names — anything annotated with a named type other than
  `str` (`justify: JustifyMethod`): the domain already has a home, and it
  is not this comparison's to redefine;
* wire-bound names — read off a payload, an iteration over somebody else's
  mapping/attribute, an environment variable, or a token stream.

### `_literal_typed_names`

Covers the function's own parameters and `x: <literal>` annotated locals in
its body (not descending into nested functions/classes, which own their
scope).

### `_cluster_is_already_closed`

Suppressed when the variable is an open-domain code name, is annotated as a
`Literal` (inline or via a module alias), or its compared literals are all
members of an in-module `Literal` alias's value set.
