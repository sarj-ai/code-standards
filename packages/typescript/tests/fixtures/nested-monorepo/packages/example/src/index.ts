export async function invalidAwait(): Promise<string> {
  return await "value";
}
