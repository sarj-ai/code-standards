export interface ConsumerName {readonly name: string}
export interface ConsumerAccount extends ConsumerName {readonly email: string; readonly note?: string}
export type ConsumerAlias = ConsumerAccount;
