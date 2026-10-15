# Stage 2A 구현 및 운영 경계

기준: `279c7904ed3384d8b644ce5ca0673aa811e18a13`. [Stage 2 설계](stage2-design.md)의 2A 범위를 구현한다. 실제 자동 저장 writer·큐·재시도·이력 API·상태 API·그래프·자동 삭제·백업 복구는 포함하지 않는다. 아래 테스트 절차는 기존 DB를 초기화하는 지시가 아니다.

## 선택과 구조

- PostgreSQL 18 계열을 대상으로 한다. 검증용 버전은 18.6이다. 시스템 전역 설치 대신 승인된 전용 임시 경로에서 공식 소스 SHA256을 검증해 빌드한다. 이 최소 테스트 빌드는 ICU·readline·zlib·TLS가 없는 로컬 검증 전용이며 원격 운영 배포용이 아니다.
- Python 3.14.4 arm64에 psycopg[binary] 3.3.6, SQLAlchemy Core 2.0.54, Alembic 1.20.0을 고정했다. 실제 cp314 wheel 설치에 성공했으며 기존 패키지 업데이트는 하지 않았다. requirements.in은 직접 목록, requirements.lock은 pip freeze 결과다.
- [psycopg 설치·지원 환경](https://www.psycopg.org/psycopg3/docs/basic/install.html), [SQLAlchemy 2.0 변경 이력](https://docs.sqlalchemy.org/en/20/changelog/changelog_20.html), [Alembic 공식 절차](https://alembic.sqlalchemy.org/en/latest/tutorial.html), [PostgreSQL 지원 정책](https://www.postgresql.org/support/versioning/)을 참고했다.
- `app/db.py`: 기본 비활성 설정, 지연 engine 생성, 명시적 트랜잭션, 고정 오류 코드, revision 점검. ORM session 대신 Core Connection을 사용한다.
- `app/schema.py`: 공개 API 모델과 독립된 저장 테이블·제약·인덱스. 서버 등록·수정 시각을 함께 둔다. 현재 등록은 불변이며 충돌 시 자동 수정하지 않아 updated_at도 바뀌지 않는다.
- `app/servers.py`: 등록과 별칭 조회. 등록자가 UUID를 한 번 정해 보존하고 재사용한다. 같은 별칭의 다른 UUID·플랫폼·label은 충돌이며 자동 덮어쓰지 않는다.
- `migrations/versions/0001_stage2a.py`: live 모델을 import하지 않는 초기 스키마 스냅샷. 향후 모델 수정으로 과거 migration 의미가 바뀌지 않는다. Alembic이 명시적 upgrade 경로에서만 DDL을 실행한다. downgrade는 데이터 손실 위험 때문에 거부한다.

## 실시간 기능 보호와 연결 수명

기존 `create_app()`·lifespan·MetricsService·Sample·health·metrics·프론트엔드는 수정하지 않았다. DB 설정이 있어도 앱 import/startup과 기존 요청은 DB에 접속하지 않는다. 따라서 DB가 없거나 설정이 잘못돼도 Stage 1 수집과 API는 유지된다. 2A 연결 점검은 내부 함수 또는 CLI로 명시적으로 실행한다. startup readiness task나 공개 상태 API는 만들지 않는다.

NullPool로 연결을 공유·유지하지 않고 작업당 연결 한 개를 열어 성공 시 commit, 실패 시 rollback 후 close/dispose한다. pool 대기열이 없으므로 pool 획득 지연도 없다. connect_timeout 2초, statement_timeout 2초, lock_timeout 500ms, idle-in-transaction timeout 5초, UTC·public search_path를 적용한다. URL query 옵션은 거부해 세션 안전 설정을 덮어쓰지 못하게 한다. DNS·네트워크 및 OS 정지까지 모든 작업이 2초에 종료된다는 보장은 없으며, 이 동기 경계는 async route/event loop나 수집 executor에서 호출하지 않는다. 2B writer는 별도 실행 경계를 사용해야 한다.

환경은 shell에서 읽으며 .env 자동 로딩은 없다. 기본 `INFRAWATCH_DB_ENABLED=0`. 명시적 DB 작업에는 `INFRAWATCH_DB_ENABLED=1`과 비공개 `INFRAWATCH_DATABASE_URL`이 필요하다. URL 형식은 SQLAlchemy의 `postgresql+psycopg`이며 user·host·database가 필요하다. 비밀번호는 인증 방식에 맞게 비공개 환경에서 전달한다. 실제 DSN을 README·명령 이력·VITE\_·API 응답에 넣지 않는다. TLS 연결이 필요한 운영 환경은 별도 검증 전 지원 완료로 선언하지 않는다.

DB 설정 repr는 URL을 숨기고 SQLAlchemy는 parameter를 숨긴다. 경계 밖에는 disabled/configuration_error/unavailable/schema_mismatch 및 서버 등록 관련 고정 코드만 반환한다. CLI는 예외 원문·traceback·DSN을 출력하지 않는다. 운영 진단은 고정 코드로 시작하며 비공개 서버 로그 접근은 별도 절차다.

## 명시적 migration과 서버 등록

아래 명령은 backend 디렉터리에서 실행하며 대상 DSN은 작업 전 운영자가 확인한다. 앱 계정으로 migration을 실행하지 않는다. 기존 데이터베이스를 DROP·재생성하거나 stamp로 불일치를 숨기지 않는다.

```sh
# DB 접속 없이 초기 PostgreSQL SQL 생성
.venv/bin/python -m alembic upgrade head --sql
# migration 전용 환경이 설정된 경우에만 실행
.venv/bin/python -m app.database_cli upgrade
.venv/bin/python -m app.database_cli check
```

`upgrade`는 Alembic revision을 사용하며 기존 head에 재실행하면 기존 데이터를 유지한다. CLI는 공개 별칭을 자동 등록하지 않는다. 별도 등록 역할 환경으로 전환하고 UUID를 한 번 생성해 보존한 뒤 실행한다. 등록 역할도 revision 조회 권한이 필요하다.

```sh
.venv/bin/python -c 'from uuid import uuid4; print(uuid4())'
# 실제 등록 시 위 UUID를 --server-id 값으로 제공한다.
.venv/bin/python -m app.database_cli register --help
.venv/bin/python -m app.database_cli lookup --public-id local
```

UUID를 재실행마다 새로 만들지 않는다. label/platform 변경도 자동 upsert하지 않는다. 최초 등록 후 동일 UUID·별칭·값으로 재실행하면 같은 등록을 반환한다. startup 자동 upgrade/create_all/등록은 없다.

## 최소 권한

전용 DB 관리자만 초기 DB·역할·schema 권한을 준비한다. 앱에 superuser·CREATEDB·CREATEROLE·DDL 권한을 주지 않는다. PUBLIC의 database 접근 및 public schema CREATE는 해당 전용 DB 정책에 맞게 제한한다. 기존 공유 DB 권한을 이 문서만 보고 일괄 변경하지 않는다.

| 역할             | 대상 권한                                                                          |
| ---------------- | ---------------------------------------------------------------------------------- |
| migration 소유자 | 해당 전용 DB/schema의 DDL, Alembic revision 관리                                   |
| 등록 운영자      | schema USAGE, servers SELECT/INSERT, alembic_version SELECT                        |
| runtime 앱       | schema USAGE, servers·metric_samples·alembic_version SELECT, metric_samples INSERT |
| 후속 정리 역할   | metric_samples SELECT/DELETE만 검토; 2A에서는 생성·실행 불필요                     |

등록과 runtime을 분리해 실시간 프로세스가 임의로 서버를 만들지 못하게 한다. 연결에는 DB CONNECT 권한도 필요하다. 역할 비밀번호는 비공개 입력으로 설정하고 예시 SQL에 하드코딩하지 않는다. 조회·등록 fixture도 앱 계정과 다른 역할로 수행한다.

## 독립 PostgreSQL 테스트

`tests/test_database_live.py`는 opt-in이다. `INFRAWATCH_TEST_DB_CONFIRM=isolated` 없이는 skipped다. 지정 시에는 migration·앱·등록 역할 URL이 모두 필요하며, 각 연결에서 SELECT로 현재 DB 이름이 `infrawatch_test_`와 12자리 hex인지, DB comment가 `InfraWatch isolated test database v1`인지 확인한 후에만 DDL/DML을 허용한다. marker는 운영 DB를 테스트 DB로 바꿔주는 장치가 아니며 관리자가 독립성을 먼저 확인해야 한다. 설정 오류·접속 실패는 성공 또는 skipped로 숨기지 않고 실패한다.

일반 테스트 DB를 자동 삭제·초기화하지 않는다. fixture 행은 트랜잭션 rollback하고 forward migration은 남긴다. 재실행 시 upgrade만 사용하며 downgrade·TRUNCATE·DROP은 하지 않는다.

```sh
# 기존 회귀·비DB 검사; DB opt-in 검사는 skipped
.venv/bin/python -m pytest
# 공급된 PostgreSQL 18 실행 파일로 새로운 독립 클러스터만 생성
.venv/bin/python scripts/run_db_tests.py --pg-bin /path/to/postgresql18/bin
# 독립 PostgreSQL + OS 실측 + 기존 회귀 전체
.venv/bin/python scripts/run_db_tests.py --pg-bin /path/to/postgresql18/bin --all
```

`run_db_tests.py`는 downloader/installer가 아니다. 사용자가 제공한 PostgreSQL 18 bin을 검증하고 0700 임시 디렉터리·임의 localhost 포트·SCRAM 비밀번호·별도 DB/계정으로 새 클러스터를 만든다. 임의 password는 프로세스 환경/비공개 파일에만 두며 콘솔에 출력하지 않는다. 공용 DB나 실행 중인 서비스에 접속하지 않는다. bootstrap 관리자와 migration/등록/runtime은 서로 분리한다. 정상 또는 실패 후 `pg_ctl stop`을 실행하고 파일은 삭제하지 않는다. 남은 password·서버 로그·클러스터는 비공개 로컬 산출물이다. 재검증은 같은 DB를 초기화하지 않고 새 임시 경로를 사용한다.

검증 항목은 upgrade·재실행·모델과 migration 일치, 값·NULL·상태·FK·고유 제약·인덱스·UTC, 등록 UUID 재사용과 충돌, runtime DDL/DELETE 금지, 등록/runtime 역할 분리, statement timeout 이후 연결 재사용 가능성이다. runner는 명시적으로 commit한 등록 fixture와 revision이 실제 DB 재시작 후 유지되는지도 확인한다. 측정 자동 저장은 없으며 테스트 fixture는 가상의 값이다.

## 이번 결과와 남은 경계

2026-10-15 macOS arm64 / Python 3.14.4 / PostgreSQL 18.6에서 실제 검증했다.

| 검사                                              | 실제 결과                                                                            |
| ------------------------------------------------- | ------------------------------------------------------------------------------------ |
| backend 전체 (독립 DB + OS 실측)                  | 함수 선언 45개 → 수집·실행 93 / passed 93 / failed 0 / skipped 0                     |
| 기존 Stage 1                                      | 기존 48 cases 보존, 전체 검사에 포함해 모두 통과                                     |
| 신규 2A                                           | 함수 선언 19개 → 비DB 12 cases + 실제 DB 33 cases = 45 cases 모두 통과               |
| 독립 DB                                           | 최초 upgrade·동일 head 재실행·제약·인덱스·권한·인증 실패·statement timeout 검사 통과 |
| DB 재시작                                         | 명시적으로 commit한 등록 UUID 및 revision 보존 확인                                  |
| pip check / 잠금                                  | 정상; 기존 .venv에서 requirements.lock 설치 일치 확인 (빈 venv 재설치는 미실행)      |
| Ruff check / format                               | 통과, Python 15개 파일 포맷 일치                                                     |
| frontend                                          | 선언 호출 30개 → Vitest 실행 43 / passed 43 / failed 0 / skipped 0, 파일 3개         |
| TypeScript / ESLint / Prettier / production build | 전부 통과; 33 modules, JS 197.69 kB / gzip 63.25 kB                                  |

전체 pytest는 함수 선언 수와 parameter 확장 수를 구분하며 반복 실행을 고유 case 수에 더하지 않는다. 기본 실행에서는 DB 33개와 OS 실측 1개가 opt-in으로 skipped가 된다. pytest의 기존 Starlette·FastAPI DeprecationWarning은 38개이며 억제하지 않았다. 최초 기본 검사에서는 작성 중 비DB/DB case 수가 적었고, 최종 전체 결과는 위 93개다. 프론트엔드 파일은 수정하지 않았다. 새 npm 의존성 설치·audit은 실행하지 않았으며 이전 audit 0개를 이번 결과로 바꾸지 않는다.

시스템에 PostgreSQL·Docker가 없음을 확인한 후 전용 소스 다운로드·실행 권한을 승인받았다. 공식 18.6 SHA256이 일치했고 /private/tmp 아래에만 빌드·설치했다. 전역 PATH·Homebrew 서비스·다른 프로젝트·기존 사용자 DB는 바꾸지 않았다. 테스트 클러스터는 신규 임시 경로 두 곳에 생성했고 모두 정상 종료했으며 파일은 삭제하지 않았다. 테스트 fixture의 rollback 외 기존 사용자 데이터 삭제는 없었다.

OS·드라이버의 모든 조합, production TLS, DNS 정지, 실제 DB 부하, backup/restore, writer·큐·유실 처리는 완료로 선언하지 않는다. 메모리 실시간 캐시는 DB에서 복원하지 않는다.
