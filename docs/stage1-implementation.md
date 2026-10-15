# Stage 1 구현 및 검증 결과

2026-10-14 macOS arm64 / Python 3.14.4 / psutil 7.2.2 / Node 24.21.0 / npm 11.19.0에서 검증했습니다. 기준 커밋은 `701b2e934569d3cb327fa913a619296c18eedfcc`, 브랜치는 main입니다. 이번 구현은 미커밋이며 commit·push·stage·reset을 수행하지 않았습니다.

## 구현

- `backend/app/metrics.py`: strict·frozen Pydantic 모델, 읽기 전용 psutil 수집기, 일반 사용자 공개 별칭·단일 디스크 대상 설정, 단일 executor 스레드 수집 서비스와 immutable 최신 스냅샷.
- `backend/app/main.py`: 앱마다 독립 서비스 생성, FastAPI lifespan 시작·종료, `GET /api/metrics`, 기존 health 및 404/500 계약 유지.
- `frontend/src/metrics.ts`, `api.ts`: TypeScript 계약과 unknown 응답 검증. 숫자·범위·정수·UTC 날짜·부분 실패 상태의 일관성 확인.
- `useMetrics.ts`, `MetricsPanel.tsx`: CPU·메모리·디스크·uptime 카드, 공개 별칭·플랫폼, 수집 시각과 마지막 유효 데이터 수신 시각, 수동 갱신·자동 polling·backoff·timeout·취소·과거 값 관리.
- `App.tsx`, `styles.css`: 기존 health 카드에 독립 메트릭 패널을 연결하고 Stage 1 현재 상태 문구·반응형 스타일 반영.

DB·실측 이력 저장·원격 수집·인증·알림·Docker·CI/CD·Kubernetes는 추가하지 않았습니다. 화면 숫자는 메트릭 API의 검증된 실제 값에서만 옵니다. `metrics-fixture.ts`는 테스트 전용이며 production 코드가 가져오지 않습니다.

## 계약·수집 정책·설계 판단

설계 원본 [stage1-design.md](stage1-design.md)는 작업 시작 시 파일과 byte 단위로 동일하게 보존했습니다. README의 기존 사용자 문단·Git 기준점·계획은 이력으로 보존하고 현재 구현 안내를 추가했습니다.

기존 `GET /api/health`는 `{"status":"ok","service":"InfraWatch"}`이며 자동 호출을 추가하지 않았습니다. 새 `/api/metrics`의 schema_version은 1입니다. 정상·부분 성공은 HTTP 200, 실패 항목은 null/errors입니다. 미수집·전체 실패·수집 timeout·stale는 503과 고정 reason, no-store 및 Retry-After: 5를 제공합니다. 예기치 않은 API 오류는 기존 500 JSON 형태이며 예외 상세는 숨깁니다.

CPU는 `cpu_percent(interval=1.0, percpu=False)`의 전체 논리 CPU 1초 평균과 실제 monotonic 호출 경과 ms입니다. 메모리 used는 total-available이며 원시 OS used나 total-free와 혼동하지 않습니다. 용량 API 단위는 bytes 정수, 화면 단위는 GiB입니다. percent·age는 소수 1자리, uptime은 정수 초, 수집 시각은 UTC 밀리초 Z입니다. 잘못된 측정값을 0·100으로 clamp하거나 문자열·boolean 숫자로 바꾸지 않습니다.

수집 시작 목표 간격은 5초이며 API는 캐시만 읽습니다. 항목별 실패는 다른 항목을 훼손하지 않습니다. 3초 논리적 timeout 이후에도 실제 작업이 종료될 때까지 기다려 중복 작업·누적 큐를 만들지 않고 늦은 결과를 버립니다. 정상 shutdown은 loop를 멈추고 실행 중 작업과 executor를 정리합니다. OS syscall의 영구 정지는 스레드 강제 취소로 해결할 수 없으며 네트워크 파일시스템은 지원 대상이 아닙니다.

사용자 요구의 ‘15초 이상’을 우선해 age **>=15초**에서 stale로 판정했습니다. 설계 원문의 >15초 표현과 경계에서만 다르며 자동 테스트가 정확히 15초를 검증합니다. 클라이언트도 같은 경계이며 응답 age에 대한 timer로 다음 성공 응답이 없어도 과거 값 상태를 표시합니다.

프런트엔드는 유효 응답 완료 후 5초, 실패 후 5/10/20/30초 대기하고, 유효 200에서 backoff를 초기화합니다. 요청 timeout은 5초입니다. setTimeout 한 개·in-flight guard·수동 요청 1초 guard를 사용합니다. unmount/hidden/offline에서는 요청·예약을 정리하고, visible/online에서 다시 시작합니다. StrictMode의 이전 effect 응답도 현재 상태를 덮어쓰지 못합니다.

마지막 데이터 갱신 시각은 **유효 응답을 받은 시각**이며 실패한 요청 시각으로 바꾸지 않습니다. 자원별 마지막 유효 값과 원래 수집 시각을 따로 보관해 부분 실패도 과거 값을 최신 시도에 섞지 않습니다. HTTP 프록시 500은 ‘메트릭 API 오류’, 실제 네트워크 거부는 ‘메트릭 API 연결 실패’, 503은 수집 상태로 구분합니다.

보안을 위해 기존 global 예외 logger의 exc_info를 제거하고, metrics endpoint는 예상 밖 오류를 경계에서 고정 500 응답으로 변환해 ASGI가 민감 예외를 다시 로깅하지 않도록 했습니다. 정상 health 계약에는 영향이 없지만 내부 traceback 기반 디버깅 정보는 줄어듭니다. 경고 억제나 프레임워크 업데이트는 하지 않았습니다.

## 실제 HTTP·OS 측정

직접 FastAPI 및 Vite `/api` 프록시에서 health HTTP 200과 기존 JSON, metrics HTTP 200과 status ok를 확인했습니다. [stage1-live-sample.json](stage1-live-sample.json)은 **실제 HTTP 측정 응답**으로, 테스트 fixture나 예시값이 아닙니다.

수집 시각: `2026-10-14T02:29:14.797Z`.

| 항목                   |                      실제 값 |
| ---------------------- | ---------------------------: |
| CPU 사용률 / 호출 경과 |               97.9% / 1002ms |
| 메모리 total           |            17179869184 bytes |
| 메모리 available       |             4320837632 bytes |
| 메모리 used / 사용률   |    12859031552 bytes / 74.8% |
| 디스크 total           |           494384795648 bytes |
| 디스크 used            |            12457340928 bytes |
| 디스크 free / 사용률   |    118526169088 bytes / 9.5% |
| 시스템 uptime          |                 4271 seconds |
| 공개 host / platform   | local, Local system / darwin |

이 값은 해당 시도의 스냅샷이며 현재 값이나 성능 기준으로 고정하지 않습니다. 이후 Safari에서도 다른 CPU·메모리 값이 정상 표시됐습니다. 부하 테스트·특정 CPU 부하 생성·성능 benchmark는 하지 않았습니다.

샌드박스 안에서는 psutil boot_time()이 PermissionError errno 1로 차단됐습니다. 이때 실제 CPU·메모리·디스크와 uptime=null/errors를 담은 **HTTP 200 partial**을 확인했습니다. 허가받은 샌드박스 밖 일반 사용자 실행에서는 uptime을 포함한 네 자원이 성공했습니다. sudo/root 권한 상승, 시스템 설정 변경, 다른 값을 uptime으로 대체하는 우회는 하지 않았습니다.

### macOS APFS 의미

기본 경로 `/`가 APFS임을 psutil disk_partitions의 filesystem type으로 확인했습니다. 운영자가 설정한 경로가 속한 파일시스템 하나를 측정하며 API에는 `primary`만 공개합니다. 위 실측의 used/total은 약 **2.52%**이지만 psutil percent는 **9.5%**입니다. [psutil 7.2.2 POSIX 소스](https://raw.githubusercontent.com/giampaolo/psutil/release-7.2.2/psutil/_psposix.py)의 used/(used+일반 사용자 free) 기준을 사용하므로 두 수치가 일치할 필요는 없습니다.

[Apple의 APFS 설명](https://support.apple.com/en-au/guide/disk-utility/dskua9e6a110/mac)에 따르면 여러 볼륨이 컨테이너 가용 공간을 공유하고 system/data 볼륨을 구분합니다. `/`의 사용량을 전체 물리 디스크·모든 볼륨 사용량으로 설명하지 않습니다. Finder의 저장 공간·purgeable·다른 볼륨 합계와 일치하는지 검증하거나 Data 볼륨을 합산하지 않았습니다.

## 실제 Safari 검증과 자동 테스트 구분

Safari에서 실제 정상 수집 상태, CPU·메모리·디스크·uptime, 두 시각과 레이아웃을 접근성 트리·스크린샷으로 직접 확인했습니다. 11:31 화면에서 CPU 39.9%/메모리 62.5%/디스크 9.5%/uptime 1시간 13분 6초가 표시됐고, 별도 클릭 없이 스크린샷에서는 CPU 38.8%·uptime 1시간 13분 11초로 변해 자동 갱신을 확인했습니다.

별도 검증 창에서도 정상 수집을 확인한 후, 이번 작업의 백엔드를 Ctrl+C로 종료했습니다. 프록시 metrics HTTP 500을 확인했고 Safari에서 **‘메트릭 API 오류’와 네 카드의 ‘이전 값’·원래 시각 보존**을 확인했습니다. 수동 health 요청 전 연결 카드는 마지막 성공을 유지했습니다.

검증 중 사용자의 Safari 창 전환과 제어 도구의 변경 감지 차단이 반복됐습니다. 한 번 이전 인덱스가 다른 대화 링크로 바뀐 것을 놓쳐 읽기 화면 이동이 발생했고, 이후 원래 대화 화면으로 복구된 상태를 확인했습니다. 입력·메시지 제출·외부 전송은 하지 않았습니다. 이후에는 전체 최신 native 창 메뉴와 로컬 URL 조건으로 대상을 선택했습니다.

백엔드 재시작 후 직접·프록시 metrics HTTP 200 정상 복구를 확인했습니다. 이후 같은 별도 Safari 창에서 **정상 수집 복구·네 지표 표시·새 수집/수신 시각·이전 값 안내 제거**를 직접 확인했습니다. 복구 화면은 CPU 29.2%, 메모리 64.4%, 디스크 9.5%, uptime 1시간 28분 50초였으며 수집 11:46:53, 수신 11:46:55 GMT+9였습니다. 이 흐름에서 메트릭 수동 버튼을 누르지 않았으므로 화면 자동 복구를 확인한 것입니다. 새 Stage 1 화면에서 health 수동 실패→재시도 성공과 메트릭 수동 버튼의 클릭 확인은 창 전환 때문에 다시 수행하지 못했습니다. 해당 동작은 기존 Stage 0 실브라우저 이력과 이번 자동 테스트 결과로 따로 구분합니다.

## 자동 검사·빌드·의존성

| 검사                           | 실제 결과                                                                   |
| ------------------------------ | --------------------------------------------------------------------------- |
| backend pytest 기본            | 함수 선언 26개 → 수집 48 cases, 실행 47 / passed 47 / failed 0 / skipped 1  |
| 실측 opt-in 포함 전체 pytest   | 수집·실행 48 / passed 48 / failed 0 / skipped 0                             |
| 신규 backend                   | 함수 23개 → 신규 45 cases (Mock/서비스·API 44, OS 실측 1)                   |
| frontend Vitest                | 선언 호출 30개 → 실행 43 cases / passed 43 / failed 0 / skipped 0, 파일 3개 |
| 신규 frontend                  | 선언 호출 24개 → 신규 37 cases                                              |
| pip check                      | No broken requirements found                                                |
| Ruff check / format check      | 통과 / Python 파일 6개 포맷 일치                                            |
| npm ci                         | 기존 잠금 기반 재설치 성공, 프런트엔드 패키지·잠금 변경 없음                |
| TypeScript / ESLint / Prettier | 전부 통과                                                                   |
| production build               | 성공, 33 modules, JS 197.69 kB / gzip 63.25 kB                              |
| npm audit / --omit=dev         | 모두 0개, 종료 코드 0                                                       |
| 개발 실행                      | Uvicorn --reload·Vite 개발 서버 정상 실행                                   |
| Git diff --check               | 통과                                                                        |

기존 pytest 함수·cases 3개와 Vitest 6개는 삭제하지 않았습니다. App.test.tsx에는 MetricsPanel을 mock하는 선언만 추가해 기존 health 테스트의 fetch 순서와 버튼·status selector를 보존했습니다. 별도 통합 테스트에서 실제 App의 health 수동 요청과 metrics polling의 독립성을 확인했습니다.

psutil 7.2.2를 프로젝트 .venv에 wheel로 설치하고 requirements.in/pyproject.toml에 runtime 직접 의존성으로 추가했습니다. pip freeze로 잠금 파일을 생성했으며 기존 잠금과 비교한 변경은 psutil 한 줄뿐입니다. 잠금 파일 설치를 기존 가상환경에서 확인했으나 새로운 빈 가상환경의 설치까지 수행한 것은 아닙니다. 다른 패키지는 업데이트하지 않았습니다.

Debug/Release라는 별도 Vite 빌드 설정은 없습니다. 개발 서버 실행은 성공, 배포용 production build도 성공입니다. 검증 완료 후 이번 작업에서 시작한 Uvicorn과 Vite는 Ctrl+C로 정상 종료했습니다. 반복 실행을 고유 테스트 수에 합산하지 않습니다.

pytest 경고는 기존 Starlette의 AnyIO 별칭과 FastAPI의 asyncio.iscoroutinefunction 두 종류이며 새 route/앱 생성 테스트 증가로 발생 횟수가 **36개**입니다. Python 3.16 전 호환성 유지보수가 필요합니다. 처음 추가 테스트의 빈 warning match를 제거해 불필요한 PytestWarning을 해결했으며 경고 필터는 추가하지 않았습니다.

초기 frontend 검사 명령을 루트에서 실행해 package.json ENOENT가 발생한 것은 테스트 실패가 아니라 실행 디렉터리 오류였고 frontend에서 재실행했습니다. TypeScript의 Node/브라우저 timer 타입 충돌은 window timer의 number 타입으로 수정했습니다. 새 테스트 파일 포맷 오류도 Prettier로 수정 후 전체 검사를 통과했습니다. 기존 eslint/whatwg-encoding 지원 종료 및 npm 설치 스크립트 승인 목록 안내는 그대로이며 실제 test/build/dev 실행은 성공했습니다.

## 보안·기존 데이터·제한·다음 작업

실제 호스트명·사용자명·IP·장치명·개인 경로를 수집 응답에 넣지 않습니다. 공개 별칭과 플랫폼만 제공합니다. 앱 코드에 shell/subprocess·원격 명령·process 제어·권한 상승·localStorage 이력 저장이 없음을 확인했습니다. 비밀 키 패턴과 추적된 제외 파일 검사에서 민감 키·환경·가상환경·node_modules·dist는 발견되지 않았습니다. 민감 exception payload는 metrics 응답·애플리케이션 로그에서 숨깁니다. 정규식 검사는 모든 미공개 취약점이나 비밀의 부재를 보장하지 않습니다.

사용자 데이터 저장은 없고 기존 파일 삭제는 하지 않았습니다. main의 baseline hash와 Git index는 유지했고 수정·신규 파일은 모두 미커밋입니다. AGENTS.md·.gitignore·기존 Stage 0 문서 및 audit JSON은 바꾸지 않았습니다. 설계 문서는 원문 그대로 남습니다.

현재 검증 OS는 macOS arm64입니다. Linux·Windows 실측, VM/container/cgroup 의미, 다중 worker·다중 서버, 인증된 외부 공개·rate limit, production proxy 배포, OS syscall 영구 정지에 대한 프로세스 격리는 미검증 또는 범위 밖입니다. 서버·프런트엔드는 로컬 주소를 유지하며 polling guard는 악성 클라이언트의 서버 rate limit을 대신하지 않습니다.

Codex 의견: Stage 1의 수집·API·대시보드 구현과 자동/HTTP 검증은 완료했습니다. 실제 Safari의 메트릭 장애 복구도 확인했으므로 **현재 macOS 로컬 단일 프로세스 범위에서 Stage 1 종료와 Stage 2 설계 진행이 가능합니다.** 미확인한 두 수동 버튼의 새 화면 직접 확인은 후속 사용 점검에서 보완할 수 있으며 자동 테스트는 통과했습니다. Stage 2 저장 스키마·보존 정책의 설계 검토는 현재 명확한 단위·host.id·UTC timestamp를 기반으로 가능합니다. 이번 작업에서는 Stage 2 기능을 구현하지 않았습니다.
