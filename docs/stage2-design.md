# InfraWatch Stage 2 설계

설계일: 2026-10-14. **문서 설계이며 DB 설치·생성, migration 실행, 앱 코드 변경 또는 Stage 2 기능 구현을 하지 않았다.** JSON의 값은 계약 설명용 가상 예시이며 실측값이 아니다.

기준: main / Stage 0 `701b2e934569d3cb327fa913a619296c18eedfcc`. Stage 1 구현은 미커밋이다. [Stage 1 설계 원본](stage1-design.md), [구현·검증 결과](stage1-implementation.md), [README](../README.md)를 기준으로 한다. 설계 원본의 구현 전 상태와 stale >15초 표현보다 실제 구현의 age >=15초 정책을 우선한다.

## 1. 목표와 범위

5초 기본 수집을 유지하면서 PostgreSQL에 실제 수집 결과와 실패 이벤트를 저장하고, 기간 조회 API와 React 과거 그래프를 제공한다. 기존 `/api/health`의 `{"status":"ok","service":"InfraWatch"}`와 `/api/metrics` schema_version 1, HTTP 상태·오류·캐시 계약을 보존한다. health는 앱 생존 확인이며 DB readiness로 바꾸지 않는다. 현재 metrics는 최신 메모리 캐시 조회를 유지한다.

초기 범위는 macOS 로컬 시스템 한 대, 수집 worker 한 개다. 인증·원격 agent·다중 서버 운영·네트워크 수집·알림·WebSocket·장기 집계·Docker 구축은 추가하지 않는다. 조회 API도 localhost와 기존 개발 프록시를 사용하며 공개 배포를 지원 완료로 선언하지 않는다.

## 2. PostgreSQL 선택과 SQLite 비교

| 기준                     | PostgreSQL                                                        | SQLite                                         |
| ------------------------ | ----------------------------------------------------------------- | ---------------------------------------------- |
| 실행·운영                | 별도 서버, 연결·백업·권한 운영 필요                               | 로컬 파일로 시작하기 간단                      |
| 현재 단일 수집기         | 필요 규모보다 여유가 있으나 저장·SQL·운영 포트폴리오에 적합       | 현재 규모만 보면 충분한 대안                   |
| 동시 쓰기·향후 중앙 저장 | 서버형 중앙 DB와 여러 클라이언트에 적합                           | 동시 writer는 한 개, 네트워크 공유 파일에 제약 |
| 선택                     | 향후 Linux 서버의 중앙 이력 저장과 관계형 설계 학습을 고려해 채택 | 오프라인 단일 앱 목적이면 재검토 가능          |

SQLite가 현재 규모에 부족해서 선택하는 것은 아니다. SQLite의 단일 writer 및 서버형 대안 설명은 [공식 사용 지침](https://www.sqlite.org/whentouse.html)을 근거로 한다. PostgreSQL 버전·Python 드라이버는 구현 승인 시 지원 상태와 Python 3.14 호환성을 검증해 고정한다. 초기 후보는 psycopg 3와 Alembic이며 이번에는 의존성을 추가하지 않는다.

## 3. 수집과 저장을 분리하는 구조

```text
psutil 단일 수집 스레드 → 수집 서비스 → 기존 최신 메모리 스냅샷 → /api/metrics
                                 └→ bounded queue → 독립 DB writer → PostgreSQL
                                                               ↑
                                                   이력 조회 API → React 과거 그래프
```

DB writer는 수집 executor와 분리된 전용 worker로 실행한다. 동기 드라이버를 사용한다면 전용 DB 스레드를 사용해 event loop도 막지 않는다. 수집 서비스는 결과 공개 후 immutable 저장 이벤트를 `put_nowait`로 전달하며 DB 연결·SQL·재시도를 기다리지 않는다. 전체 실패와 timeout은 기존 캐시 공개 여부와 별도로 이벤트를 만들되 `/api/metrics`에는 기존 503을 유지한다. API polling이나 수동 새로고침은 저장 이벤트를 만들지 않는다.

현재 `MetricsService._run()`에는 이 이벤트 전달 지점이 없고 `Sample`에는 식별자가 없다. 이후 구현에서 서비스 경계에 내부 이벤트 생성·queue 전달만 추가하고 공개 모델은 유지해야 한다. 요청마다 캐시를 DB에 저장하는 방식은 중복과 실패 이력 누락을 일으키므로 사용하지 않는다.

writer 초기화·DB 연결 실패는 lifespan을 실패시키지 않는다. 수집은 시작하고 이력 상태만 degraded로 둔다. 저장 비활성도 지원하며 비활성 상태를 명시한다. 반면 기존 host 설정 오류·OS 호출 영구 정지는 Stage 1의 별도 제한이며 DB 분리로 해결됐다고 주장하지 않는다.

## 4. 서버 식별과 관계형 모델

공개 host.id (`local` 기본값)는 API 호환 별칭이다. DB 내부 `server_id` UUID는 서버 등록 때 한 번 발급해 재시작 후 재사용하며 실제 hostname·IP·사용자명으로 만들지 않는다. `servers.public_id`는 UNIQUE이고 최초 로컬 등록은 migration 또는 명시적 등록 절차로 수행한다. startup에서는 기존 등록을 조회할 뿐 자동 재등록·별칭 변경으로 새 서버를 만들지 않는다. 별칭이 누락되거나 충돌하면 저장만 degraded로 둔다. 별칭 변경·장비 교체는 운영자가 명시적으로 매핑을 결정한다.

초기 테이블은 `servers`와 `metric_samples` 두 개다. metric_samples는 측정 시도당 한 행으로 네 자원을 함께 저장한다. 필드별 EAV나 정상 응답 전체 JSON의 중복 저장은 하지 않는다.

| 필드 그룹      | 타입·의미                                                                                                               |
| -------------- | ----------------------------------------------------------------------------------------------------------------------- |
| servers        | server_id uuid PK, public_id varchar(64) UNIQUE, label varchar(80), platform, registered_at timestamptz(3)              |
| 이벤트 식별    | sample_id uuid PK, server_id FK (ON DELETE RESTRICT), run_id uuid, sequence bigint, UNIQUE(server_id, run_id, sequence) |
| 버전·관측 맥락 | payload_schema_version smallint = 1, collection_interval_seconds smallint = 5, platform, scope = local_system           |
| 시간           | observed_at timestamptz(3) NOT NULL, collected_at timestamptz(3) NULL, stored_at timestamptz(3) NOT NULL                |
| 상태           | status = ok/partial/failed/timeout, failure_reason NULL 또는 고정 코드, errors jsonb (자원·고정 code만)                 |
| CPU            | cpu_usage_percent numeric(4,1), cpu_window_ms bigint                                                                    |
| 메모리         | memory_total_bytes, memory_available_bytes, memory_used_bytes bigint; memory_usage_percent numeric(4,1)                 |
| 디스크         | disk_target_id = primary, disk_total_bytes, disk_used_bytes, disk_free_bytes bigint; disk_usage_percent numeric(4,1)    |
| uptime         | uptime_seconds bigint, booted_at timestamptz(3)                                                                         |

성공 자원은 필드 묶음 전체 NOT NULL, 실패 자원은 묶음 전체 NULL이다. SQL CHECK와 입력 검증으로 percent 0..100, 용량·시간의 비음수 및 JavaScript 안전 정수 상한 2^53-1, total>0, used/available/free<=total, memory_used=total-available, CPU window>0을 보장한다. 메모리 percent는 소수 1자리 반올림 허용 오차 0.051로 검증한다. errors 자원은 중복 없이 NULL 자원과 일치한다. JSONB 배열의 세부 일관성은 writer의 검증과 integration test로 보장한다. 오류 원문·경로·DSN은 저장하지 않는다.

ok에는 실패 자원이 없고 partial에는 1..3개가 있다. failed에는 모든 지표가 NULL이고 failure_reason=COLLECTION_FAILED, timeout에는 모든 지표가 NULL이고 failure_reason=COLLECTION_TIMEOUT이다. failed의 errors는 알려진 자원 실패 코드 4개 또는 수집 전체 예외일 때 빈 배열이다. timeout의 errors는 빈 배열이다. 제약 변경은 migration으로 한다.

platform/scope는 행에 당시 맥락을 보존한다. 디스크 대상 경로가 바뀌면 primary 의미도 달라지므로 초기 Stage 2에서는 동일 서버의 대상 변경을 운영상 금지하고, 변경이 필요하면 공개 target 버전 정책을 별도 설계한다. 개인 경로를 DB에 보관해 이 문제를 해결하지 않는다.

## 5. 측정 시각과 저장 시각

`collected_at`은 기존 Sample의 수집 완료 UTC 시각을 그대로 저장한다. CPU는 그 시각 한 점의 순간 사용률이 아닌 약 1초 평균이다. `observed_at`은 이력 정렬에 사용하는 사건 시각이다. 정상·부분 성공·전체 자원 실패 Sample에서는 collected_at과 같다. 수집 전체 예외와 timeout에서는 서비스가 실패 또는 3초 timeout을 판단한 UTC 시각이며 collected_at은 NULL이다. 종료·시작 예정 슬롯에 임의 측정값을 만들지 않는다.

`stored_at`은 실제 성공한 INSERT 시 DB의 statement_timestamp()로 설정하며 commit 시각을 뜻하지 않는다. 재시도·지연 저장에도 observed_at/collected_at/sample_id는 바꾸지 않고, 기존 행과 충돌하면 stored_at도 덮어쓰지 않는다. age_seconds는 조회 순간의 캐시 나이이므로 저장하지 않는다.

timestamptz는 UTC 순간을 저장하고 세션 timezone에 따라 출력하므로 DB 연결 timezone을 UTC로 설정하고 API는 밀리초 Z 문자열로 직렬화한다. 원래 timezone 이름은 저장되지 않는다. [PostgreSQL 날짜·시간 문서](https://www.postgresql.org/docs/current/datatype-datetime.html)를 따른다. 순서·stale·queue 만료 판단에는 monotonic을 사용한다. wall clock 역행은 사건 시각 정렬에 영향을 줄 수 있으며 run_id/sequence가 실제 시도 순서를 보완한다. 저장 시각>=측정 시각 CHECK는 두 시계 차이 때문에 두지 않는다.

## 6. 수집 실패 이력과 중복 방지

- 정상·partial: 해당 시도의 실제 값만 저장한다. 이전 성공 값을 실패 칼럼에 복사하지 않는다.
- 네 자원 전체 실패 Sample: failed 한 행과 collected_at 및 고정 오류 코드 저장. 기존 실시간 API는 503이다.
- 수집 전체 예외: failed 한 행, collected_at NULL, 고정 reason 저장.
- timeout: 3초 판정 순간에 timeout 한 행만 만든다. 이후 도착한 결과는 기존처럼 버리며 같은 시도에 성공 행을 추가하지 않는다.
- syscall이 계속 정지하면 새로운 시도도 없으므로 매 5초 실패 행을 만들어 채우지 않는다. 앱 중단 시간도 행이 없으며 구간을 unknown으로 표현한다.
- stale와 METRICS_NOT_READY는 API 조회 상태이며 측정 시도가 아니다. polling 횟수만큼 실패 행을 저장하지 않는다.

각 lifespan에 새 run_id, 각 실제 시도에 단조 증가 sequence와 랜덤 sample_id를 배정한다. timeout과 늦은 결과는 같은 시도 ID를 공유한다. 재시도 때 ID를 다시 만들지 않는다. PK와 UNIQUE 제약에 대해 `INSERT ... ON CONFLICT DO NOTHING`으로 commit 응답 유실 후 재전송도 중복 없이 처리한다. 충돌 키에 다른 payload가 오면 불변 이벤트 위반으로 계수하고 덮어쓰지 않는다. 타임스탬프만으로 중복을 판단하지 않아 같은 시각의 다른 시도를 보존한다. [PostgreSQL INSERT 문서](https://www.postgresql.org/docs/current/sql-insert.html)를 참고한다.

## 7. 저장 간격·트랜잭션·장애 처리

모든 실제 완료 시도 또는 실패 이벤트를 1회 저장 대상으로 한다. 정상 수집 시작 간격은 기존 5초, 초기 writer는 최대 20행 또는 oldest 대기 1초에서 flush한다. 이벤트가 드물면 약 5초당 한 행이다. 한 batch는 한 트랜잭션이며 전부 commit 또는 rollback한다. 기본 READ COMMITTED로 충분하고 commit된 행만 조회한다. 재시도는 동일 batch ID를 유지한다.

초기 queue는 **대기+in-flight 합계 120 이벤트**, 이벤트 하나의 직렬화 크기 상한 8 KiB로 제한한다. 최대 payload는 약 960 KiB이나 Python 객체 overhead는 별도 실측한다. queue full이면 가장 오래된 대기 이벤트를 버려 최근 사건을 우선한다. in-flight는 강제 수정하지 않으며 대기 이벤트가 없으면 신규 이벤트를 거절한다. 각 drop과 reason을 계수한다.

DB 연결·pool 획득은 각각 2초 상한, statement_timeout 2초, lock_timeout 500ms를 초기값으로 제안한다. writer batch의 전체 시도 deadline은 5초이며 rollback/연결 폐기도 deadline 내 처리하도록 driver 취소·연결 timeout을 검증한다. SQL timeout만으로 모든 네트워크 정지를 제어할 수 있다고 가정하지 않는다. 수집과 event loop는 이러한 지연을 기다리지 않는다. [PostgreSQL timeout 설정](https://www.postgresql.org/docs/current/runtime-config-client.html)을 참고한다.

연결 오류·일시적 timeout은 1/2/4/8/16/30초 capped backoff와 jitter로 재연결하고 단일 writer·단일 retry timer만 유지한다. constraint/schema/권한 오류는 빠르게 반복하지 않고 저장을 degraded로 표시하며 운영 조치 후 재시도한다. batch 내 검증 불가능 이벤트는 enqueue 전 거절하며, 영구 DB 오류로 batch를 처리하지 못하면 만료 정책을 적용하고 유실을 계수한다.

대기·실패한 in-flight 이벤트는 enqueue 이후 monotonic 기준 10분 만료다. 재시도마다 만료를 확인한다. 정상 5초 흐름에서 120개는 약 10분이지만 수집 정지·시계·DB 처리량에 따라 실제 보유 시간은 다르며 보존 보장이 아니다. ACK 불명확한 이벤트가 만료되면 DB에 이미 존재할 수도 있으므로 unconfirmed로 별도 계수한다.

## 8. DB 장애 시 실시간 유지와 상태 API

DB가 없어도 psutil·메모리 캐시·기존 health와 metrics는 계속 동작한다. 이력 읽기만 503 HISTORY_UNAVAILABLE로 응답하며 이전 이력 응답을 최신 조회처럼 내보내지 않는다. DB 결과 0행은 정상 200이며 장애와 구분한다. 읽기와 writer의 DB 연결을 분리하고 작은 pool(초기 총 4개 이하)·조회 동시 실행 2개·짧은 획득 timeout으로 읽기가 writer를 고갈시키지 않게 한다.

별도 `GET /api/history/status`는 DB 호출을 기다리지 않고 메모리 상태를 반환한다. mode=disabled/connecting/ready/degraded, last_committed_at, pending_events, dropped_events, unconfirmed_events, last_failure_code를 제공한다. 계수는 현재 run에서만 유효하며 재시작 후 0이고 영구 유실 장부가 아니다. ready는 마지막 저장 시도가 성공한 상태로 미래 성공을 보장하지 않는다. credential·DB 주소·예외 원문은 노출하지 않는다.

```json
{
  "schema_version": 1,
  "mode": "degraded",
  "run_id": "22222222-2222-4222-8222-222222222222",
  "last_committed_at": "2026-10-14T03:00:00.200Z",
  "pending_events": 120,
  "dropped_events": 8,
  "unconfirmed_events": 0,
  "last_failure_code": "DB_UNAVAILABLE"
}
```

## 9. 재시작·복구·유실 범위

PostgreSQL에 commit된 데이터는 앱·DB 정상 재시작 후 다시 조회한다. 새 lifespan은 새 run_id로 시작하고 기존 server_id를 재사용한다. 기존 행을 메모리 실시간 캐시에 로딩하지 않는다. 과거 값으로 시작 직후 METRICS_NOT_READY를 숨기지 않는다. migration 불일치·등록 누락은 저장/조회만 차단한다.

메모리 queue는 durable하지 않다. 프로세스 crash·강제 종료·reload로 미commit 데이터 최대 120개와 enqueue 전 현재 시도가 유실될 수 있다. commit 응답이 유실됐으면 실제 DB에는 일부 batch가 이미 있을 수 있다. DB 장애가 10분 이상이면 오래된 대기 이벤트가 만료되고, queue 포화면 더 일찍 drop될 수 있다. 종료 시 새 이벤트 전달을 멈추고 writer는 최대 5초 drain 후 남은 개수를 기록하며 종료한다. 기존 수집 스레드가 영구 정지하면 앱 전체 종료의 상한은 여전히 보장되지 않는다.

복구 후 queue의 남은 실제 이벤트만 재전송하고 없는 시도의 값을 보간하거나 Stage 1 시기 이력을 역으로 만들지 않는다. 디스크 spool·message broker·무손실 전달은 초기 범위에서 제외한다. DB volume 삭제·초기화·DROP/재생성으로 장애를 해결하지 않는다. DB 자체 crash 내구성은 fsync/synchronous_commit 등 안전 설정을 유지하는 조건이며 설정·스토리지별 검증이 필요하다. 디스크 손실까지 앱 재시작만으로 복구할 수 없으므로 승인된 운영 단계에서 별도 백업·복원 연습과 RPO/RTO를 정의한다. 초기 설계는 무손실 또는 백업 완료를 주장하지 않는다.

## 10. 데이터 증가량·보존·정리

정상 24시간 연속 실행, 5초당 한 행, 4개 자원을 한 행에 저장한다는 가정이다. timeout·정지 시 실제 행 수는 줄 수 있다.

| 기간  | 서버 1대 행 수 | 행+인덱스 0.5 KiB 추정 | 행+인덱스 1 KiB 추정 |
| ----- | -------------: | ---------------------: | -------------------: |
| 1시간 |            720 |              0.352 MiB |            0.703 MiB |
| 1일   |         17,280 |               8.44 MiB |            16.88 MiB |
| 7일   |        120,960 |              59.06 MiB |           118.12 MiB |
| 30일  |        518,400 |             253.12 MiB |           506.25 MiB |
| 365일 |      6,307,200 |               3.01 GiB |             6.02 GiB |

산식: 86400/5=17280행/일, bytes=행 수×512 또는 1024, MiB=bytes/2^20, GiB=bytes/2^30. 실패 JSON·행 header·PK/unique/조회/정리 인덱스 때문에 실제 크기는 달라진다. 추정은 benchmark가 아니며 WAL·백업·dead tuple·서버 기본 파일을 포함하지 않는다. 10대면 1년 약 30.1..60.2 GiB, 100대면 약 301..602 GiB로 선형 증가하며 영구 원본 보존은 권고하지 않는다. 최소 예상 상한의 2~3배 디스크 여유를 출발점으로 잡되 WAL/백업 요구는 별도 산정한다.

**초기 정책은 원본 모든 지표와 실패 이벤트 7일 보존**, 장기 rollup 없음이다. 시간별 평균만 남기면 CPU peak·부분 실패 맥락을 잃으므로 초기에는 원본을 유지한다. 장기 요구가 확인되면 1분 평균/min/max/유효 자원별 count·실패 count와 별도 보존 기간을 설계한다.

삭제 기준은 DB UTC now에서 7일 이전의 observed_at이다. clock 이상 이벤트는 입력 경계에서 서버 시각과 ±5분을 넘으면 저장 거절·고정 코드로 계수하고 운영 시계 점검을 요청한다. queued 이벤트의 검증은 enqueue 시점에 수행해 정상 지연 저장을 거절하지 않는다. 초기 로컬 동일 호스트 기준이며 다중 서버에서는 별도 clock skew 정책을 설계한다.

정리 worker는 앱당 하나, 시작 시 catch-up 후 1시간마다 최대 1000행씩 짧은 트랜잭션으로 삭제한다. 한 cycle 최대 10 batch, 남으면 다음 cycle에서 이어간다. writer와 별도 연결로 낮은 우선순위·짧은 lock/statement timeout을 적용한다. 실행 장애 시 보존은 일시적으로 7일+약 1시간보다 길어질 수 있고 오래 중단됐으면 여러 cycle이 필요하므로 삭제 완료 시간을 보장하지 않는다. 사용자 서버 등록·비대상 테이블은 삭제하지 않는다. 기본 정책을 문서화하고 실제 적용은 Stage 2 구현 승인 범위이며 이 설계 작업에서는 삭제하지 않는다.

DELETE는 파일을 즉시 축소하지 않으므로 autovacuum과 dead tuple·테이블 크기를 관찰한다. VACUUM FULL은 정상 정리 경로에 넣지 않는다. [PostgreSQL vacuum 문서](https://www.postgresql.org/docs/current/routine-vacuuming.html)를 참고한다.

## 11. 인덱스와 migration

PK(sample_id), UNIQUE(server_id,run_id,sequence), 조회 B-tree(server_id,observed_at,sample_id), 전체 정리용 B-tree(observed_at,sample_id)를 초기 인덱스로 한다. query는 서버·반개구간 시간 조건과 keyset을 사용한다. 지표 칼럼·errors JSONB에 기본 인덱스를 남발하지 않는다. EXPLAIN ANALYZE·실제 pg_total_relation_size로 비용과 앞 절의 가정을 구현 후 확인한다. 일별 partition·BRIN은 현재 7일/단일 서버 규모에는 넣지 않고 증가 후 판단한다.

공개 API payload_schema_version=1과 DB migration revision은 별개다. Alembic 후보의 순차 migration 파일로 테이블·제약·인덱스를 관리하고 revision 일치 여부를 저장 서비스 시작 전에 제한 시간 내 확인한다. 앱 시작 시 create_all·자동 upgrade·DB 초기화를 하지 않는다. migration은 별도 명시 명령과 DDL 역할로 실행하며 앱 역할은 대상 테이블 SELECT/INSERT만, 정리 역할은 SELECT/DELETE만 부여한다. 서버 등록 변경은 별도 운영 역할이다. schema CREATE 및 superuser 권한은 앱에 주지 않는다.

기존 데이터가 생긴 이후 migration은 백업·복원 가능성 확인, nullable 칼럼 추가→backfill→제약 추가 순서와 짧은 lock 정책을 검토한다. 실패 시 기존 revision·데이터를 유지하고 수정 migration 또는 검토된 복구를 사용한다. destructive downgrade로 자동 복구하지 않는다. 인증 DSN은 백엔드 환경에서만 읽고 VITE\_·JSON·로그에 넣지 않는다. 외부 DB 연결이 필요하면 인증서 검증을 유지하는 TLS와 명시적 네트워크 접근 정책을 별도로 승인받는다.

## 12. 기간별 원본 조회 API

`GET /api/metrics/history`를 추가하고 기존 두 API는 바꾸지 않는다. 요청은 query string이며 POST JSON body가 아니다. 아래 JSON은 같은 query parameter의 설명용 표현이다.

```http
GET /api/metrics/history?host_id=local&from=2026-10-14T03%3A00%3A00.000Z&to=2026-10-14T03%3A00%3A10.000Z&limit=500
```

```json
{
  "host_id": "local",
  "from": "2026-10-14T03:00:00.000Z",
  "to": "2026-10-14T03:00:10.000Z",
  "limit": 500
}
```

host_id는 등록 공개 별칭, from/to는 밀리초 UTC Z이고 필수다. 범위는 [from,to), from<to, 최대 7일. limit 기본 500, 최소 1, 최대 1000이다. 정렬은 observed_at ASC, sample_id ASC로 고정하고 임의 SQL 정렬·필드 선택을 받지 않는다. 서버 미등록은 404 HOST_NOT_FOUND, 잘못된 범위·limit·cursor는 422 INVALID_HISTORY_QUERY, DB 장애·migration 불일치·읽기 timeout은 503 HISTORY_UNAVAILABLE 및 Retry-After: 5, 예기치 않은 오류는 상세 없는 500이다. 모든 응답은 Cache-Control: no-store다.

```json
{
  "schema_version": 1,
  "host_id": "local",
  "range": {
    "from": "2026-10-14T03:00:00.000Z",
    "to": "2026-10-14T03:00:10.000Z"
  },
  "retention_seconds": 604800,
  "retention_cutoff": "2026-10-07T03:00:10.000Z",
  "snapshot_at": "2026-10-14T03:00:10.000Z",
  "items": [
    {
      "sample_id": "11111111-1111-4111-8111-111111111111",
      "observed_at": "2026-10-14T03:00:00.000Z",
      "collected_at": "2026-10-14T03:00:00.000Z",
      "stored_at": "2026-10-14T03:00:00.200Z",
      "status": "partial",
      "failure_reason": null,
      "payload_schema_version": 1,
      "platform": "darwin",
      "scope": "local_system",
      "collection_interval_seconds": 5,
      "metrics": {
        "cpu": { "usage_percent": 25.0, "measurement_window_ms": 1002 },
        "memory": {
          "total_bytes": 1073741824,
          "available_bytes": 536870912,
          "used_bytes": 536870912,
          "usage_percent": 50.0
        },
        "disk": null,
        "uptime": { "seconds": 3600, "booted_at": "2026-10-14T02:00:00.000Z" }
      },
      "errors": [{ "resource": "disk", "code": "COLLECTION_FAILED" }]
    },
    {
      "sample_id": "33333333-3333-4333-8333-333333333333",
      "observed_at": "2026-10-14T03:00:05.000Z",
      "collected_at": null,
      "stored_at": "2026-10-14T03:00:05.200Z",
      "status": "timeout",
      "failure_reason": "COLLECTION_TIMEOUT",
      "payload_schema_version": 1,
      "platform": "darwin",
      "scope": "local_system",
      "collection_interval_seconds": 5,
      "metrics": { "cpu": null, "memory": null, "disk": null, "uptime": null },
      "errors": []
    }
  ],
  "page": { "limit": 500, "has_more": false, "next_cursor": null },
  "coverage": "not_guaranteed"
}
```

`items=[]`는 저장된 행이 없다는 뜻이며 정상 측정이나 사용률 0을 의미하지 않는다. 보존 기한 이전 구간도 빈 결과로 반환하고 retention_cutoff를 명시한다. coverage=not_guaranteed는 수집 중단·drop·재시작으로 이력의 완전성을 증명할 수 없다는 고정 정책이며, 개별 결측 원인을 추측하지 않는다.

limit+1행을 조회해 has_more를 판단하고 초과할 때만 opaque cursor를 반환한다. cursor에는 version, host/range/limit, 마지막 observed_at/sample_id, 첫 응답의 snapshot_at과 retention_cutoff, 만료 시각을 인코딩하며 길이 상한 2048 bytes와 각 필드를 검증한다. cursor는 권한 증명이 아니다. 초기 localhost 전용 환경에서는 서명 없이도 검증된 값과 파라미터화 SQL로 처리하고, 외부 공개 시 인가와 서명은 별도로 설계한다. cursor TTL은 10분이며 만료 시 422를 반환하고 첫 페이지부터 다시 조회한다.

다음 페이지에도 모든 query parameter를 같은 값으로 보내며, (observed_at,sample_id)>cursor, 동일 시간 범위, stored_at<=snapshot_at 조건을 적용한다. OFFSET은 사용하지 않는다. 다만 stored_at은 commit 시각이 아니고 페이지 사이에 지연 commit이나 보존 기한에 따른 삭제가 발생할 수 있으므로 엄밀한 DB snapshot은 보장하지 않는다. 새 이력과 지연 저장된 행은 새 조회로 가져온다. 페이지 사이에 트랜잭션을 유지하지 않는다. 원본 행을 수정하지 않더라도 이러한 최선 노력 방식의 정합성 제한을 UI에 반영한다.

```json
{
  "error": {
    "code": 503,
    "message": "History unavailable",
    "reason": "HISTORY_UNAVAILABLE",
    "retryable": true
  }
}
```

## 13. React 과거 그래프

기존 health·최신 메트릭과 독립된 이력 패널에 15분/1시간/24시간/최대 7일 범위와 공개 host 선택을 제공한다. CPU·메모리·디스크는 0..100%의 개별 선, uptime은 초를 표시 단위로 변환한 선으로 표현한다. 용량은 tooltip에서 GiB로 표시하고 UTC 저장 시각은 브라우저 현지 시각으로 변환하며 timezone을 명시한다. 그래프 후보는 Recharts이며 채택과 의존성 추가는 구현 단계에서 결정한다.

기간 변경·unmount 시 AbortController 취소와 요청 세대 guard를 사용하며 이력 오류가 현재 metrics 상태를 바꾸지 않게 한다. 조회 중·빈 결과·일부 조회·DB 장애를 구분한다. 초기 화면은 15분으로 약 180행이다. API 페이지는 최대 1000행, UI 전체 조회는 최대 5000행으로 제한하고 상한에 도달하면 자동 추가를 멈추고 ‘일부 표시, 기간을 줄여주세요’를 표시한다. 7일 전체 120960행을 자동 조회하지 않는다. 장기간의 완전한 그래프에는 후속 bucket 집계 API가 필요하며, 초기 설계에서는 해상도를 낮춘 결과를 완전한 표시라고 설명하지 않는다.

partial의 결측 자원·failed·timeout은 NULL로 선을 끊는다. observed_at 간격이 10초를 초과할 때도 선을 끊고 예정된 5초 간격이 엄밀한 보장이 아님을 알린다. 연결선으로 결측을 채우거나 과거 값을 이어 붙이거나 0으로 대체하지 않는다. 마지막 점 이후에도 측정이 계속된 것처럼 선을 연장하지 않는다. uptime 감소는 재부팅 가능성으로 표시하고 장애로 단정하지 않는다.

## 14. 향후 다중 Linux 서버

server_id FK·공개 host·UTC·관측 platform/scope와 불변 sample ID로 서버별 분리는 가능하지만 여러 장비의 `local`을 같은 등록에 그대로 연결하지 않는다. 중앙 등록·고유 ID·agent 인증·발신자 권한·TLS·clock skew·관측 namespace/cgroup·디스크 대상 버전을 먼저 설계한다. 이번 범위에서는 원격 수신 endpoint나 agent를 만들지 않는다.

현재 단일 worker의 메모리 캐시와 queue는 여러 worker 사이에서 공유되지 않으며 DB UNIQUE만으로 이중 수집을 막을 수 없다. 다중 worker를 허용하기 전에 독립 collector 서비스와 공유 snapshot의 소유권을 결정한다. 초기 Stage 2도 Uvicorn worker 1개를 유지한다. Linux OS 실측과 container 값의 의미도 별도로 검증하고 현재 darwin 검증으로 지원 완료를 선언하지 않는다.

## 15. Stage 2A 확정 범위와 2B 전달 계약

범위 확정일: 2026-10-15. 앞 절은 Stage 2 전체 목표다. **Stage 2A는 DB 기반과 검증 가능한 스키마만 마련하며 실제 수집 결과를 DB에 저장하지 않는다.** 이 절은 구현 승인에 사용할 범위이며 이번 문서 수정은 설치·구현·DB 실행의 승인이 아니다.

### 2A 포함 범위

- PostgreSQL 연결 설정: 백엔드 전용 환경 설정, 저장 기능 기본 비활성, UTC 세션, 제한된 연결·pool 획득·SQL 대기 시간, 연결 자원 해제와 비밀정보 마스킹을 정의한다. DSN은 VITE\_·응답·로그에 노출하지 않는다.
- DB 드라이버 및 버전 선정: PostgreSQL 대상 버전과 Python 3.14 환경에서 사용할 드라이버·migration 도구의 정확한 버전을 구현 시 검증·고정한다. 후보는 psycopg 3와 Alembic이며 현재 설치·선정 완료로 간주하지 않는다.
- 서버 식별 모델: 공개 별칭과 내부 server_id의 매핑, 고유 제약, 명시적 최초 등록·재사용·충돌 처리를 정의한다. startup 자동 등록은 하지 않는다.
- 메트릭 저장 스키마: 앞 절의 servers/metric_samples, NULL 묶음·상태·단위·UTC·중복 방지 제약과 인덱스를 migration으로 표현한다. 업무 데이터 적재는 하지 않는다.
- 명시적 migration: 별도 명령으로 upgrade와 revision 확인을 수행하도록 설계한다. 앱 startup에서 자동 DDL·upgrade·초기화를 하지 않는다.
- DB 연결 실패 처리: 비활성·설정 오류·연결 불가·revision 불일치를 내부 고정 상태로 구분한다. DB 검사는 제한 시간 내 종료하고 기존 앱 lifespan·health·metrics·수집을 실패시키거나 차단하지 않는다. 새 공개 상태 API는 2A에 추가하지 않는다.
- 테스트용 독립 DB 및 migration 검증: 개발·사용자 DB와 구분되는 전용 대상의 명시적 설정을 요구한다. 대상 확인 실패 시 DB 테스트를 중단하고, 연결 문자열·자격증명은 출력하지 않는다. 기존 DB의 DROP·TRUNCATE·재생성·초기화에 의존하지 않는다.
- 최소 권한 계정 설계: migration DDL 역할, 서버 등록 운영 역할, 앱 SELECT/INSERT 역할, 향후 정리 SELECT/DELETE 역할을 분리한다. 2A에서는 정리 작업을 실행하지 않으며 superuser를 앱에 부여하지 않는다. 실제 계정 준비는 승인된 환경 범위에서만 수행한다.

### 2A 제외 범위

실제 메트릭 DB writer, 수집 서비스와 메모리 큐 연동, 저장 재시도·유실 정책 구현, 이력 조회 API 및 `/api/history/status`, React 이력 그래프, 자동 데이터 삭제, 백업·복구 구현은 제외한다. 앞 절의 이 정책들은 후속 단계 설계로 유지한다. DB 검증용 고정 fixture와 rollback 기반 제약 검사는 실제 메트릭 writer에 해당하지 않는다. Stage 1의 Sample·MetricsService·API 계약을 DB 저장 목적으로 변경하지 않는다.

### 2A 성공 기준

1. 정확한 DB·드라이버·migration 도구 버전과 지원 환경, 연결 설정·권한 준비 절차를 문서화하고 직접 의존성·실제 해결 잠금을 일치시킨다.
2. 비활성 상태에서는 DB 접속을 시도하지 않는다. 연결 불가·인증 실패·revision 불일치·등록 누락을 고정 내부 오류로 반환하며 기존 health JSON, metrics schema와 상태 코드, 5초 수집을 유지한다. 연결 시도가 event loop나 수집 executor를 장시간 점유하지 않는지 검증한다.
3. 승인된 전용 빈 테스트 DB에 명시적 upgrade 후 revision·테이블·제약·인덱스를 확인한다. 같은 upgrade를 재실행해 데이터와 revision이 보존됨을 확인하고, 앱 재시작이 schema를 자동 변경하지 않음을 검증한다.
4. 전용 DB의 트랜잭션 fixture로 정상·partial·failed·timeout, NULL 묶음, 수치 경계, FK·고유 제약·중복 방지 키를 검사한다. fixture DML은 rollback하고 migration DDL은 명시적으로 남긴다. 명시적 등록 fixture의 UUID 재사용도 검증한다. 기존 사용자 행을 삭제하지 않는다.
5. 앱 역할의 허용된 SELECT/INSERT와 금지된 DDL/DELETE를 검증한다. 연결 자원 종료, DSN·예외 상세 비노출을 확인하고 Stage 1 전체 회귀를 통과한다.
6. DB 도구·전용 대상·권한이 없으면 해당 DB 검증을 미실행 또는 skipped로 구분하고 성공으로 대체하지 않는다. 실제 PostgreSQL 검증이 남으면 2A 완료로 선언하지 않는다.

### 2B에 넘길 인터페이스

| 경계      | 2A 산출 계약                                                                                                          | 2B 책임                                                          |
| --------- | --------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| 설정·연결 | 저장 활성 여부, 백엔드 전용 DSN, timeout·UTC 정책을 담은 설정과 명시적 연결/해제 경계                                 | 별도 writer 실행 환경에서 연결 사용; 수집 경로에서 SQL 대기 금지 |
| 준비 상태 | 연결/스키마 점검 결과와 disabled/configuration_error/unavailable/schema_mismatch/ready 고정 내부 상태; 원문 예외 제외 | 등록 누락을 포함한 저장 상태 집계, 후속 status API 설계 연결     |
| 서버 식별 | 공개 host.id로 등록 server_id를 조회하는 읽기 경계; 미등록/충돌 고정 오류                                             | 이벤트의 server_id 고정과 등록 재사용; 자동 등록 금지            |
| 저장 모델 | sample_id/server_id/run_id/sequence, 시각·버전·상태·자원별 NULL과 오류 코드의 불변 입력 명세 및 DB 제약               | 실제 이벤트 ID 발급, Sample 변환, 실패·timeout 이벤트 생성       |
| 트랜잭션  | 명시적 연결·트랜잭션 관리 규칙, commit/rollback 책임과 중복 키 계약                                                   | INSERT 실행, batch 원자성, 재시도·불명확 ACK 처리 구현           |
| migration | 고정 revision과 검증된 upgrade 절차·테스트 fixture 규칙                                                               | startup 자동 upgrade 금지, 불일치 시 저장만 degraded 처리        |

위 표는 전달할 계약이며 실제 함수명·모듈 경로·클래스 API가 이미 존재한다는 뜻이 아니다. 2A 구현 시 단순한 구성으로 구체화하고 2B는 그 경계를 사용한다. 2B는 우선 writer·큐·재시도·유실 처리를 담당하며, 이력 API·그래프·자동 정리·백업 복구까지 모두 2B에 포함하는 것은 별도 범위 승인 없이 가정하지 않는다.

## 16. Stage 2 전체 구현 순서·완료 기준과 이번 검증 범위

1. 설계 확인 후 DB/드라이버 지원 버전·접속 권한·설정을 확정하고, 명시적 migration과 서버 등록을 구현한다. 빈 DB와 기존 데이터 DB 모두에서 revision·제약·재시작 지속성을 확인한다.
2. bounded queue와 독립 writer, 내부 이벤트 ID, partial·전체 실패·timeout, 중복 방지를 구현한다. DB 중단·지연·commit 응답 유실·queue full·만료·shutdown에서도 기존 health/metrics와 5초 수집을 보호하는 검증을 우선한다.
3. status와 기간/keyset 조회 API, 제한·고정 오류·DB 권한·비밀정보 비노출을 구현한다.
4. 원본 7일 retention과 작은 batch 삭제, 인덱스 query plan·실측 용량·backup/restore를 검증한다. 기존 DB를 초기화해 검증을 다시 시작하지 않는다.
5. React 이력 그래프의 NULL·결측·일부 조회·DB 장애를 구현하고, 기존 Stage 1 회귀와 실브라우저 확인을 수행한다.

완료 판단에는 위 구현 결과와 실행 검증이 필요하며 설계만으로 Stage 2 완료를 선언하지 않는다. 느린 writer가 수집 간격에 미치는 영향, HTTP p95, queue 메모리, 실제 DB 크기는 미측정이다. 드라이버 취소, PostgreSQL 실제 버전, migration runner, 백업 복원도 미확인이다.

이번 작업에서는 기존 코드·문서를 읽고 설계 충돌을 검토했다. JSON 문법·의미 예시, 로컬 문서 링크, Markdown 형식과 git diff 공백 검사를 별도로 수행하며 최종 실행 결과는 ChatGPT Handoff에 보고한다. 기존 자동 테스트·빌드·lint·DB SQL 실행·서버 실행·실측·부하 테스트는 하지 않는다. Stage 1 구현 문서의 통과 기록은 과거 결과이며 이번 결과로 바꾸지 않는다.
