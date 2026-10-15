import { useEffect, useState } from "react";
import { checkHealth } from "./api";
import MetricsPanel from "./MetricsPanel";

type Status = "loading" | "success" | "error";
const labels: Record<Status, string> = {
  loading: "연결 중",
  success: "연결 성공",
  error: "연결 실패",
};

export default function App() {
  const [status, setStatus] = useState<Status>("loading");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    const timeout = window.setTimeout(() => controller.abort(), 5000);
    checkHealth(controller.signal)
      .then(() => {
        if (active) setStatus("success");
      })
      .catch(() => {
        if (active) setStatus("error");
      })
      .finally(() => window.clearTimeout(timeout));
    return () => {
      active = false;
      controller.abort();
      window.clearTimeout(timeout);
    };
  }, [attempt]);
  function retry() {
    setStatus("loading");
    setAttempt((value) => value + 1);
  }
  return (
    <main>
      <header>
        <a className="brand" href="/">
          ◉ InfraWatch
        </a>
        <span className="stage">STAGE 1 · LOCAL MONITORING</span>
      </header>
      <section className="intro">
        <p className="eyebrow">INFRASTRUCTURE OBSERVABILITY</p>
        <h1>
          서버의 상태를,
          <br />
          한눈에.
        </h1>
        <p className="description">
          여러 서버의 자원 상태와 장애 이력을 한곳에서 살펴보기 위한
          <br className="desktop" /> 서버 통합 모니터링 프로젝트입니다.
        </p>
      </section>
      <section className="connection" aria-labelledby="connection-title">
        <div>
          <p className="eyebrow">API CONNECTION</p>
          <h2 id="connection-title">백엔드 연결 상태</h2>
          <p>FastAPI 서비스의 응답을 확인합니다.</p>
        </div>
        <div className="connection-action">
          <p role="status" aria-live="polite" className={`status ${status}`}>
            <span aria-hidden="true">●</span> {labels[status]}
          </p>
          <button onClick={retry} disabled={status === "loading"}>
            다시 확인
          </button>
        </div>
        {status === "error" && (
          <p className="error-help">
            백엔드 실행 여부와 API 주소를 확인한 후 다시 시도해 주세요.
          </p>
        )}
      </section>
      <MetricsPanel />
      <section className="foundation">
        <h2>모니터링을 위한 첫 기반</h2>
        <p>
          현재 실행 중인 로컬 시스템의 실제 자원을 확인합니다. 다중 서버 수집과
          장애 알림은 이후 단계에서 제공합니다.
        </p>
        <div className="steps">
          <article>
            <span>01 / 현재</span>
            <h3>실행 기반</h3>
            <p>분리된 앱 구조와 연결 확인</p>
          </article>
          <article>
            <span>02 / 현재</span>
            <h3>자원 수집</h3>
            <p>CPU · 메모리 · 디스크 · uptime</p>
          </article>
          <article>
            <span>03 / 예정</span>
            <h3>장애 분석</h3>
            <p>감지 · 알림 · 이력 탐색</p>
          </article>
        </div>
      </section>
      <footer>
        InfraWatch <span>개발자 포트폴리오 프로젝트</span>
      </footer>
    </main>
  );
}
