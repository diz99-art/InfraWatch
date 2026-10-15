export async function checkHealth(signal: AbortSignal): Promise<void> {
  const base = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
  const response = await fetch(`${base}/api/health`, { signal });
  if (!response.ok) throw new Error("Health request failed");
  const data: unknown = await response.json();
  if (
    !data ||
    typeof data !== "object" ||
    !("status" in data) ||
    data.status !== "ok" ||
    !("service" in data) ||
    data.service !== "InfraWatch"
  ) {
    throw new Error("Invalid health response");
  }
}

import { isObject, parseMetrics } from "./metrics";

export type MetricsFailure =
  | "not-ready"
  | "collection"
  | "stale"
  | "connection"
  | "timeout"
  | "api"
  | "invalid";
export class MetricsRequestError extends Error {
  constructor(public kind: MetricsFailure) {
    super(kind);
  }
}
export async function getMetrics(signal: AbortSignal) {
  const base = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
  let response: Response;
  try {
    response = await fetch(`${base}/api/metrics`, {
      signal,
      cache: "no-store",
    });
  } catch {
    throw new MetricsRequestError("connection");
  }
  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new MetricsRequestError(response.ok ? "invalid" : "api");
  }
  if (!response.ok) {
    if (response.status === 503 && isObject(data) && isObject(data.error)) {
      const reason = data.error.reason;
      if (reason === "METRICS_NOT_READY")
        throw new MetricsRequestError("not-ready");
      if (reason === "METRICS_STALE") throw new MetricsRequestError("stale");
      if (reason === "COLLECTION_FAILED" || reason === "COLLECTION_TIMEOUT")
        throw new MetricsRequestError("collection");
    }
    throw new MetricsRequestError("api");
  }
  try {
    return parseMetrics(data);
  } catch {
    throw new MetricsRequestError("invalid");
  }
}
