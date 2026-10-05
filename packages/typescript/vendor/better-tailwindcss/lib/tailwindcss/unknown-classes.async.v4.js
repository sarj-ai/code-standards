export function getUnknownClasses(tailwindContext, classes) {
    const css = tailwindContext.candidatesToCss(classes);
    return classes.filter((_, index) => css.at(index) === null);
}