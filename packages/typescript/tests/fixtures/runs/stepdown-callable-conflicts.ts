export class ConstructedRunner {
  private load(): number {
    return 1;
  }

  public constructor() {
    this.load();
  }
}

export class GetterRunner {
  private load(): number {
    return 1;
  }

  public get result(): number {
    return this.load();
  }
}

export class SetterRunner {
  private save(value: number): void {
    void value;
  }

  public set result(value: number) {
    this.save(value);
  }
}
