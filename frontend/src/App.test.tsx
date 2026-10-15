import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, test, expect } from "vitest";
import App from "./App";

// Keep the original health regressions independent of metrics polling.
vi.mock("./MetricsPanel", () => ({ default: () => null }));

function response(
  data: unknown = { status: "ok", service: "InfraWatch" },
  ok = true,
) {
  return { ok, json: async () => data };
}
test("shows loading while request is pending", () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => new Promise(() => {})),
  );
  render(<App />);
  expect(screen.getByRole("status")).toHaveTextContent("연결 중");
  expect(screen.getByRole("button")).toBeDisabled();
});
test("shows success for valid API response", async () => {
  const fetchMock = vi.fn().mockResolvedValue(response());
  vi.stubGlobal("fetch", fetchMock);
  render(<App />);
  await waitFor(() =>
    expect(screen.getByRole("status")).toHaveTextContent("연결 성공"),
  );
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/health",
    expect.objectContaining({ signal: expect.any(AbortSignal) }),
  );
});
test("shows network failure and allows retry", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(response()),
  );
  render(<App />);
  await waitFor(() =>
    expect(screen.getByRole("status")).toHaveTextContent("연결 실패"),
  );
  fireEvent.click(screen.getByRole("button"));
  await waitFor(() =>
    expect(screen.getByRole("status")).toHaveTextContent("연결 성공"),
  );
});
test("rejects HTTP errors", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({}, false)));
  render(<App />);
  await waitFor(() =>
    expect(screen.getByRole("status")).toHaveTextContent("연결 실패"),
  );
});
test("rejects malformed health payloads", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({ status: "ok" })));
  render(<App />);
  await waitFor(() =>
    expect(screen.getByRole("status")).toHaveTextContent("연결 실패"),
  );
});
test("aborts timed out requests and shows failure", async () => {
  vi.useFakeTimers();
  vi.stubGlobal(
    "fetch",
    vi.fn(
      (_url, { signal }) =>
        new Promise((_resolve, reject) =>
          signal.addEventListener("abort", () => reject(new Error("timeout"))),
        ),
    ),
  );
  render(<App />);
  const { act } = await import("@testing-library/react");
  await act(async () => {
    await vi.advanceTimersByTimeAsync(5000);
  });
  expect(screen.getByRole("status")).toHaveTextContent("연결 실패");
});
