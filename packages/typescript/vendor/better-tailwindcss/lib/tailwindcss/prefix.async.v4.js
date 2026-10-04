export function getPrefix(tailwindContext) {
    return tailwindContext.theme.prefix ?? "";
}
export function getSuffix(tailwindContext) {
    return !!tailwindContext.theme.prefix ? ":" : "";
}