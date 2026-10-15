import { capacity, duration, localTime, type Resource } from "./metrics";
import { useMetrics } from "./useMetrics";

const errors = {
  "not-ready": "첫 데이터 수집 중",
  collection: "전체 수집 실패 · 수집 시간 초과 또는 자원 조회 실패",
  stale: "수집 지연 · 오래된 데이터",
  connection: "메트릭 API 연결 실패",
  timeout: "메트릭 요청 시간 초과",
  api: "메트릭 API 오류",
  invalid: "메트릭 응답 형식 오류",
};
export default function MetricsPanel() {
  const state = useMetrics();
  const label = state.failure
    ? errors[state.failure]
    : state.stale
      ? "수집 지연 · 오래된 데이터"
      : !state.data
        ? "데이터 수신 전"
        : state.data.status === "partial"
          ? "일부 지표 수집 실패"
          : "정상 수집";
  const old = (resource: Resource) =>
    !!state.failure || state.stale || state.data?.metrics[resource] == null;
  const stored = state.stored;
  function note(resource: Resource) {
    const value = stored[resource];
    return old(resource) ? (
      <p className="metric-note error">
        {value
          ? `이전 값 · ${localTime(value.collectedAt)}`
          : state.data?.errors.some((error) => error.resource === resource)
            ? "수집 실패"
            : "수집 데이터 없음"}
      </p>
    ) : null;
  }
  const cpu = stored.cpu?.value;
  const memory = stored.memory?.value;
  const disk = stored.disk?.value;
  const uptime = stored.uptime?.value;
  return (
    <section
      className="metrics-panel"
      aria-labelledby="metrics-title"
      aria-busy={state.pending}
    >
      <div className="metrics-heading">
        <div>
          <p className="eyebrow">LOCAL SYSTEM · LIVE METRICS</p>
          <h2 id="metrics-title">단일 호스트 자원 모니터링</h2>
          <p>
            {state.data
              ? `${state.data.host.label} · ${state.data.host.platform}`
              : "로컬 시스템 · 실제 데이터 대기"}
          </p>
        </div>
        <button onClick={state.refresh} disabled={state.pending}>
          메트릭 새로고침
        </button>
      </div>
      <p
        aria-live="polite"
        data-testid="metrics-state"
        className={
          state.failure || state.stale || state.data?.status === "partial"
            ? "error"
            : !state.data
              ? "loading"
              : "success"
        }
      >
        {label}
        {state.pending ? " · 조회 중" : ""}
      </p>
      <div className="metric-grid">
        <article
          className={old("cpu") ? "metric-card previous" : "metric-card"}
        >
          <h3>CPU 사용률</h3>
          <p className="metric-value">
            {cpu ? `${cpu.usage_percent.toFixed(1)}%` : "—"}
          </p>
          <p>전체 논리 CPU · 1초 구간 평균</p>
          {note("cpu")}
        </article>
        <article
          className={old("memory") ? "metric-card previous" : "metric-card"}
        >
          <h3>메모리</h3>
          <p className="metric-value">
            {memory ? `${memory.usage_percent.toFixed(1)}%` : "—"}
          </p>
          {memory && (
            <p>
              {capacity(memory.used_bytes)} / {capacity(memory.total_bytes)} ·
              가용 {capacity(memory.available_bytes)}
            </p>
          )}
          <p>사용 가능 메모리를 제외한 사용량</p>
          {note("memory")}
        </article>
        <article
          className={old("disk") ? "metric-card previous" : "metric-card"}
        >
          <h3>디스크 · primary</h3>
          <p className="metric-value">
            {disk ? `${disk.usage_percent.toFixed(1)}%` : "—"}
          </p>
          {disk && (
            <p>
              {capacity(disk.used_bytes)} / {capacity(disk.total_bytes)} · 가용{" "}
              {capacity(disk.free_bytes)}
            </p>
          )}
          <p>설정한 파일시스템 · 일반 사용자 가용 공간 기준</p>
          {note("disk")}
        </article>
        <article
          className={old("uptime") ? "metric-card previous" : "metric-card"}
        >
          <h3>시스템 uptime</h3>
          <p className="uptime-value">
            {uptime ? duration(uptime.seconds) : "—"}
          </p>
          <p>시스템 부팅 후 경과 시간</p>
          {note("uptime")}
        </article>
      </div>
      <div className="metrics-times">
        <p>
          마지막 수집:{" "}
          {state.data ? (
            <time dateTime={state.data.collected_at}>
              {localTime(state.data.collected_at)}
            </time>
          ) : (
            "없음"
          )}
        </p>
        <p>
          마지막 데이터 갱신:{" "}
          {state.updatedAt ? (
            <time dateTime={state.updatedAt}>{localTime(state.updatedAt)}</time>
          ) : (
            "없음"
          )}
        </p>
      </div>
      <p className="metric-note">
        자동 갱신은 요청 완료 후 약 5초 간격입니다. 실패 시 최대 30초까지
        대기하며, 백엔드 연결 확인은 위의 ‘다시 확인’ 버튼으로 별도 요청합니다.
      </p>
    </section>
  );
}
