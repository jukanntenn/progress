"use client";

import { useQuery } from "@tanstack/react-query";
import { reportKeys, fetchReports, fetchReport } from "@/lib/api";

export function useReports(page: number = 1) {
  return useQuery({
    queryKey: reportKeys.list(page),
    queryFn: () => fetchReports(page),
  });
}

export function useReport(id: number | undefined) {
  return useQuery({
    queryKey: reportKeys.detail(id!),
    queryFn: () => fetchReport(id!),
    enabled: id !== undefined,
  });
}
