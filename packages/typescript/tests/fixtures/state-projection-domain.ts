export enum Phase {
  Ready = "ready",
  Waiting = "waiting",
  Reconnecting = "reconnecting",
  Closed = "closed",
  Unknown = "unknown",
}

export { Phase as ReexportedPhase };

export const lookalike: typeof Phase = Phase;
