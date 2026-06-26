export const reportKeys = {
  all: ["reports"] as const,
  list: (page: number) => [...reportKeys.all, "list", page] as const,
  detail: (id: number) => [...reportKeys.all, "detail", id] as const,
};

export const configKeys = {
  all: ["config"] as const,
  data: () => [...configKeys.all, "data"] as const,
  schema: () => [...configKeys.all, "schema"] as const,
  timezones: () => [...configKeys.all, "timezones"] as const,
};
