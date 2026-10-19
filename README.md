# InfraWatch

여러 서버의 CPU, 메모리, 디스크, 네트워크 상태를 수집하고 실시간 대시보드, 장애 감지·알림 및 장애 이력 분석을 제공하기 위한 서버 통합 모니터링 웹서비스입니다.

System Engineer · IDC 운영 · DevOps 직무를 목표로 하는 개발자 포트폴리오입니다. API 설계, 테스트, 운영 관측과 단계적인 제품 개발 과정을 보여주는 것이 목적입니다. 현재 Stage 1은 로컬 시스템의 실제 CPU·메모리·디스크·uptime을 표시합니다. Stage 0은 실행 구조와 API 연결 기반을 마련한 이전 단계이며, 가짜 운영 수치나 장애 데이터는 표시하지 않습니다.

## Stage 2A까지의 범위

| 구분 | 구현 상태 |
| --- | --- |
| Stage 1 완료 | FastAPI health·metrics API, React 화면, 실제 CPU·메모리·디스크·uptime 수집, 기본 5초 수집·요청 완료 후 5초 갱신, 부분 실패·stale 처리 |
| Stage 2A 완료 | PostgreSQL 연결 기반, 서버 UUID 등록·조회, 저장 스키마·제약·인덱스, Alembic migration, 독립 DB 테스트 도구 |
| Stage 2B 미구현 | 메트릭 자동 DB writer, 메모리 큐·저장 재시도 |
| Stage 2C 미구현 | 과거 이력 조회 API, React 이력 그래프 |
| 후속 미구현 | 다중 Linux 서버 수집, 자동 장애 알림, 운영 배포, 자동 삭제·백업 복원 |

실행 구조는 브라우저 → Vite 개발 서버의 `/api` 프록시 → FastAPI → psutil 수집 캐시입니다. PostgreSQL은 명시적인 CLI·테스트 경계에서만 사용합니다. 프론트엔드와 백엔드는 독립 프로세스이며 프로덕션에서는 별도 역방향 프록시가 필요합니다. 인증 없는 로컬 단일 worker 범위로, 운영 환경 지원 완료를 의미하지 않습니다.

설계·과거 검증 기록은 `docs/`에 보존했습니다. 아래 과거 기록은 당시 결과이며 공개 준비 과정의 최신 검증과 구분합니다.

## 공개 준비 검증 (2026-10-19)

별도 공개용 복사본에서 잠금 파일로 새 가상환경 설치와 `npm ci`를 실행했습니다. 기능 코드는 원본과 바이트 단위로 동일합니다. 과거 검증 문서는 수정하지 않았습니다.

| 검사 | 이번 실제 결과 |
| --- | --- |
| 백엔드 기본 pytest | 함수 선언 45개 → 93 cases 수집, 59 passed / 0 failed / 34 skipped |
| Stage 1 OS 실측 | 샌드박스 uptime 제한으로 최초 1 failed, 일반 사용자 권한 재실행 1 passed |
| 백엔드 고유 case 기준 | 60 passed / 최종 미해결 실패 0 / PostgreSQL 33 cases 미실행; 반복 실행을 더하지 않음 |
| Stage 1 회귀 | 기존 48 cases 중 기본 47개와 별도 OS 실측 1개 통과 |
| Stage 2A | 비DB 12 cases 통과; 실제 PostgreSQL 33 cases는 실행 파일 부재로 skipped |
| DB migration | 오프라인 SQL 생성 통과; 실제 DB upgrade·재시작 보존 검사는 이번에 미실행 |
| pip check / Ruff check·format | 모두 통과, Python 15개 파일 포맷 일치 |
| 프론트엔드 Vitest | 선언 호출 30개 → 43 cases 실행, 43 passed / 0 failed / 0 skipped |
| TypeScript / ESLint / Prettier | 모두 통과 |
| Production build | 통과, 33 modules, JS 197.69 kB / gzip 63.25 kB |
| npm audit 전체 / 운영 의존성 | 각각 취약점 0개 |

백엔드 기본 실행의 DeprecationWarning 38개는 남아 있습니다. Debug 전용 빌드 명령은 없으며 개발 서버·브라우저 UI는 이번에 재실행하지 않았습니다. 과거 PostgreSQL 18.6 전체 93 passed 기록은 [Stage 2A 검증 문서](docs/stage2a-implementation.md)에 보존했으며 이번 결과와 구분합니다.

독립 DB 검증이 필요한 경우 PostgreSQL 18 실행 파일을 준비한 뒤 아래 명령을 사용합니다. 기존 사용자 DB에 연결하지 않고 새 임시 클러스터를 만들며, 종료 후 파일은 보존합니다.

```sh
cd backend
.venv/bin/python scripts/run_db_tests.py --pg-bin /path/to/postgresql18/bin --all
```

## Stage 1 구현 상태 (2026-10-14)

psutil 7.2.2 기반 로컬 CPU·메모리·단일 파일시스템·uptime 수집과 `GET /api/metrics`, React 대시보드를 구현했습니다. 기존 `/api/health` 계약과 수동 ‘다시 확인’은 유지합니다. 아래 Stage 0 및 설계 단계 내용은 이전 검증 이력으로 보존합니다.

- CPU: 전체 논리 CPU의 1초 평균. 메모리 사용량: `total - available`.
- 디스크: 기본 `/`가 속한 단일 파일시스템. macOS APFS에서는 표시 사용률이 `used / total`과 다를 수 있습니다.
- 백엔드: 시작 즉시 첫 수집, 기본 5초 간격, 캐시 조회 API, 항목별 부분 실패, 3초 수집 timeout 및 15초 이상 stale.
- 화면: 요청 완료 후 5초 polling, 5초 요청 timeout, 실패 backoff 최대 30초, 중복 요청·언마운트·숨긴 탭·오프라인 처리. 과거 값은 원래 시각과 함께 ‘이전 값’으로 표시합니다.
- Stage 1 구현 당시 검증 기록: pytest 기본 47 passed / 1 skipped, 실측 포함 전체 48 passed / 0 skipped; Vitest 43 passed. 기존 테스트 9개를 보존했습니다. typecheck·lint·format·build·pip check 및 전체/운영 npm audit(0개)을 확인했습니다.

설계 원본은 [Stage 1 설계](docs/stage1-design.md)에 그대로 보존했고, 실제 결과와 차이·제한은 [Stage 1 구현 및 검증](docs/stage1-implementation.md)에 기록합니다. Stage 1 변경은 아래 기준점 커밋으로 보존했습니다. 당시 Stage 2 문서 작업에서는 테스트·빌드·실측을 재실행하지 않았습니다.

[Stage 2 설계](docs/stage2-design.md)는 PostgreSQL 이력 저장·기간 조회·과거 그래프의 계획입니다. 설계 작성 당시 DB 설치·생성 및 기능 구현은 하지 않았습니다. 이후 2A 구현은 다음 절에서 구분합니다.

## Stage 2A DB 기반 구현

Stage 1 기준점은 `279c7904ed3384d8b644ce5ca0673aa811e18a13`입니다. PostgreSQL 연결·SQLAlchemy Core 저장 모델·명시적 Alembic migration·서버 UUID 등록/조회·독립 DB 검증 도구를 추가했습니다. DB는 기본 비활성이며 기존 앱 시작과 health/metrics 요청은 DB에 접속하지 않습니다. **실제 메트릭 writer·이력 조회·그래프는 아직 없습니다.**

구체적인 연결 설정·최소 권한·명시적 명령·독립 테스트 및 제한은 [Stage 2A 구현 기록](docs/stage2a-implementation.md)을 참고하세요. 기존 Stage 1 및 Stage 2 설계 문서의 ‘당시 미구현·미커밋’ 설명은 작성 당시 이력입니다. Stage 2A는 커밋으로 보존되어 있습니다. 공개용 이력은 개인 이메일을 GitHub noreply 주소로 바꾼 별도 복사본이며, 문서에 남아 있는 원본 커밋 해시는 원본의 검증 이력을 가리킵니다.

### 수집 설정과 실행 제약

기존 설치·실행 명령을 사용합니다. backend는 shell 환경의 `INFRAWATCH_HOST_ID`(기본 `local`), `INFRAWATCH_HOST_LABEL`(기본 `Local system`), `INFRAWATCH_DISK_PATH`(macOS 기본 `/`)를 읽습니다. `.env.example`은 예시이고 파일을 자동 로딩하지 않습니다. 설정 변경 후 백엔드를 재시작하세요. 별칭에는 공개 가능한 이름만 넣습니다. API 응답에는 실제 호스트명·사용자명·디스크 경로가 없습니다.

Uvicorn 수집 worker는 **1개만** 사용합니다. `--reload`의 watcher는 수집하지 않으며 서버 자식 프로세스의 lifespan이 수집기를 관리합니다. 다중 worker에서는 각 프로세스의 캐시·수집기가 분리되므로 지원하지 않습니다. 인증 없는 로컬 개발 범위이며 127.0.0.1 바인딩을 유지합니다.

```sh
curl --fail http://127.0.0.1:8000/api/metrics
# 시작 직후 첫 수집 전에는 HTTP 503 METRICS_NOT_READY일 수 있습니다.

cd backend
# Mock 기반 검사 및 기존 회귀: OS 실측 1개는 기본 skipped
.venv/bin/python -m pytest
# 일반 macOS 터미널에서 실제 OS 측정까지 포함
INFRAWATCH_RUN_LIVE_TESTS=1 .venv/bin/python -m pytest
```

macOS 샌드박스에서는 psutil boot_time 조회가 PermissionError로 차단될 수 있습니다. 이 경우 uptime을 0으로 대체하지 않고 부분 실패로 표시합니다. Stage 1 구현 당시 일반 사용자 실행에서는 네 자원을 모두 실제 수집했습니다. OS syscall이 영구 정지하면 스레드를 강제 종료할 수 없다는 제한이 있습니다.

## Stage 0 및 설계 단계 검증 이력

2026-10-14 Stage 0 최종 안정화를 완료했습니다. Vite 7.1.7 → 7.3.7, Vitest 3.2.4 → 4.1.11, typescript-eslint 8.44.1 → 8.71.2를 업데이트하고 잠금 파일 기반 `npm ci` 재설치까지 확인했습니다. 최종 전체·운영 npm audit은 모두 **0개**이며, 실제 Safari에서 연결 성공 → 백엔드 중단 후 다시 확인 → 연결 실패 → 백엔드 재시작 후 재시도 → 연결 성공 복구를 확인했습니다.

기존 pytest 3개와 Vitest 6개, pip check, Ruff, TypeScript, ESLint, Prettier 및 production build가 다시 통과했습니다. pytest의 DeprecationWarning 6개는 Starlette의 AnyIO 별칭과 FastAPI의 asyncio.iscoroutinefunction 호출에서 발생하며 억제하지 않았습니다. 후자는 Python 3.16 전 호환성 유지보수가 필요합니다. 상세 위험·패키지별 대응·집계 차이·브라우저 검증·제한은 [최종 안정화 기록](docs/stage0-stabilization.md)을 참고하세요. 당시 환경에서 Stage 0은 종료 가능하다고 판단했으며, 해당 안정화 작업에서는 Stage 1 기능을 추가하지 않았습니다.

### Git 기준점과 Stage 1 설계 당시 이력

Stage 0을 `main`의 최초 로컬 커밋 `701b2e934569d3cb327fa913a619296c18eedfcc` (`chore: establish InfraWatch stage 0 baseline`)으로 확정했습니다. 소스·잠금 파일·필수 문서 29개를 포함했고 커밋 전 테스트·품질 검사·빌드가 다시 통과했습니다. 원격 push는 하지 않았습니다.

[Stage 1 설계](docs/stage1-design.md)는 로컬 시스템의 CPU·메모리·단일 파일시스템·uptime·수집 시각과 공개 호스트 별칭을 다룹니다. 기존 `/api/health`와 수동 연결 확인은 유지하고, 새 `/api/metrics`는 5초 주기 수집 스냅샷을 조회하도록 설계했습니다. CPU는 1초 평균, 메모리는 `total - available` 기준이며 메트릭 화면의 자동 갱신·오류·중복 요청 방지를 health와 분리합니다. 이 설계 작성 당시에는 psutil 설치와 Stage 1 기능 구현을 진행하지 않았습니다. 이후 구현·검증은 상단의 현재 상태와 구현 문서를 참고하세요. Stage 1 설계·구현 변경은 당시 미커밋이었으며 이후 아래 Stage 1 기준점으로 보존했습니다.

### 이전 검증 이력 (2026-10-13)

2026-10-13 macOS에서 의존성 설치, 잠금 파일 생성 및 재설치, 전체 테스트·품질 검사·production build를 검증했습니다. PyPI와 npm 레지스트리는 당시 Codex 세션에서 모두 HTTP 200을 반환했습니다. Python 3.14.4에서 설치·pytest·Uvicorn 실행이 성공했습니다.

백엔드 및 Vite 프록시의 `/api/health`는 HTTP 200과 계약 JSON을 반환했고, Safari에서 연결 중 → 연결 성공을 확인했습니다. 백엔드 중단 시 프록시 HTTP 500은 확인했으나, 브라우저 제어 도구 오류와 활성 창 변경으로 실제 UI의 연결 실패 → 재시도 복구 확인은 남아 있습니다. 당시에는 이 항목이 미완료였으며, 위 2026-10-14 검증에서 완료했습니다.

Git 저장소는 `.git` 쓰기 권한 승인 후 초기화했습니다. commit·push는 하지 않았습니다. 설치 과정에서 npm은 취약점 13개(중간 1, 높음 10, 치명적 2)를 보고했고 별도 `npm audit --json`은 15개(중간 3, 높음 10, 치명적 2)를 보고했습니다. 감사 결과와 설치 요약의 집계 차이를 그대로 기록하며, 강제 업데이트는 하지 않았습니다. 당시 남긴 보안 검토 항목은 위 최종 안정화에서 처리했습니다.

## 기술 스택

- 백엔드: Python 3.11 이상, FastAPI, Uvicorn, psutil 7.2.2, pytest, Ruff
- DB 기반: PostgreSQL 18, SQLAlchemy Core 2.0.54, psycopg 3.3.6, Alembic 1.20.0
- 프론트엔드: Node.js 22.12 이상, React, TypeScript, Vite, Vitest, Testing Library
- 품질 검사: ESLint, Prettier
- 향후: Docker Compose, 과거 그래프용 라이브러리(구현 시 선정), 필요 시 WebSocket

작성 시 확인한 macOS 도구는 Python 3.14.4, Node.js 24.21.0, npm 11.19.0입니다. 시스템 설정은 변경하지 않습니다.

## 구조

아래는 Stage 0 기반의 구조 요약입니다. Stage 2A는 `db.py`·`schema.py`·`servers.py`·`database_cli.py`, `migrations/`, 독립 DB 테스트를 추가했습니다. Stage 1은 `backend/app/metrics.py`, 메트릭 테스트, `frontend/src/MetricsPanel.tsx`·`useMetrics.ts`·`metrics.ts` 등을 추가했습니다.

```text
InfraWatch/
├── backend/
│   ├── app/main.py          # 앱 팩토리, health API, 오류 처리
│   ├── tests/test_health.py
│   ├── pyproject.toml       # 의존성·테스트·Ruff 설정
│   ├── requirements.in     # 고정된 직접 의존성
│   └── .env.example
├── frontend/
│   ├── src/                # 화면, health 요청, 테스트
│   ├── vite.config.ts      # localhost 및 개발 API 프록시
│   ├── package.json
│   └── .env.example
├── README.md
├── AGENTS.md
└── .gitignore
```

## 처음 설치하기

Git, Python 3.11 이상, Node.js 22.12 이상이 필요합니다. 실제 검증 환경은 macOS arm64 / Python 3.14.4 / Node.js 24.21.0입니다. PostgreSQL 없이도 실시간 화면을 실행할 수 있습니다.

```sh
git clone https://github.com/diz99-art/InfraWatch.git
cd InfraWatch
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.lock
cd frontend
npm ci
cd ..
```

이후 명령의 프로젝트 루트는 방금 복제한 `InfraWatch` 폴더입니다. 터미널 두 개에서 아래 백엔드와 프론트엔드를 각각 실행하세요. `.env` 파일은 자동으로 읽지 않으므로 기본 설정에서는 복사할 필요가 없습니다.

`requirements.in`·`package.json`은 직접 의존성 목록이고, `requirements.lock`·`package-lock.json`은 전이 의존성까지 고정한 설치 기준입니다. 일반 설치에서는 잠금 파일을 다시 생성하지 않습니다. 의존성 변경 시에만 설치·해결 결과로 갱신하고 검증합니다. 다른 Python 버전·플랫폼은 별도 설치 검증이 필요합니다.

## PostgreSQL 설정과 migration

DB는 기본 비활성입니다. Stage 2A는 연결·저장 스키마·서버 UUID 등록 기반이며 **수집 메트릭을 DB에 자동 저장하지 않습니다.** 기존 앱과 health/metrics API는 DB에 접속하지 않습니다.

1. PostgreSQL 18을 별도로 준비하고, 관리자가 InfraWatch 전용 빈 DB와 migration·등록·runtime 역할을 준비합니다. 기존 사용자 DB를 초기화하거나 공유 DB 권한을 일괄 변경하지 마세요. 역할별 최소 권한은 [Stage 2A 운영 경계](docs/stage2a-implementation.md#최소-권한)를 따릅니다.
2. `backend` 디렉터리에서 `INFRAWATCH_DB_ENABLED=1`을 export하고, 비공개 셸 환경에 `INFRAWATCH_DATABASE_URL`을 설정합니다. SQLAlchemy 드라이버는 `postgresql+psycopg`이며 사용자·호스트·DB 이름이 필요합니다. query 옵션은 지원하지 않습니다. 실제 접속 문자열을 문서·명령 이력·VITE_ 변수에 기록하지 마세요.
3. migration 역할의 환경에서 대상 DB를 확인한 뒤 아래 명령을 실행합니다.

```sh
cd backend
# DB에 접속하지 않고 migration SQL만 확인
.venv/bin/python -m alembic upgrade head --sql
# 전용 DB와 migration 역할의 비공개 환경이 준비된 경우에만 실행
.venv/bin/python -m app.database_cli upgrade
.venv/bin/python -m app.database_cli check
```

현재 revision은 `0001_stage2a`입니다. migration은 명시적으로 실행하며 앱 시작 시 자동 실행하지 않습니다. 동일 head에 재실행할 수 있고 downgrade는 데이터 손실 방지를 위해 거부합니다.

서버 등록은 등록 역할로 전환한 뒤 실행합니다. `--server-id`에는 한 번 생성해 보존한 UUID를 사용합니다. 전체 인수는 `.venv/bin/python -m app.database_cli register --help`로 확인하고, 조회는 `.venv/bin/python -m app.database_cli lookup --public-id local`을 사용합니다. UUID·별칭 충돌은 자동 덮어쓰지 않습니다. 운영 TLS·백업 복원·실제 부하 검증은 남아 있습니다.

## 실행

터미널 1 — 프로젝트 루트:

```sh
cd backend
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

터미널 2 — 프로젝트 루트:

```sh
cd frontend
npm run dev
```

브라우저에서 <http://127.0.0.1:5173>을 엽니다. API 문서는 <http://127.0.0.1:8000/docs>입니다. 종료는 각 터미널에서 Ctrl+C입니다.

```sh
curl --fail http://127.0.0.1:8000/api/health
# 기대 응답: {"status":"ok","service":"InfraWatch"}
curl --fail http://127.0.0.1:5173/api/health
# 개발 프록시를 거쳐 같은 응답을 기대합니다.
```

화면은 연결 중 → 연결 성공 또는 연결 실패를 구분합니다. 요청 제한 시간은 5초이고, 다시 확인 버튼으로 재요청합니다. 백엔드를 종료한 다음 다시 확인하면 실패 상태를 검증할 수 있습니다. 연결 상태는 마지막 요청 결과이며 자동 갱신하지 않습니다. health는 앱 생존 확인이며 서버 자원이나 DB 준비 상태를 확인하지 않습니다.

### 환경 변수

`frontend/.env.example`을 `frontend/.env`로 복사할 수 있습니다.

- `API_PROXY_TARGET`: 개발 프록시 대상. 기본 `http://127.0.0.1:8000`.
- `VITE_API_BASE_URL`: 브라우저 요청의 기본 URL. 기본 빈 문자열로 동일 출처 `/api/health` 호출.
- `VITE_` 값은 공개 번들에 포함되므로 비밀번호·토큰을 넣지 않습니다.
- 환경 변수 변경 후 Vite를 재시작합니다.

백엔드의 `.env.example`은 Uvicorn 셸 변수 예시입니다. 자동 로딩하지 않으며 필요하면 `export UVICORN_HOST=127.0.0.1` 등으로 설정합니다. 위 실행 명령의 CLI 옵션이 우선합니다.

개발은 Vite 프록시로 동일 출처를 유지해 CORS 설정이 필요 없습니다. 직접 다른 출처로 요청하려면 명시적인 CORS 정책이 필요하며 현재 구현하지 않았습니다. 프로덕션 배포에서는 `/api`를 백엔드로 전달하는 역방향 프록시를 별도로 구성해야 합니다. Vite 개발 프록시는 배포 번들의 일부가 아니고 `npm run preview`에서도 API 프록시를 제공하지 않습니다.

## 테스트·빌드·품질 검사

프로젝트 루트:

```sh
cd backend
.venv/bin/python -m pytest
.venv/bin/python -m pip check
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
cd ../frontend
npm test
npm audit
npm audit --omit=dev
npm run typecheck
npm run build
npm run lint
npm run format:check
```

포맷 수정은 백엔드에서 `.venv/bin/python -m ruff format .`, 프론트엔드에서 `npm run format`입니다. 생성 번들은 `frontend/dist/`이며 `npm run preview`로 정적 화면만 미리 볼 수 있습니다. Debug/Release 구분 대신 개발 서버와 프로덕션 빌드를 사용합니다.

Stage 0 당시 테스트 정의는 백엔드 3개(정상 health, 404, 내부 오류 비공개), 프론트엔드 6개(대기, 성공, 네트워크 오류·재시도, HTTP 오류, 잘못된 응답, 시간 초과)입니다. 실제 수집·실행 결과는 pytest 3 passed / 0 failed / 0 skipped, Vitest 6 passed / 0 failed / 0 skipped입니다. 당시 신규 테스트는 없었습니다. Stage 1은 백엔드 함수 26개/48 cases, 프론트엔드 선언 호출 30개/43 cases로 확장됐으며 결과·skipped 구분은 상단과 구현 문서에 기록돼 있습니다. 반복 검증은 서로 다른 테스트 수에 합산하지 않습니다.

아래는 Stage 0 검증 이력입니다. `pip check`, Ruff check 및 format check, TypeScript, ESLint, Prettier, production build가 통과했습니다. 최초 Prettier 검사에서 10개 파일의 포맷 오류가 발견되어 공식 포맷 명령으로 수정하고 재검사했습니다. 앱과 테스트의 동작은 변경하지 않았습니다. pytest는 전이 의존성과 FastAPI에서 DeprecationWarning 6개를 보고했습니다. 현재 환경의 통과는 모든 Python 버전·플랫폼의 호환성을 보장하지 않습니다.

## 안정화 당시 확인 절차 (이력)

아래는 Stage 0 당시 절차이며 현재 재실행 지시가 아닙니다. 저장소는 이미 초기화됐고 잠금 파일도 존재합니다. 기존 저장소를 재초기화하거나 잠금 파일을 이유 없이 다시 생성하지 않습니다.

1. 네트워크 접근이 가능한 실행 환경에서 `curl -I https://pypi.org/simple/fastapi/`와 `curl -I https://registry.npmjs.org/react`로 연결을 확인합니다. TLS 오류가 나면 해당 원인을 조사하고 인증서 검증은 끄지 않습니다.
2. 위 설치 절차로 의존성을 설치합니다. Python 3.14에서 설치 오류가 있으면 정확한 패키지와 오류를 기록하고 지원 버전을 확인합니다.
3. 테스트·TypeScript·lint·format·빌드를 실행합니다. 실제 포맷 오류가 있으면 제공된 포맷 명령으로 수정한 뒤 다시 검사합니다.
4. Uvicorn과 Vite를 별도 터미널에서 실행합니다. 백엔드와 개발 프록시 health 주소 모두 HTTP 200 및 예상 JSON인지 확인합니다.
5. 브라우저에서 연결 성공을 확인합니다. 백엔드를 Ctrl+C로 종료하고 다시 확인 버튼을 눌러 연결 실패를 확인합니다. 백엔드를 다시 시작하고 버튼을 눌러 성공으로 복구되는지 확인합니다. 이 검증은 Vitest의 fetch 모킹 테스트와 별개입니다.
6. 의존성 해결이 성공한 환경에서 잠금 파일을 생성하고 `pip check` 및 잠금 파일 기반 재설치를 확인합니다.
7. 프로젝트 루트에서 `git init` 후 `git status --short`, `git diff --check`를 실행합니다. commit·push는 수행하지 않습니다. 비밀정보 제외 규칙은 추적 전 파일에 적용되며 이미 추적한 비밀은 별도 처리가 필요합니다.

프로젝트 저장소에서 `git check-ignore --no-index`로 `.env`, 가상환경, 캐시, node_modules, dist, 로그, AWS 자격증명과 키 파일 제외를 확인했습니다. `.env.example`과 잠금 파일은 제외되지 않습니다. 이 내용은 안정화 검증 당시의 상태이며, 현재는 위 Git 기준점으로 소스와 필수 문서를 추적합니다.

## 현재 구현

- 독립 FastAPI 앱 팩토리와 `GET /api/health`, 캐시 기반 `GET /api/metrics`
- HTTP 오류 및 내부 오류 JSON 응답, 내부 오류 상세는 응답에서 숨김
- 반응형 InfraWatch 화면과 API 연결 상태, 제한 시간, 재시도
- 실제 로컬 자원 수집, 부분 실패·stale 처리 및 자동 갱신 메트릭 패널
- localhost 실행 설정, 테스트 정의, 환경 예시 및 민감 파일 제외 규칙

로그에는 내부 예외가 포함될 수 있으므로 향후 실제 데이터가 추가되면 민감정보 마스킹을 검토해야 합니다. DB 연결·저장 스키마·명시적 migration·서버 UUID 등록/조회는 구현되어 있습니다. 수집 메트릭의 자동 DB 저장은 없으며 최신 값과 화면의 이전 값은 메모리 상태입니다.

## 로드맵

1. Stage 0 완료: 실제 Safari 장애 복구·안전한 의존성 업데이트·전체 회귀 확인. 후속 유지보수는 FastAPI/Starlette 경고 해결 및 개발 도구 지원 버전 검토.
2. Stage 1 구현·검증 완료: macOS 로컬 단일 worker 범위. [설계 원본](docs/stage1-design.md)과 [구현·검증 기록](docs/stage1-implementation.md). 기준점 `279c7904ed3384d8b644ce5ca0673aa811e18a13`으로 보존.
3. Stage 2A: [DB 기반 구현](docs/stage2a-implementation.md). [전체 설계](docs/stage2-design.md)의 2A 범위만 구현하며 실제 writer·큐·조회 API·과거 그래프·자동 삭제·백업 복구는 후속 범위입니다.
4. 후속 대시보드 확장: 집계·장기 보존과 필요성 검토 후 WebSocket. Docker Compose는 필요 시 별도 검토.
5. 운영 기능: 다중 서버 관리, 인증, 장애 감지·알림·이력 분석.

## 설계 참고

안정화 과정에서 `loadEnv`를 `vite`에서 가져오도록 수정했습니다. 설정 API는 [Vite 설정 문서](https://vite.dev/config/)와 [Vitest 설정 문서](https://vitest.dev/config/)를 참고했습니다. 개발 프록시는 [Vite 공식 서버 옵션](https://vite.dev/config/server-options), 앱 테스트와 오류 처리는 [FastAPI 테스트](https://fastapi.tiangolo.com/tutorial/testing/) 및 [오류 처리 문서](https://fastapi.tiangolo.com/tutorial/handling-errors/)를 참고했습니다.
