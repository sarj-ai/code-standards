declare function use(value: string): void;
declare const items: string[] | undefined;

for (const item of items ?? []) {
  use(item);
}
