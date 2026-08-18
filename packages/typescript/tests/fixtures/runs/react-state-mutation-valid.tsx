import React from "react";

export class Counter extends React.Component {
  increment(): void {
    this.setState(({ count }) => ({ count: count + 1 }));
  }
}
