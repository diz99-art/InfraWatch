import { act, fireEvent, render, screen } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { getMetrics, MetricsRequestError } from "./api";
import MetricsPanel from "./MetricsPanel";
import App from "./App";
import { metricsFixture } from "./metrics-fixture";
import type { Metrics } from "./metrics";

vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  getMetrics: vi.fn(),
}));
const request = vi.mocked(getMetrics);
beforeEach(() => {
  vi.useFakeTimers();
  request.mockReset();
  request.mockResolvedValue(metricsFixture());
});
afterEach(() => {
  vi.restoreAllMocks();
});
async function settle() {
  await act(async () => {
    await Promise.resolve();
  });
}
async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}
function partial(): Metrics {
  const data = metricsFixture();
  data.status = "partial";
  data.metrics.disk = null;
  data.errors = [
    {
      resource: "disk",
      code: "COLLECTION_FAILED",
      message: "Disk metrics unavailable",
    },
  ];
  return data;
}

test("first loading has no fabricated numbers", () => {
  request.mockReturnValue(new Promise(() => {}));
  render(<MetricsPanel />);
  expect(screen.getByTestId("metrics-state")).toHaveTextContent(
    "데이터 수신 전",
  );
  expect(screen.getAllByText("—")).toHaveLength(4);
  expect(
    screen.getByRole("button", { name: "메트릭 새로고침" }),
  ).toBeDisabled();
});
test("shows validated values units uptime and distinct timestamps", async () => {
  render(<MetricsPanel />);
  await settle();
  expect(screen.getByText("25.0%")).toBeInTheDocument();
  expect(screen.getByText("37.5%")).toBeInTheDocument();
  expect(screen.getByText("52.6%")).toBeInTheDocument();
  expect(screen.getByText(/3.0 GiB \/ 8.0 GiB/)).toBeInTheDocument();
  expect(screen.getByText("0일 1시간 0분 0초")).toBeInTheDocument();
  expect(screen.getByTestId("metrics-state")).toHaveTextContent("정상 수집");
  expect(screen.getByText(/마지막 수집:/)).toBeInTheDocument();
  expect(screen.getByText(/마지막 데이터 갱신:/)).toBeInTheDocument();
});
test("partial initial sample keeps failed resource empty", async () => {
  request.mockResolvedValue(partial());
  render(<MetricsPanel />);
  await settle();
  expect(screen.getByTestId("metrics-state")).toHaveTextContent(
    "일부 지표 수집 실패",
  );
  expect(screen.getByText("수집 실패")).toBeInTheDocument();
  expect(screen.queryByText("52.6%")).not.toBeInTheDocument();
  expect(screen.getByText("25.0%")).toBeInTheDocument();
});
test("partial later sample preserves disk's original timestamp as previous", async () => {
  const next = partial();
  next.collected_at = "2026-10-14T02:01:00.000Z";
  request.mockResolvedValueOnce(metricsFixture()).mockResolvedValueOnce(next);
  render(<MetricsPanel />);
  await settle();
  await advance(5000);
  expect(screen.getByText("52.6%")).toBeInTheDocument();
  const previous = screen.getByText(/^이전 값/);
  expect(previous).toHaveTextContent(
    new Date(metricsFixture().collected_at).toLocaleString(undefined, {
      timeZoneName: "short",
    }),
  );
});
test.each([
  ["collection", "전체 수집 실패"],
  ["not-ready", "첫 데이터 수집 중"],
  ["stale", "수집 지연"],
  ["connection", "API 연결 실패"],
  ["api", "API 오류"],
  ["invalid", "응답 형식 오류"],
] as const)("distinguishes %s failure", async (kind, label) => {
  request.mockRejectedValue(new MetricsRequestError(kind));
  render(<MetricsPanel />);
  await settle();
  expect(screen.getByTestId("metrics-state")).toHaveTextContent(label);
  expect(screen.getAllByText("—")).toHaveLength(4);
});
test("failure never updates previous collection or data reception timestamps", async () => {
  request
    .mockResolvedValueOnce(metricsFixture())
    .mockRejectedValue(new MetricsRequestError("connection"));
  const { container } = render(<MetricsPanel />);
  await settle();
  const times = [...container.querySelectorAll("time")].map((t) => t.dateTime);
  await advance(5000);
  expect(
    [...container.querySelectorAll("time")].map((t) => t.dateTime),
  ).toEqual(times);
  expect(screen.getAllByText(/^이전 값/)).toHaveLength(4);
});
test("manual retry recovers after failure without overlapping the pending request", async () => {
  let resolve!: (value: Metrics) => void;
  request
    .mockRejectedValueOnce(new MetricsRequestError("collection"))
    .mockReturnValueOnce(
      new Promise((done) => {
        resolve = done;
      }),
    );
  render(<MetricsPanel />);
  await settle();
  fireEvent.click(screen.getByRole("button"));
  fireEvent.click(screen.getByRole("button"));
  expect(request).toHaveBeenCalledTimes(2);
  expect(screen.getByRole("button")).toBeDisabled();
  await act(async () => {
    resolve(metricsFixture());
  });
  expect(screen.getByTestId("metrics-state")).toHaveTextContent("정상 수집");
});
test("polls five seconds after completion rather than starting overlapping requests", async () => {
  let resolve!: (value: Metrics) => void;
  request.mockReturnValueOnce(
    new Promise((done) => {
      resolve = done;
    }),
  );
  render(<MetricsPanel />);
  await advance(4000);
  expect(request).toHaveBeenCalledTimes(1);
  await act(async () => {
    resolve(metricsFixture());
  });
  await advance(4999);
  expect(request).toHaveBeenCalledTimes(1);
  await advance(1);
  expect(request).toHaveBeenCalledTimes(2);
});
test("uses bounded failure backoff and resets on recovery", async () => {
  request.mockRejectedValue(new MetricsRequestError("connection"));
  render(<MetricsPanel />);
  await settle();
  for (const [delay, count] of [
    [5000, 2],
    [10000, 3],
    [20000, 4],
    [30000, 5],
    [30000, 6],
  ]) {
    await advance(delay - 1);
    expect(request).toHaveBeenCalledTimes(count - 1);
    await advance(1);
    expect(request).toHaveBeenCalledTimes(count);
  }
  request.mockResolvedValue(metricsFixture());
  await advance(30000);
  expect(request).toHaveBeenCalledTimes(7);
  await advance(5000);
  expect(request).toHaveBeenCalledTimes(8);
});
test("five second timeout aborts even when the transport never settles", async () => {
  request.mockReturnValue(new Promise(() => {}));
  render(<MetricsPanel />);
  await advance(5000);
  expect(request.mock.calls[0][0].aborted).toBe(true);
  expect(screen.getByTestId("metrics-state")).toHaveTextContent(
    "요청 시간 초과",
  );
  expect(screen.getByRole("button")).not.toBeDisabled();
});
test("unmount cancels requests timers and ignores late responses", async () => {
  let resolve!: (value: Metrics) => void;
  request.mockReturnValue(
    new Promise((done) => {
      resolve = done;
    }),
  );
  const { unmount } = render(<MetricsPanel />);
  const signal = request.mock.calls[0][0];
  unmount();
  expect(signal.aborted).toBe(true);
  await act(async () => {
    resolve(metricsFixture());
  });
  await advance(60000);
  expect(request).toHaveBeenCalledTimes(1);
  expect(vi.getTimerCount()).toBe(0);
});
test("marks old data stale without waiting for another successful request", async () => {
  request.mockImplementationOnce(async () => {
    const data = metricsFixture();
    data.age_seconds = 14;
    return data;
  });
  render(<MetricsPanel />);
  await settle();
  await advance(1000);
  expect(screen.getByTestId("metrics-state")).toHaveTextContent("수집 지연");
  expect(screen.getAllByText(/^이전 값/)).toHaveLength(4);
});
test("visibility pause cancels polling and resumes with one request", async () => {
  const visibility = vi
    .spyOn(document, "visibilityState", "get")
    .mockReturnValue("visible");
  render(<MetricsPanel />);
  await settle();
  visibility.mockReturnValue("hidden");
  act(() => document.dispatchEvent(new Event("visibilitychange")));
  await advance(30000);
  expect(request).toHaveBeenCalledTimes(1);
  visibility.mockReturnValue("visible");
  act(() => document.dispatchEvent(new Event("visibilitychange")));
  await settle();
  expect(request).toHaveBeenCalledTimes(2);
});
test("offline pauses requests and online recovers", async () => {
  const online = vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
  render(<MetricsPanel />);
  await settle();
  await advance(30000);
  expect(request).not.toHaveBeenCalled();
  online.mockReturnValue(true);
  act(() => window.dispatchEvent(new Event("online")));
  await settle();
  expect(request).toHaveBeenCalledTimes(1);
});
test("StrictMode cleanup aborts obsolete effect and keeps one polling timer", async () => {
  render(
    <StrictMode>
      <MetricsPanel />
    </StrictMode>,
  );
  await settle();
  expect(request.mock.calls[0][0].aborted).toBe(true);
  const count = request.mock.calls.length;
  await advance(5000);
  expect(request).toHaveBeenCalledTimes(count + 1);
});
test("metrics failure and polling do not alter the manual health status", async () => {
  const fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ status: "ok", service: "InfraWatch" }),
  });
  vi.stubGlobal("fetch", fetch);
  request.mockRejectedValue(new MetricsRequestError("collection"));
  render(<App />);
  await settle();
  expect(screen.getByRole("status")).toHaveTextContent("연결 성공");
  await advance(15000);
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(screen.getByTestId("metrics-state")).toHaveTextContent(
    "전체 수집 실패",
  );
  fireEvent.click(screen.getByRole("button", { name: "다시 확인" }));
  await settle();
  expect(fetch).toHaveBeenCalledTimes(2);
});
