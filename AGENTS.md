# InfraWatch 협업 규칙

## 목적과 범위

취업용 개발자 포트폴리오인 서버 통합 모니터링 웹서비스다. Stage 0은 프로젝트 구조, 실행 환경, health 연결과 테스트 기반에 집중한다. 실제 자원 수집, DB, 인증, 다중 서버, 장애 알림, WebSocket을 승인 없이 추가하지 않는다. 가짜 사용률이나 장애 데이터를 실제 값처럼 표시하지 않는다.

## 확인된 구조와 기술

- `backend/`: Python 3.11+, FastAPI/Uvicorn, pytest, Ruff. `app/main.py`의 `create_app()`으로 테스트마다 독립 앱을 만든다.
- `frontend/`: React/TypeScript/Vite, Vitest/Testing Library, ESLint/Prettier. `src/api.ts`가 health 응답을 검증하고 `App.tsx`가 상태를 표시한다.
- 루트: README, AGENTS, .gitignore. 변경 전 실제 파일과 Git 상태를 먼저 확인한다.
- 작성 환경: macOS, Python 3.14.4, Node 24.21.0, npm 11.19.0. 프로젝트 실행 검증은 문서의 실제 결과를 확인하고 수행한다.

## 아키텍처

프론트엔드와 백엔드는 독립 프로세스다. 개발 서버는 127.0.0.1:5173, 백엔드는 127.0.0.1:8000을 사용한다. 프론트엔드의 동일 출처 `/api` 요청을 Vite가 백엔드로 전달한다. 프로덕션은 별도 역방향 프록시가 필요하다. health 응답 계약은 `{"status":"ok","service":"InfraWatch"}`다. UI는 요청 결과와 실제 모니터링 데이터를 구분한다. 단순한 구조를 유지하고 확장 필요성이 확인된 후 모듈을 나눈다.

## 데이터·보안과 기존 기능 보호

- .env, 가상환경, 빌드 결과, 캐시, 로그는 추적하지 않는다. .env.example에는 공개 가능한 예시만 넣는다.
- 토큰, 비밀번호, 개인정보와 실제 서버 주소를 코드·문서·테스트에 넣지 않는다. VITE_ 변수는 공개 값이다.
- 기존 사용자 파일, 미커밋 변경, 정상 기능을 보호한다. 변경이 겹치면 먼저 내용과 의도를 확인한다.
- 내부 예외 상세를 클라이언트에 노출하지 않는다. 민감 데이터 도입 시 로그도 점검한다.
- macOS 설정과 다른 프로젝트의 환경을 바꾸지 않는다. 의존성은 프로젝트 가상환경과 node_modules에만 설치한다.

## 검증

백엔드 디렉터리: `.venv/bin/python -m pytest`, `.venv/bin/python -m ruff check .`, `.venv/bin/python -m ruff format --check .`.
프론트엔드 디렉터리: `npm test`, `npm run build`, `npm run lint`, `npm run format:check`.
실행: 백엔드 `.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload`, 프론트엔드 `npm run dev`.
설치·잠금 절차는 README를 따른다. 직접 의존성 목록과 전이 의존성 잠금 파일을 혼동하지 않는다. 성공을 보고하기 전에 실제 명령 결과를 확인한다. 테스트 정의 수, 실행 수, 성공·실패·skipped 수를 구분한다. 도구 미설치는 테스트 케이스 실패와 구분한다.

## Git 안전

작업 시작과 종료 시 Git 상태를 확인한다. Git 저장소가 없으면 그 사실을 보고한다. 초기화는 사용자 허용 범위와 환경 권한 안에서만 한다. commit, push, force push, reset --hard, 강제 checkout, 사용자 변경 삭제는 명시 승인 없이 수행하지 않는다. .git과 기존 저장소를 덮어쓰거나 권한 제한을 우회하지 않는다. 잠금 파일은 실제 설치·해결 결과로 생성하고 검증 후 포함한다.

## ChatGPT·Codex 협업과 Handoff

ChatGPT는 단계·요구사항 판단을 돕고 Codex는 실제 코드와 실행 결과를 근거로 구현·검증한다. 계획을 실행 사실처럼 보고하지 않는다. 불명확한 요구는 가능한 독립 작업을 진행하면서 확인하고, 중요한 설계 변경은 이유와 영향을 설명한다.
완료 시 사용자가 지정한 ChatGPT Handoff 형식을 사용한다. 목표, 최종 상태, 구현, 설계 판단, 주요 파일, 기존 데이터 영향, 실제 테스트·빌드·실행 결과, 코드상 확인과 미확인 사항, 제한, Git 상태, 측정 여부, 미구현 기능과 추천 다음 작업을 포함한다. 임시 작업 로그나 일회성 TODO를 이 파일에 누적하지 않는다.
