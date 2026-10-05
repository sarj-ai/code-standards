import {
  computeReadonlyModifier,
  computeStaticModifier,
} from './common-modifiers.js'
/**
 * Computes details related to an index-signature.
 *
 * @param params - Parameters object.
 * @param params.indexSignature - The index signature node to compute
 *   information for.
 * @param params.sourceCode - The source code object.
 * @returns An object containing various details about the index-signature.
 */
function computeIndexSignatureDetails({ indexSignature, sourceCode }) {
  return {
    name: sourceCode.text.slice(
      indexSignature.range.at(0),
      indexSignature.typeAnnotation?.range.at(0) ?? indexSignature.range.at(1),
    ),
    modifiers: computeModifiers(indexSignature),
    selectors: ['index-signature'],
  }
}
function computeModifiers(indexSignature) {
  return [
    ...computeStaticModifier(indexSignature),
    ...computeReadonlyModifier(indexSignature),
  ]
}
export { computeIndexSignatureDetails }
