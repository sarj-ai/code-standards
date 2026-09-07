type WirePayload = { wire_key: string };

export function requestHandler(snake_param: string): string {
  return snake_param;
}

export function aliasedWireKey({ wire_key: wireKey }: WirePayload): string {
  return wireKey;
}

export function shorthandWireKey({ wire_key }: WirePayload): string {
  return wire_key;
}

export function snakeAlias({ wire_key: snake_local }: WirePayload): string {
  return snake_local;
}

export function arrayBinding([snake_item]: string[]): string | undefined {
  return snake_item;
}
