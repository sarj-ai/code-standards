export function readNamed(input: {
  named: string;
  [key: string]: string;
}): string {
  return input.named;
}
