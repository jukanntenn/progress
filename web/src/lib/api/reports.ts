export interface Report {
  id: number;
  title: string | null;
  created_at: string;
  markpost_url: string | null;
}

export interface ReportDetail extends Report {
  content: string;
}

export interface PaginatedReports {
  reports: Report[];
  page: number;
  total_pages: number;
  total: number;
  has_prev: boolean;
  has_next: boolean;
}

export async function fetchReports(page: number = 1): Promise<PaginatedReports> {
  const res = await fetch(`/api/v1/reports?page=${page}`);
  if (!res.ok) throw new Error("Failed to fetch reports");
  return res.json();
}

export async function fetchReport(id: number): Promise<ReportDetail> {
  const res = await fetch(`/api/v1/reports/${id}`);
  if (!res.ok) throw new Error("Failed to fetch report");
  return res.json();
}
