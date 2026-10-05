/**
 * Represents a group of overload signatures along with their implementation.
 */
var OverloadSignatureGroup = class {
  implementation
  _overloadSignatures
  constructor({ overloadSignatures, implementation }) {
    this._overloadSignatures = new Set(overloadSignatures)
    this.implementation = implementation
  }
  doesNodeBelongToGroup(node) {
    return this._overloadSignatures.has(node) || this.implementation === node
  }
}
export { OverloadSignatureGroup }
