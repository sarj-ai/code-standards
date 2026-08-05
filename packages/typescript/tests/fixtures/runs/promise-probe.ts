export async function loadValue(): Promise<number> {
  return Promise.resolve(1).then((value) => value + 1);
}
