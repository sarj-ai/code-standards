export interface TrialChannelRecord {
  applicationId: string;
  channelId: null | string;
}

export interface OptionalDomainRecord {
  applicationId: string;
  channelId: null | string;
  displayName?: string;
}

export interface ReadonlyRecord {
  readonly applicationId: string;
}

export interface GenericRecord<T> {
  data: T;
}

export type AliasRecord = {
  applicationId: string;
  channelId: null | string;
};

export interface NestedRecord {
  child: { value: string };
  tags: string[];
}

export interface AugmentedRecord {
  applicationId: string;
}

export interface AugmentedRecord {
  channelId: null | string;
}
