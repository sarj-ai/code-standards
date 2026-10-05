/**
 * Newlines between value getter for overload signatures.
 *
 * @param newlinesBetweenOverloadSignatures - Newlines between overload
 *   signatures option value.
 * @returns NewlinesBetween option value.
 */
function buildOverloadSignatureNewlinesBetweenValueGetter(
  newlinesBetweenOverloadSignatures,
) {
  return ({ computedNewlinesBetween, right, left }) => {
    if (
      left.overloadSignatureImplementation &&
      left.overloadSignatureImplementation ===
        right.overloadSignatureImplementation
    ) {
      return newlinesBetweenOverloadSignatures
    }
    return computedNewlinesBetween
  }
}
export { buildOverloadSignatureNewlinesBetweenValueGetter }
