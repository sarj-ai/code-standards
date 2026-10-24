interface Identity {
  readonly name: string;
}

export interface AvatarProps extends Identity {
  avatar?: string;
}

export type PropsAlias = AvatarProps;
