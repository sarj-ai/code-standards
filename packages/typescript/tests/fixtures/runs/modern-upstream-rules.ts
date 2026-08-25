export type User = { readonly id: string };
export const makeUser = (id: string): User => ({ id });

export { type User as ExportedUser, makeUser as exportedMakeUser };

export const hasId = (value: object): boolean =>
  Object.prototype.hasOwnProperty.call(value, "id");
