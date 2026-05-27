"use client";

import { useQuery } from "@tanstack/react-query";
import { configKeys, fetchConfig, fetchConfigSchema, fetchTimezones } from "@/lib/api";

export function useConfig() {
  return useQuery({
    queryKey: configKeys.data(),
    queryFn: fetchConfig,
  });
}

export function useConfigSchema() {
  return useQuery({
    queryKey: configKeys.schema(),
    queryFn: fetchConfigSchema,
  });
}

export function useTimezones() {
  return useQuery({
    queryKey: configKeys.timezones(),
    queryFn: fetchTimezones,
  });
}
