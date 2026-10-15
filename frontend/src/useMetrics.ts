import { useEffect, useRef, useState } from "react";
import { getMetrics, MetricsRequestError, type MetricsFailure } from "./api";
import { resources, type Metrics, type Resource, type Values } from "./metrics";

export type StoredValues = {
  [K in Resource]?: { value: NonNullable<Values[K]>; collectedAt: string };
};
export type MetricsState = {
  data: Metrics | null;
  stored: StoredValues;
  updatedAt: string | null;
  failure: MetricsFailure | null;
  stale: boolean;
  pending: boolean;
};
export function useMetrics() {
  const [state, setState] = useState<MetricsState>({
    data: null,
    stored: {},
    updatedAt: null,
    failure: null,
    stale: false,
    pending: true,
  });
  const refreshRef = useRef<() => void>(() => {});
  useEffect(() => {
    let active = true;
    let inFlight = false;
    let pollTimer: number | undefined;
    let staleTimer: number | undefined;
    let timeoutTimer: number | undefined;
    let controller: AbortController | undefined;
    let failures = 0;
    let lastManual = -Infinity;
    let resumeRequested = false;
    const available = () =>
      document.visibilityState !== "hidden" && navigator.onLine;
    const clearPoll = () => window.clearTimeout(pollTimer);
    async function request() {
      if (!active || !available() || inFlight) return;
      clearPoll();
      inFlight = true;
      resumeRequested = false;
      controller = new AbortController();
      const current = controller;
      let timedOut = false;
      setState((old) => ({ ...old, pending: true }));
      const timeout = new Promise<never>((_resolve, reject) => {
        timeoutTimer = window.setTimeout(() => {
          timedOut = true;
          current.abort();
          reject(new MetricsRequestError("timeout"));
        }, 5000);
      });
      // Aborting also settles requests while hidden/unmounted, including custom transports.
      const aborted = new Promise<never>((_resolve, reject) => {
        current.signal.addEventListener(
          "abort",
          () =>
            reject(
              new MetricsRequestError(timedOut ? "timeout" : "connection"),
            ),
          { once: true },
        );
      });
      try {
        const data = await Promise.race([
          getMetrics(current.signal),
          timeout,
          aborted,
        ]);
        if (!active || current.signal.aborted || !available()) return;
        failures = 0;
        const stale = data.age_seconds >= 15;
        setState((old) => {
          const stored = { ...old.stored };
          for (const name of resources) {
            const value = data.metrics[name];
            if (value)
              Object.assign(stored, {
                [name]: { value, collectedAt: data.collected_at },
              });
          }
          return {
            data,
            stored,
            updatedAt: new Date().toISOString(),
            failure: null,
            stale,
            pending: true,
          };
        });
        window.clearTimeout(staleTimer);
        if (!stale)
          staleTimer = window.setTimeout(
            () => {
              if (active) setState((old) => ({ ...old, stale: true }));
            },
            (15 - data.age_seconds) * 1000,
          );
      } catch (error) {
        if (!active || (!timedOut && current.signal.aborted)) return;
        failures++;
        setState((old) => ({
          ...old,
          failure: error instanceof MetricsRequestError ? error.kind : "api",
        }));
      } finally {
        window.clearTimeout(timeoutTimer);
        inFlight = false;
        if (active) {
          setState((old) => ({ ...old, pending: false }));
          if (available()) {
            if (resumeRequested) {
              resumeRequested = false;
              void request();
            } else
              pollTimer = window.setTimeout(
                () => void request(),
                Math.min(30000, 5000 * 2 ** Math.max(0, failures - 1)),
              );
          }
        }
      }
    }
    refreshRef.current = () => {
      const now = performance.now();
      if (inFlight || now - lastManual < 1000) return;
      lastManual = now;
      void request();
    };
    function environmentChanged() {
      clearPoll();
      if (!available()) {
        controller?.abort();
        if (!navigator.onLine)
          setState((old) => ({
            ...old,
            failure: "connection",
            pending: false,
          }));
      } else if (inFlight) resumeRequested = true;
      else void request();
    }
    document.addEventListener("visibilitychange", environmentChanged);
    window.addEventListener("online", environmentChanged);
    window.addEventListener("offline", environmentChanged);
    if (available()) void request();
    else
      setState((old) => ({
        ...old,
        pending: false,
        failure: navigator.onLine ? null : "connection",
      }));
    return () => {
      active = false;
      clearPoll();
      window.clearTimeout(staleTimer);
      window.clearTimeout(timeoutTimer);
      controller?.abort();
      refreshRef.current = () => {};
      document.removeEventListener("visibilitychange", environmentChanged);
      window.removeEventListener("online", environmentChanged);
      window.removeEventListener("offline", environmentChanged);
    };
  }, []);
  return { ...state, refresh: () => refreshRef.current() };
}
