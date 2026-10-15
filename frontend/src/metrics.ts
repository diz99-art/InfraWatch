export type CPU = { usage_percent: number; measurement_window_ms: number };
export type Memory = {
  total_bytes: number;
  available_bytes: number;
  used_bytes: number;
  usage_percent: number;
};
export type Disk = {
  target_id: "primary";
  total_bytes: number;
  used_bytes: number;
  free_bytes: number;
  usage_percent: number;
};
export type Uptime = { seconds: number; booted_at: string };
export type Values = {
  cpu: CPU | null;
  memory: Memory | null;
  disk: Disk | null;
  uptime: Uptime | null;
};
export type Resource = keyof Values;
export const resources: Resource[] = ["cpu", "memory", "disk", "uptime"];
export type Metrics = {
  schema_version: 1;
  status: "ok" | "partial";
  host: {
    id: string;
    label: string;
    platform: "darwin" | "linux" | "win32" | "other";
    scope: "local_system";
  };
  collected_at: string;
  age_seconds: number;
  collection_interval_seconds: 5;
  metrics: Values;
  errors: {
    resource: Resource;
    code: "COLLECTION_FAILED" | "INVALID_VALUE";
    message: string;
  }[];
};
export function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function number(
  value: unknown,
  min = 0,
  max = Number.MAX_SAFE_INTEGER,
): value is number {
  return (
    typeof value === "number" &&
    Number.isFinite(value) &&
    value >= min &&
    value <= max
  );
}
function integer(value: unknown, min = 0): value is number {
  return number(value, min) && Number.isSafeInteger(value);
}
function timestamp(value: unknown): value is string {
  if (
    typeof value !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(value)
  )
    return false;
  const date = new Date(value);
  return Number.isFinite(date.getTime()) && date.toISOString() === value;
}
export function parseMetrics(data: unknown): Metrics {
  const bad = () => {
    throw new Error("Invalid metrics response");
  };
  if (
    !isObject(data) ||
    data.schema_version !== 1 ||
    !["ok", "partial"].includes(String(data.status)) ||
    !timestamp(data.collected_at) ||
    !number(data.age_seconds) ||
    data.collection_interval_seconds !== 5 ||
    !isObject(data.host) ||
    !isObject(data.metrics) ||
    !Array.isArray(data.errors)
  )
    return bad();
  const host = data.host;
  if (
    typeof host.id !== "string" ||
    !/^[a-z0-9_-]{1,64}$/.test(host.id) ||
    typeof host.label !== "string" ||
    host.label.length < 1 ||
    host.label.length > 80 ||
    !["darwin", "linux", "win32", "other"].includes(String(host.platform)) ||
    host.scope !== "local_system"
  )
    return bad();
  const values = data.metrics;
  for (const name of resources) {
    const value = values[name];
    if (value === null) continue;
    if (!isObject(value)) return bad();
    if (name !== "uptime" && !number(value.usage_percent, 0, 100)) return bad();
    if (name === "cpu" && !integer(value.measurement_window_ms, 1))
      return bad();
    if (name === "memory") {
      if (
        !integer(value.total_bytes, 1) ||
        !integer(value.available_bytes) ||
        !integer(value.used_bytes) ||
        !number(value.usage_percent, 0, 100)
      )
        return bad();
      if (
        value.available_bytes > value.total_bytes ||
        value.used_bytes !== value.total_bytes - value.available_bytes ||
        Math.abs(
          value.usage_percent - (value.used_bytes / value.total_bytes) * 100,
        ) > 0.051
      )
        return bad();
    }
    if (name === "disk") {
      if (
        value.target_id !== "primary" ||
        !integer(value.total_bytes, 1) ||
        !integer(value.used_bytes) ||
        !integer(value.free_bytes) ||
        value.used_bytes > value.total_bytes ||
        value.free_bytes > value.total_bytes
      )
        return bad();
    }
    if (
      name === "uptime" &&
      (!integer(value.seconds) ||
        !timestamp(value.booted_at) ||
        value.booted_at > data.collected_at)
    )
      return bad();
  }
  const missing = resources.filter((name) => values[name] === null);
  if (
    missing.length === 4 ||
    data.status !== (missing.length ? "partial" : "ok") ||
    data.errors.length !== missing.length
  )
    return bad();
  const seen = new Set();
  for (const error of data.errors) {
    if (
      !isObject(error) ||
      !missing.includes(error.resource as Resource) ||
      seen.has(error.resource) ||
      !["COLLECTION_FAILED", "INVALID_VALUE"].includes(String(error.code)) ||
      typeof error.message !== "string"
    )
      return bad();
    seen.add(error.resource);
  }
  return data as Metrics;
}
export function capacity(bytes: number) {
  return `${(bytes / 1024 ** 3).toFixed(1)} GiB`;
}
export function localTime(value: string) {
  return new Date(value).toLocaleString(undefined, { timeZoneName: "short" });
}
export function duration(seconds: number) {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return `${days}일 ${hours}시간 ${minutes}분 ${seconds % 60}초`;
}
