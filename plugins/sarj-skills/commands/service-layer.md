# Service boundaries

Apply [protocol](../skills/audit-protocol/SKILL.md).

Move privileged client work/presentation policy to an authorized boundary only
when contracts or measured cost improve. Add layers for real substitution/policy,
not simple CRUD. Keep deploy-varying settings at a typed startup boundary; inspect
unsafe fallbacks without turning stable constants into settings.

Trace deployment accounts/projects, service origins, resource identifiers, paths
and tuning to their configuration owner. Externalize deployment-varying values;
reuse existing inputs. Construct one shared validated root settings object per
application/runtime startup, then inject/import that instance in consumers.
Compose existing nested settings and preserve aliases, source precedence and
intentional optional defaults. Keep server secrets separate from public client
settings; share parsed output, never raw input aliases.
Construct settings at the owning entrypoint; library imports and unused CLI
commands should not require unrelated deployment configuration.

In JavaScript/TypeScript, use the output of the actual Zod parser. Await
`parseAsync`/`safeParseAsync`; handle `safeParse` failure before using `.data`.
A schema declaration, parser-shaped method name, ignored result or unawaited
promise does not establish validated settings. For the existing account input:

```ts
import { z } from "zod";
const SettingsSchema = z.object({
  CLOUDFLARE_ACCOUNT_ID: z.string().length(32).regex(/^[a-fA-F0-9]{32}$/u),
});
export const settings = SettingsSchema.parse(process.env);
```

In Python, construct Pydantic Settings for environment sources, or use a
Pydantic `BaseModel.model_validate(...)`/`model_validate_json(...)` for an
already-loaded mapping/JSON input. Use the validated model. `model_construct`
and `model_copy(update=raw)` do not validate external configuration.

```python
from pydantic import Field
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    cloudflare_account_id: str = Field(
        validation_alias="CLOUDFLARE_ACCOUNT_ID",
        min_length=32,
        max_length=32,
        pattern=r"^[a-fA-F0-9]{32}$",
    )

settings = Settings()
```

Environment input is text. Parse textual booleans/numbers deliberately:
`Boolean("false")` and `z.coerce.boolean()` use truthiness; `Number("")` is zero.
Use explicit textual-boolean parsing (such as `z.stringbool()` where supported)
or a deliberate true/false mapping. Coercion must not make missing/empty required
input valid. Required parse/validation failures stop startup before remote
effects; production account/service fallbacks must not hide them. Preserve
defaults where the contract permits omission and validate defaults when needed
(`BaseModel` defaults require `validate_default` for that validation).

| File/runtime | Native configuration boundary |
| --- | --- |
| Shell/Make | Quoted `${CLOUDFLARE_ACCOUNT_ID:?required}` checks presence; Make spells the shell dollar `$$`. Use quoted arguments and the actual shell. Domain validation belongs to the invoked runtime or native shell implementation. |
| GitHub Actions YAML | Pass deployment `vars` and credential `secrets` through `env`/action inputs; validate in the invoked entrypoint. Avoid turning untrusted expressions into shell source. |
| Terraform/HCL | Typed inputs via caller modules, tfvars or `TF_VAR_`, with native provider/input validation. Reuse resource/data references and fixed shared locals; preserve independent scopes. |
| Compose/Kubernetes/Dockerfile | Use supported interpolation, config/secret references and runtime env; preserve source precedence. Syntax-only or no-interpolation checks do not validate resolved app settings; required interpolation checks presence only. Keep credentials out of image `ARG`/`ENV`; exec-form argv does not imply shell expansion. |
| JSON/JSONC/TOML/INI/dotenv | Use the consuming tool's supported loader or an explicit generator emitting validated output. These formats do not inherently expand `${VAR}`; native syntax/schema checks do not prove application-domain validation. |
| SQL | Bind application values or use explicit runner/session configuration. Preserve schema identifiers and immutable migration literals. |
| Swift/Kotlin/native apps | Use platform build/runtime settings for public values. Packaged values are extractable; retain privileged secrets at an authorized server or appropriate user secret store. |
| Markdown/examples | Document required names and safe placeholders; keep fixtures and illustrative literals deterministic. |

Keep reviewed security allowlists/expected identities independently authoritative;
reading the target and expected identity from one env setting removes the check.
Preserve policy, snapshots, stable protocol/tool constants and legitimate optional
settings. Validate native formats through their supported mechanisms and the
owning application runtime.

Startup tests should cover absent/malformed required input, empty/textual-boolean
coercion traps, permitted defaults, aliases/source precedence and nested settings;
prove validation precedes effects and consumers reuse the parsed settings object.

Trace acquisition/close ownership through the last consumer, including lazy
responses. FastAPI provider changes must preserve authorization/security schema:
`Security` and `Depends` can differ for the same callable.

Reuse compatible write commands without widening fields/access. Preserve
omitted/null, update-only, per-key authorization, ordering, results and atomic
transitions. Require observable alias/effect evidence for mutation/discarded-copy
findings; copy changed ancestors, preserve intentional stateful APIs.
