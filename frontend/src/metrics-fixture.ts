// Contract fixtures are for tests only; production never imports this module.
import type { Metrics } from "./metrics";
export function metricsFixture(): Metrics {
  return {
    schema_version: 1,
    status: "ok",
    host: {
      id: "local",
      label: "Local system",
      platform: "darwin",
      scope: "local_system",
    },
    collected_at: "2026-10-14T02:00:00.000Z",
    age_seconds: 0,
    collection_interval_seconds: 5,
    metrics: {
      cpu: { usage_percent: 25, measurement_window_ms: 1001 },
      memory: {
        total_bytes: 8589934592,
        used_bytes: 3221225472,
        available_bytes: 5368709120,
        usage_percent: 37.5,
      },
      disk: {
        target_id: "primary",
        total_bytes: 107374182400,
        used_bytes: 53687091200,
        free_bytes: 48318382080,
        usage_percent: 52.6,
      },
      uptime: { seconds: 3600, booted_at: "2026-10-14T01:00:00.000Z" },
    },
    errors: [],
  };
}
