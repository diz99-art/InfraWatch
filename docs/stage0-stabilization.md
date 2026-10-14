# Stage 0 최종 안정화 검증

2026-10-14 macOS / Python 3.14.4 / Node 24.21.0 / npm 11.19.0에서 실제 실행한 결과입니다. 이전 설치·잠금 파일·테스트·API 연결 검증은 README에 보존합니다.

## npm 보안 검사와 대응

| 시점·명령                                    | moderate | high | critical | 합계 |
| -------------------------------------------- | -------: | ---: | -------: | ---: |
| 이전 설치 요약                               |        1 |   10 |        2 |   13 |
| 작업 최초 `npm audit --json`                 |        3 |   10 |        2 |   15 |
| 중단 후 업데이트 전 재조회·저장              |        1 |   10 |        2 |   13 |
| Vite·Vitest 업데이트 후 audit                |        0 |    9 |        0 |    9 |
| 최종 `npm ci` 설치 요약                      |        0 |    0 |        0 |    0 |
| 최종 `npm audit --json`                      |        0 |    0 |        0 |    0 |
| 업데이트 전·후 `npm audit --omit=dev --json` |        0 |    0 |        0 |    0 |

업데이트 전 재조회와 최종 전체·운영 JSON은 [security 디렉터리](security/)에 저장했습니다. 최초 15개 원문은 도구 실행 출력에 있으며, 저장 파일은 재조회한 13개입니다. 최초 결과를 재구성한 JSON으로 바꾸지 않았습니다. 모든 단계에서 감사 기능을 유지했으며 `audit fix --force`, 임의 overrides, 취약점 무시 설정은 사용하지 않았습니다. 최종 audit 두 명령 모두 종료 코드 0입니다.

### 집계 차이

15개와 13개의 차이는 Vite에서 파생된 `@vitejs/plugin-react`, `vite-node` moderate 항목 두 개입니다. 근본 권고 목록과 high 10 / critical 2는 같습니다. audit의 패키지 개수는 독립적인 보안 권고 개수가 아니며, 취약한 전이 의존성 때문에 표시되는 상위 패키지도 포함합니다.

설치된 npm 11.19.0 소스의 `npm-audit-report/lib/reporters/install.js`는 JSON의 `metadata.vulnerabilities`를 그대로 표시하고, Arborist는 권고와 상위 의존성의 meta-vulnerability를 계산합니다. 따라서 설치 요약이 항상 전이 취약점을 제외한다는 설명은 맞지 않습니다. [npm 공식 문서](https://docs.npmjs.com/cli/v11/commands/npm-audit/)에 따르면 계산 결과는 npm 캐시에 보관되고 권고 범위·새 버전에 따라 갱신됩니다. 같은 세션에서 npm view의 샌드박스 캐시 쓰기 제한을 확인했고, 권한 허용 후 업데이트 전 audit 재조회는 13개였습니다. 캐시·실행 시점에 따른 상위 패키지 판정 차이가 가능한 원인이지만, 과거 두 실행의 전체 원문·캐시 상태를 모두 확보하지 못했으므로 단일 원인으로 확정하지 않습니다. 최종 상태는 `npm ci`와 독립 audit 모두 0개로 일치합니다.

### 업데이트 판단

| 직접 개발 의존성  | 이전   | 최종   | 판단                                                                                                                                |
| ----------------- | ------ | ------ | ----------------------------------------------------------------------------------------------------------------------------------- |
| vite              | 7.1.7  | 7.3.7  | 같은 주 버전. 아래 6개 권고의 영향 범위에서 벗어남.                                                                                 |
| vitest            | 3.2.4  | 4.1.11 | 3.2.7도 tinypool 1.x와 mocker 3.x를 사용하므로 패치만으로 모두 해결되지 않음. 4.1.11로 mocker 수정 및 tinypool·vite-node 경로 제거. |
| typescript-eslint | 8.44.1 | 8.71.2 | 같은 주 버전. estree가 fast-glob 대신 다른 glob 경로를 사용해 braces·micromatch·fast-glob 제거.                                     |

Vitest 주 버전 변경은 [공식 4.0 마이그레이션 문서](https://v4.vitest.dev/guide/migration)를 검토했습니다. 현재는 jsdom, fetch 함수 모킹, fake timers, afterEach만 사용하며 변경된 coverage·custom pool·browser project API는 사용하지 않습니다. Node 24.21.0, Vite 7.3.7, jsdom 26.1.0 및 @types/node 22.18.6은 설치 버전의 요구사항을 만족합니다. 기존 테스트와 설정을 변경하지 않고 전체 검사를 통과했습니다. typescript-eslint의 ESLint 9 / TypeScript 5.9 호환 범위도 registry 메타데이터로 확인했습니다.

### 패키지별 영향 경로

아래는 최초 15개 모두입니다. **모두 개발 의존성**이며 React 운영 의존성이나 생성 정적 번들의 실행 의존성에 해당하지 않습니다. 개발 도구도 개발자 파일·프로세스에 접근하므로 운영 검사 0개만으로 무시하지 않았습니다. 식별자 A/B/C는 다음 절의 권고에 연결됩니다. 상위 패키지는 독립 권고가 아니라 하위 취약점의 파생 항목입니다.

| 패키지                               | 심각도   | 직접/전이 | 권고·실제 경로                                                  | 수정 버전·최종 대응                                              |
| ------------------------------------ | -------- | --------- | --------------------------------------------------------------- | ---------------------------------------------------------------- |
| @typescript-eslint/eslint-plugin     | high     | 전이      | A; typescript-eslint → plugin → type-utils/utils → estree       | typescript-eslint 8.71.2에 맞는 8.71.2로 갱신                    |
| @typescript-eslint/parser            | high     | 전이      | A; typescript-eslint → parser → estree                          | 8.71.2로 갱신                                                    |
| @typescript-eslint/type-utils        | high     | 전이      | A; plugin → type-utils → estree/utils                           | 8.71.2로 갱신                                                    |
| @typescript-eslint/typescript-estree | high     | 전이      | A; estree → fast-glob → micromatch → braces                     | 8.71.2가 취약 경로 제거                                          |
| @typescript-eslint/utils             | high     | 전이      | A; plugin/type-utils → utils → estree                           | 8.71.2로 갱신                                                    |
| @vitejs/plugin-react                 | moderate | 직접      | B; plugin-react → Vite 개발 서버                                | plugin 5.0.3 유지, Vite 7.3.7로 해결                             |
| @vitest/mocker                       | moderate | 전이      | B/C; Vitest → mocker → Vite 및 redirect mock                    | 4.1.11로 갱신                                                    |
| braces                               | high     | 전이      | A; typescript-eslint → estree → fast-glob → micromatch → braces | 수정 릴리스 없음; 상위 8.71.2로 경로 제거                        |
| fast-glob                            | high     | 전이      | A; estree → fast-glob → micromatch                              | 상위 업데이트로 제거                                             |
| micromatch                           | high     | 전이      | A; fast-glob → micromatch → braces                              | 상위 업데이트로 제거                                             |
| tinypool                             | critical | 전이      | C; Vitest → tinypool worker 실행                                | 권고별 2.1.1 / 2.1.2; 강제 주 버전 override 대신 Vitest 4로 제거 |
| typescript-eslint                    | high     | 직접      | A; lint에서 위 estree 경로 사용                                 | 8.71.2로 갱신                                                    |
| vite                                 | high     | 직접      | B; localhost 개발 HTTP/WebSocket 서버                           | 모든 아래 권고에 대해 7.3.5 이상; 7.3.7 적용                     |
| vite-node                            | moderate | 전이      | B; Vitest 3 → vite-node → Vite                                  | Vitest 4의 Vite module runner 사용으로 제거                      |
| vitest                               | critical | 직접      | B/C; mocker·tinypool 및 UI 서버                                 | UI 권고는 3.2.6, redirect mock은 4.1.11; 4.1.11 적용             |

### 보안 권고와 실제 위험

**A — glob 패턴 DoS**: [GHSA-vfj7-8cjw-p6xm / CVE-2026-93687](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm). braces ≤3.0.3의 깊은 중첩 패턴으로 Node 스택 고갈이 가능합니다. 현재 lint는 저장소 파일·설정을 읽고 외부 사용자의 패턴을 받는 API가 없습니다. 위험은 공격자가 lint 입력·설정을 통제하는 개발/CI 상황이며, 최종 설치에서 이 의존성 경로 자체가 없어졌습니다. braces의 수정 릴리스는 조회 당시 없습니다.

**B — Vite 개발 서버 파일 접근**:

- [GHSA-93m4-6634-74q7](https://github.com/advisories/GHSA-93m4-6634-74q7): Windows backslash deny 우회, 7.1.11에서 범위 이탈.
- [GHSA-4w7w-66w2-5vf9](https://github.com/advisories/GHSA-4w7w-66w2-5vf9): 최적화 의존성 map 경로 순회, 7.3.2에서 범위 이탈.
- [GHSA-v2wj-q39q-566r](https://github.com/advisories/GHSA-v2wj-q39q-566r): query를 통한 deny 우회, 7.3.2에서 범위 이탈.
- [GHSA-p9ff-h696-f583](https://github.com/advisories/GHSA-p9ff-h696-f583): 개발 WebSocket을 통한 파일 읽기, 7.3.2에서 범위 이탈.
- [GHSA-v6wh-96g9-6wx3](https://github.com/advisories/GHSA-v6wh-96g9-6wx3): Windows UNC 경로의 NTLMv2 해시 노출, 7.3.5에서 범위 이탈.
- [GHSA-fx2h-pf6j-xcff](https://github.com/advisories/GHSA-fx2h-pf6j-xcff): Windows 대체 경로 deny 우회, 7.3.5에서 범위 이탈.

macOS에서는 Windows 전용 경로는 직접 적용되지 않지만, 일반 개발 서버 HTTP/WebSocket 파일 읽기 위험은 별개입니다. 서버는 127.0.0.1에 바인딩되며 production은 정적 빌드와 별도 API 프록시를 사용합니다. localhost 바인딩만으로 모든 브라우저 기원 공격이 차단된다고 가정하지 않고 수정 버전을 적용했습니다.

**C — 테스트 도구**:

- [GHSA-5xrq-8626-4rwp](https://github.com/advisories/GHSA-5xrq-8626-4rwp): Vitest UI 서버 파일 읽기·실행, 3.2.6에서 수정. 프로젝트는 `vitest run`만 사용하며 UI 서버를 실행하지 않습니다.
- [GHSA-82fw-gwwq-j7x9 / CVE-2026-84373](https://github.com/advisories/GHSA-82fw-gwwq-j7x9): mocker redirect mock 경로 순회·파일 읽기, 4.1.11에서 수정. 현재 테스트는 전역 fetch 모킹을 사용하고 redirect mock을 구성하지 않습니다.
- [GHSA-5gmw-xhrv-c9v3 / CVE-2026-104848](https://github.com/advisories/GHSA-5gmw-xhrv-c9v3): tinypool worker options의 prototype pollution gadget, 2.1.1에서 수정.
- [GHSA-85c8-ppgw-ccpr / CVE-2026-104849](https://github.com/advisories/GHSA-85c8-ppgw-ccpr): tinypool run options의 prototype pollution gadget, 2.1.2에서 수정.

Tinypool 권고는 선행 prototype pollution과 worker 옵션 경로가 필요합니다. 현재 앱에는 외부 입력을 worker 옵션으로 전달하는 코드가 없지만 개발 테스트 프로세스의 코드 실행 위험이므로 해당 경로를 제거했습니다. 남은 critical/high 취약점은 최종 npm audit 기준 **없음**입니다. 감사 0개는 모든 미공개 취약점의 부재나 백엔드 전체 보안 감사를 뜻하지 않습니다.

## pytest 경고 6개

`.venv/bin/python -m pytest -W always`로 3 passed / 6 warnings를 재현했습니다. 경고 종류는 2개이며 테스트 실패가 아닙니다.

| 발생 수 | 라이브러리·호출 경로                                                                                                                       | 영향·판단                                                                                                                                                           |
| ------- | ------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1       | tests → fastapi.testclient → starlette.testclient 0.47.3:51 → 타입 별칭의 anyio.abc.BlockingPortal 조회 → AnyIO 4.15.1 deprecated alias    | 대체 경로는 anyio.from_thread.BlockingPortal. import 시 발생하며 TestClient 경로입니다. 별칭 제거 시 테스트 import가 깨질 수 있고, 제거 시점은 확인하지 못했습니다. |
| 5       | app.main 모듈의 create_app 1회 + 테스트별 create_app 3회 + /broken 등록 1회 → FastAPI 0.116.1 routing.py:234 → asyncio.iscoroutinefunction | Python 3.14 deprecation, 경고 메시지는 Python 3.16 제거 예정이라고 명시합니다. 앱 route 등록 경로에도 해당하므로 향후 앱 생성 실패 위험이 있습니다.                 |

현재 Python 3.14.4에서는 API 실행과 테스트 모두 정상입니다. 로컬 패키지 소스와 [Starlette 0.47.3 원본](https://raw.githubusercontent.com/encode/starlette/0.47.3/starlette/testclient.py)을 확인했습니다. [FastAPI 0.116.2 패치 소스](https://raw.githubusercontent.com/fastapi/fastapi/0.116.2/fastapi/routing.py)에도 asyncio.iscoroutinefunction 호출이 남습니다. 설치된 FastAPI는 Starlette <0.48.0을 요구합니다. 앱 코드의 최소 변경으로 두 경고를 해결할 수 없으며, 검증된 백엔드 잠금을 유지했습니다. site-packages 편집, monkey patch, AnyIO 다운그레이드, 경고 필터는 사용하지 않았습니다.

후속 작업은 Python 3.16 적용 전에 FastAPI·Starlette의 두 호출 수정이 포함된 조합을 선정하고 동일 회귀 검증을 하는 것입니다. 현재 경고를 숨기거나 모든 Python 3.11+ 환경이 검증되었다고 선언하지 않습니다.

## 실제 Safari 장애 복구

Uvicorn `--reload`와 Vite를 각각 실행했습니다. Safari의 기존 InfraWatch 탭을 선택하고 새로고침한 뒤 다음 UI를 접근성 트리로 직접 확인했습니다.

1. `http://127.0.0.1:5173/`에서 **연결 성공**.
2. 이번 작업에서 시작한 백엔드 프로세스를 Ctrl+C로 종료하고 정상 종료 로그 확인.
3. Safari **다시 확인** 버튼 클릭 → **연결 실패**, 실행 여부·API 주소 확인 안내 표시.
4. 별도 HTTP 검사: 직접 API connection refused, Vite 프록시 HTTP 500.
5. 같은 명령으로 백엔드 재시작, startup complete 확인.
6. Safari **다시 확인** 버튼 클릭 → **연결 성공**, 실패 안내 제거.

검증 중 사용자가 Safari 창을 변경해 제어 도구가 동작을 거부한 경우 현재 UI를 다시 조회한 후 새 버튼 인덱스로 진행했습니다. 다른 웹사이트에는 입력하거나 제출하지 않았습니다. 실제 실패·재시도 복구를 완료했으므로 브라우저 미검증으로 대체하지 않습니다. 자동 polling은 없으며, 백엔드 중단 직후 자동 실패 전환은 검증 조건으로 삼지 않았습니다. 기존 Vitest의 fetch 모킹 실패·재시도 테스트 결과와 실제 Safari 검증은 별개입니다.

## 최종 회귀 결과

| 검사                              | 실제 결과                                                         |
| --------------------------------- | ----------------------------------------------------------------- |
| pytest                            | 선언 3 / 수집·실행 3 / passed 3 / failed 0 / skipped 0, 경고 6    |
| pip check                         | No broken requirements found                                      |
| Ruff check / format check         | 통과 / 3 files already formatted                                  |
| npm ci                            | 최종 잠금 기반 재설치 성공, audit 0                               |
| Vitest                            | 선언 6 / 실행 6 / passed 6 / failed 0 / skipped 0, 파일 1개 통과  |
| TypeScript / ESLint / Prettier    | 전부 통과                                                         |
| production build                  | 성공, 모듈 30개, JS 189.07 kB (gzip 60.20 kB)                     |
| 최종 전체 / 운영 npm audit        | 각각 0개, 오류 없음                                               |
| Uvicorn / 직접·Vite 프록시 health | 실행 성공, 각각 HTTP 200 및 계약 JSON                             |
| 실제 Safari                       | 성공 → 실패 → 재시도 성공 복구 확인                               |
| Git diff --check                  | 통과. 모든 파일이 untracked이므로 별도 파일 비교·공백 검사도 수행 |

기존 테스트 선언 수는 변경하지 않았습니다. 반복 실행은 고유 테스트 수에 합산하지 않습니다. 설치 중간에 `npm run dev`를 실행해 Vite 실행 파일이 아직 준비되지 않아 한 번 실패했고, 설치 완료 후 재실행은 정상입니다. 최초 npm 버전 조회는 전역 캐시 쓰기 EPERM으로 실패했으며 필요한 명령을 권한 허용 후 수행했습니다. 시스템 캐시 소유권이나 전역 설정은 바꾸지 않았습니다. pip의 캐시 비활성 경고는 pip check 성공 여부와 별개입니다.

`npm ci`는 eslint 9.36.0 지원 종료, whatwg-encoding 3.1.1 사용 중단과 esbuild/fsevents 설치 스크립트 승인 목록 안내를 출력했습니다. 설정을 바꾸지 않았고 테스트·빌드·개발 서버가 실제로 정상 작동했습니다. 이 안내들은 최종 audit 취약점과 별개이며 다음 유지보수에서 검토할 사항입니다.

## 기존 기능·Git·제한

변경은 frontend/package.json, frontend/package-lock.json, README.md 및 이 검증 문서·audit JSON 4개입니다. 앱·API·테스트·백엔드 잠금·AGENTS.md·.gitignore는 유지했습니다. 독립 앱 팩토리, health 계약 `{"status":"ok","service":"InfraWatch"}`, 연결 중/성공/실패, 제한 시간 5초와 수동 재시도를 보존했습니다. 사용자 데이터 저장 기능은 없으며 사용자 파일 삭제는 하지 않았습니다.

Git 저장소는 커밋·추적 파일이 없고 모든 프로젝트 파일은 untracked 상태입니다. commit, push, stage, reset은 수행하지 않았습니다. .gitignore의 .env, 가상환경, 캐시, node_modules, dist, 로그, AWS 자격증명·키 제외를 확인했고 .env.example·잠금 파일은 제외되지 않습니다. 추적된 민감 파일은 없습니다.

검증 완료 후 이번 작업에서 시작한 Uvicorn·Vite를 Ctrl+C로 종료했습니다. 최종 8000·5173 포트에 실행 중인 서버는 없습니다.

검증 범위는 현재 macOS와 해당 버전입니다. 다른 OS·Python 버전·production 역방향 프록시 배포·부하·커버리지·자원 사용률은 측정하거나 검증하지 않았습니다. Stage 1의 수집·DB·인증·다중 서버·장애 알림·WebSocket은 구현하지 않았습니다. Codex 의견은 **현재 Stage 0 종료 가능**이며, 백엔드 경고 해결은 Python 3.16 전 호환성 유지보수로 남깁니다. 다음 기능 작업은 사용자 승인 후 단일 서버 수집의 데이터 단위·API 계약 설계부터 진행할 수 있습니다.
