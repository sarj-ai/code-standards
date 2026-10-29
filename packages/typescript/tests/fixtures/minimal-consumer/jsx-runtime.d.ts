declare module "react/jsx-runtime" {
  export namespace JSX {
    interface Element {}
    interface IntrinsicAttributes {key?: string | number}
    interface IntrinsicElements {
      div: {id?: string; children?: unknown};
      span: {children?: unknown};
    }
  }
}
