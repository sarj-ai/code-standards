import { readFileSync } from 'node:fs';
import { getActionSchema } from '@actions/workflow-parser/actions/index';
import { convertToIfCondition } from '@actions/workflow-parser/model/converter/if-condition';
import { IdBuilder } from '@actions/workflow-parser/model/converter/id-builder';
import { TemplateContext, TemplateValidationErrors } from '@actions/workflow-parser/templates/template-context';
import { readTemplate } from '@actions/workflow-parser/templates/template-reader';
import { isMapping, isSequence, isString } from '@actions/workflow-parser/templates/tokens/type-guards';
import { ExpressionToken, type TemplateToken } from '@actions/workflow-parser/templates/tokens/index';
import { NoOperationTraceWriter } from '@actions/workflow-parser/templates/trace-writer';
import { YamlObjectReader } from '@actions/workflow-parser/workflows/yaml-object-reader';

interface Source {
  path: string;
  content: string;
}

// ActionManifestManager adds runtime requirements after the shared template reader.
function validateRuntime(context: TemplateContext, root: TemplateToken): void {
  if (!isMapping(root)) return;
  const runs = root.find('runs');
  if (!runs || !isMapping(runs)) {
    context.error(root, "Action requires a 'runs' mapping");
    return;
  }
  if (runs.find('plugin')) return;
  const using = runs.find('using');
  if (!using || !isString(using)) {
    context.error(runs, "Action requires 'runs.using'");
    return;
  }
  const runtimes = context.schema.getScalarDefinitions(context.schema.getDefinition('using'));
  if (!runtimes.some(runtime => runtime.isMatch(using))) {
    context.error(using, `Unsupported action runtime '${using.value}'`);
    return;
  }
  let required = 'main';
  if (using.value === 'composite') required = 'steps';
  if (using.value === 'docker') required = 'image';
  if (!runs.find(required)) context.error(runs, `Action runtime '${using.value}' requires '${required}'`);
  for (const key of ['pre-if', 'post-if']) {
    const condition = runs.find(key);
    if (!condition || !isString(condition)) continue;
    try {
      ExpressionToken.validateExpression(condition.value, context.schema.getDefinition('runs-if').readerContext);
    } catch (error) {
      context.error(condition, error);
    }
  }
  const steps = runs.find('steps');
  if (!steps || !isSequence(steps)) return;
  const ids = new IdBuilder();
  for (const step of steps) {
    if (!isMapping(step)) continue;
    const id = step.find('id');
    if (id && isString(id)) {
      // The runner compares known reference names without case sensitivity.
      const error = ids.tryAddKnownId(id.value.toLowerCase());
      if (error) context.error(id, error);
    }
    const condition = step.find('if');
    if (condition) convertToIfCondition(context, condition);
    const uses = step.find('uses');
    if (!uses || !isString(uses) || uses.value.startsWith('./') || uses.value.startsWith('.\\') || uses.value.startsWith('$/') || uses.value.startsWith('docker://')) continue;
    const [repository, ref, extra] = uses.value.split('@') as [string, ...string[]];
    if (!ref || extra !== undefined || repository.split(/[\\/]/).filter(Boolean).length < 2) {
      context.error(uses, "Action reference requires owner/repository[/path]@ref");
    }
  }
}

const sources = JSON.parse(readFileSync(process.argv[2]!, 'utf8')) as Source[];
const results = sources.map(({ path, content }) => {
  const context = new TemplateContext(new TemplateValidationErrors(), getActionSchema(), new NoOperationTraceWriter());
  const file = context.getFileId(path);
  const reader = new YamlObjectReader(file, content);
  for (const error of reader.errors) context.error(file, error.message, error.range);
  // parseAction selects action-root-strict for public metadata. The native
  // action-root contract matches the runner, including local actions without UI labels.
  const value = reader.errors.length ? undefined : readTemplate(context, 'action-root', reader, file);
  if (!context.errors.count && value) {
    validateRuntime(context, value);
  }
  return {
    path,
    errors: context.errors.getErrors().map(error => ({
      message: error.rawMessage,
      line: error.range?.start.line ?? 1,
      column: error.range?.start.column ?? 1,
    })),
  };
});
process.stdout.write(JSON.stringify(results));
