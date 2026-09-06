export class ErasedPrivate {
  private load() { return 1; }
  run() { return this.load(); }
}

export class RuntimePrivate {
  #load() { return 1; }
  run() { return this.#load(); }
}
