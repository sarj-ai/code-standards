/**
 * Generates all possible combinations of a specific size from an array.
 *
 * @param array - The array of strings to generate combinations from.
 * @param number - The number of elements in each combination.
 * @returns An array containing all possible combinations.
 */
function getArrayCombinations(array, number) {
  let result = []
  function backtrack(start, comb) {
    if (comb.length === number) {
      result.push([...comb])
      return
    }
    for (let i = start; i < array.length; i++) {
      comb.push(array[i])
      backtrack(i + 1, comb)
      comb.pop()
    }
  }
  backtrack(0, [])
  return result
}
export { getArrayCombinations }
