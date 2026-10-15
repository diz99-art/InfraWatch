import { expect, test, vi } from "vitest";
import { getMetrics, MetricsRequestError } from "./api";
import { parseMetrics } from "./metrics";
import { metricsFixture } from "./metrics-fixture";

test("accepts valid sample and zero / hundred percent", () => {
  expect(parseMetrics(metricsFixture()).status).toBe("ok");
  for (const value of [0, 100]) {
    const data = metricsFixture();
    data.metrics.cpu!.usage_percent = value;
    expect(parseMetrics(data).metrics.cpu?.usage_percent).toBe(value);
  }
});
test.each([-1, 101, NaN, Infinity, "25", true])(
  "rejects invalid CPU value %s",
  (value) => {
    const data = metricsFixture() as unknown as {
      metrics: { cpu: { usage_percent: unknown } };
    };
    data.metrics.cpu.usage_percent = value;
    expect(() => parseMetrics(data)).toThrow();
  },
);
test("rejects inconsistent memory partial states invalid dates and missing fields", () => {
  const memory = metricsFixture();
  memory.metrics.memory!.used_bytes = 100;
  expect(() => parseMetrics(memory)).toThrow();
  const partial = metricsFixture();
  partial.metrics.disk = null;
  expect(() => parseMetrics(partial)).toThrow();
  const date = metricsFixture();
  date.collected_at = "2026-02-31T00:00:00.000Z";
  expect(() => parseMetrics(date)).toThrow();
  const missing = { ...metricsFixture(), schema_version: 2 };
  expect(() => parseMetrics(missing)).toThrow();
});
test("rejects duplicate error resource and all-null success", () => {
  const data = metricsFixture();
  data.status = "partial";
  data.metrics.disk = null;
  data.errors = [
    { resource: "disk", code: "COLLECTION_FAILED", message: "unavailable" },
    { resource: "disk", code: "COLLECTION_FAILED", message: "unavailable" },
  ];
  expect(() => parseMetrics(data)).toThrow();
  data.metrics = { cpu: null, memory: null, disk: null, uptime: null };
  expect(() => parseMetrics(data)).toThrow();
});
test.each([
  ["METRICS_NOT_READY", "not-ready"],
  ["COLLECTION_FAILED", "collection"],
  ["COLLECTION_TIMEOUT", "collection"],
  ["METRICS_STALE", "stale"],
])("maps 503 %s separately", async (reason, kind) => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => ({ error: { reason } }),
    }),
  );
  await expect(getMetrics(new AbortController().signal)).rejects.toMatchObject({
    kind,
  });
});
test("runtime validation and generic HTTP errors are distinct", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({}) })
    .mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: async () => ({ error: { code: 500 } }),
    });
  vi.stubGlobal("fetch", fetch);
  await expect(getMetrics(new AbortController().signal)).rejects.toMatchObject({
    kind: "invalid",
  });
  await expect(getMetrics(new AbortController().signal)).rejects.toMatchObject({
    kind: "api",
  });
});
test("valid metrics fetch uses same-origin URL and no-store", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValue({ ok: true, json: async () => metricsFixture() });
  vi.stubGlobal("fetch", fetch);
  const signal = new AbortController().signal;
  await expect(getMetrics(signal)).resolves.toEqual(metricsFixture());
  expect(fetch).toHaveBeenCalledWith("/api/metrics", {
    signal,
    cache: "no-store",
  });
});
test("transport failure produces connection error", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockRejectedValue(new Error("private detail")),
  );
  await expect(getMetrics(new AbortController().signal)).rejects.toEqual(
    new MetricsRequestError("connection"),
  );
});
