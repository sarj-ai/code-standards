declare module "react/jsx-runtime" {
  export namespace JSX {
    interface Element {}
    interface IntrinsicElements {
      div: {[key: string]: unknown};
      span: {children?: unknown};
    }
  }
}
