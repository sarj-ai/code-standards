export const z = {
  uuid: () => ({
    safeParse: (value: unknown) => ({ success: typeof value === "string" }),
  }),
};
