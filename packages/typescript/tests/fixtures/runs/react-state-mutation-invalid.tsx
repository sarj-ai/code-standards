import React from "react";

export class Counter extends React.Component {
  increment(): void {
    this.state.count += 1;
  }
}
