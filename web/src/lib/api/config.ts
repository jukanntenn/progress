import type { FieldSchema, SectionSchema } from "./config-types";

export type { FieldSchema, SectionSchema };

export interface ConfigData {
  data: Record<string, unknown>;
  version: number;
}

export interface ConfigSaveResult {
  data: Record<string, unknown>;
  version: number;
}

export interface ConfigValidateResult {
  success: boolean;
  error?: string;
}

export type JsonSchema = Record<string, unknown>;

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    const message = (detail as { detail?: string }).detail ?? res.statusText;
    const error = new Error(message) as Error & { status?: number };
    error.status = res.status;
    throw error;
  }
  return res.json() as Promise<T>;
}

export async function fetchConfig(): Promise<ConfigData> {
  const res = await fetch("/api/v1/config");
  return json<ConfigData>(res);
}

export async function fetchConfigSchema(): Promise<JsonSchema> {
  const res = await fetch("/api/v1/config/schema");
  return json<JsonSchema>(res);
}

export async function fetchTimezones(): Promise<string[]> {
  const res = await fetch("/api/v1/config/timezones");
  const data = await json<{ timezones: string[] }>(res);
  return data.timezones;
}

export async function saveConfig(
  config: Record<string, unknown>,
  version: number,
): Promise<ConfigSaveResult> {
  const res = await fetch("/api/v1/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ config, version }),
  });
  return json<ConfigSaveResult>(res);
}

export async function validateConfig(
  config: Record<string, unknown>,
): Promise<ConfigValidateResult> {
  const res = await fetch("/api/v1/config/validate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ config }),
  });
  return json<ConfigValidateResult>(res);
}
