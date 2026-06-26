"use client";

import { useQuery } from "@tanstack/react-query";
import {
  configKeys,
  fetchConfig,
  fetchConfigSchema,
  fetchOwners,
  fetchRepos,
  fetchTimezones,
} from "@/lib/api";

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

export function useRepos() {
  return useQuery({
    queryKey: configKeys.repos(),
    queryFn: fetchRepos,
  });
}

export function useOwners() {
  return useQuery({
    queryKey: configKeys.owners(),
    queryFn: fetchOwners,
  });
}
