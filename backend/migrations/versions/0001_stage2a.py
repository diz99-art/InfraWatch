"""Frozen initial schema. Do not import live app schema into this revision."""

from alembic import op


import json

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID

revision = "0001_stage2a"
down_revision = None
branch_labels = None
depends_on = None

metadata = sa.MetaData()
MAX_INTEGER = 2**53 - 1
PLATFORMS = "platform IN ('darwin','linux','win32','other')"
servers = sa.Table(
    "servers",
    metadata,
    sa.Column("server_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("public_id", sa.String(64), nullable=False, unique=True),
    sa.Column("label", sa.String(80), nullable=False),
    sa.Column("platform", sa.String(8), nullable=False),
    sa.Column(
        "registered_at",
        TIMESTAMP(timezone=True, precision=3),
        nullable=False,
        server_default=sa.text("statement_timestamp()"),
    ),
    sa.Column(
        "updated_at",
        TIMESTAMP(timezone=True, precision=3),
        nullable=False,
        server_default=sa.text("statement_timestamp()"),
    ),
    sa.CheckConstraint("public_id ~ '^[a-z0-9_-]{1,64}$'", name="server_public_id"),
    sa.CheckConstraint("length(label) BETWEEN 1 AND 80", name="server_label"),
    sa.CheckConstraint(PLATFORMS, name="server_platform"),
)

columns = [
    sa.Column("sample_id", UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "server_id",
        UUID(as_uuid=True),
        sa.ForeignKey("servers.server_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("run_id", UUID(as_uuid=True), nullable=False),
    sa.Column("sequence", sa.BigInteger, nullable=False),
    sa.Column("payload_schema_version", sa.SmallInteger, nullable=False),
    sa.Column("collection_interval_seconds", sa.SmallInteger, nullable=False),
    sa.Column("platform", sa.String(8), nullable=False),
    sa.Column("scope", sa.String(20), nullable=False),
    sa.Column("observed_at", TIMESTAMP(timezone=True, precision=3), nullable=False),
    sa.Column("collected_at", TIMESTAMP(timezone=True, precision=3)),
    sa.Column(
        "stored_at",
        TIMESTAMP(timezone=True, precision=3),
        nullable=False,
        server_default=sa.text("statement_timestamp()"),
    ),
    sa.Column("status", sa.String(8), nullable=False),
    sa.Column("failure_reason", sa.String(32)),
    sa.Column("errors", JSONB, nullable=False),
    sa.Column("disk_target_id", sa.String(7)),
    sa.Column("booted_at", TIMESTAMP(timezone=True, precision=3)),
]
resource_columns = {
    "cpu": ["cpu_usage_percent", "cpu_window_ms"],
    "memory": [
        "memory_total_bytes",
        "memory_available_bytes",
        "memory_used_bytes",
        "memory_usage_percent",
    ],
    "disk": [
        "disk_target_id",
        "disk_total_bytes",
        "disk_used_bytes",
        "disk_free_bytes",
        "disk_usage_percent",
    ],
    "uptime": ["uptime_seconds", "booted_at"],
}
for name in ["cpu_usage_percent", "memory_usage_percent", "disk_usage_percent"]:
    columns.append(sa.Column(name, sa.Numeric(4, 1)))
for name in [
    "cpu_window_ms",
    "memory_total_bytes",
    "memory_available_bytes",
    "memory_used_bytes",
    "disk_total_bytes",
    "disk_used_bytes",
    "disk_free_bytes",
    "uptime_seconds",
]:
    columns.append(sa.Column(name, sa.BigInteger))

constraints = [
    sa.UniqueConstraint("server_id", "run_id", "sequence", name="sample_attempt"),
    sa.CheckConstraint(f"sequence BETWEEN 1 AND {MAX_INTEGER}", name="sample_sequence"),
    sa.CheckConstraint(
        "payload_schema_version = 1 AND collection_interval_seconds = 5",
        name="sample_version",
    ),
    sa.CheckConstraint(PLATFORMS + " AND scope = 'local_system'", name="sample_scope"),
    sa.CheckConstraint(
        "disk_target_id IS NULL OR disk_target_id = 'primary'",
        name="sample_disk_target",
    ),
    sa.CheckConstraint(
        "booted_at IS NULL OR (collected_at IS NOT NULL AND booted_at <= collected_at)",
        name="sample_boot_time",
    ),
    sa.CheckConstraint(
        "collected_at IS NULL OR collected_at = observed_at", name="sample_time"
    ),
]
for resource, names in resource_columns.items():
    all_null = " AND ".join(f"{n} IS NULL" for n in names)
    all_set = " AND ".join(f"{n} IS NOT NULL" for n in names)
    constraints.append(
        sa.CheckConstraint(
            f"({all_null}) OR ({all_set})", name=f"sample_{resource}_group"
        )
    )
for col in columns:
    if isinstance(col.type, sa.BigInteger) and col.name != "sequence":
        minimum = (
            1
            if col.name in {"cpu_window_ms", "memory_total_bytes", "disk_total_bytes"}
            else 0
        )
        constraints.append(
            sa.CheckConstraint(
                f"{col.name} BETWEEN {minimum} AND {MAX_INTEGER}",
                name=f"range_{col.name}",
            )
        )
    if isinstance(col.type, sa.Numeric):
        constraints.append(
            sa.CheckConstraint(
                f"{col.name} BETWEEN 0 AND 100", name=f"range_{col.name}"
            )
        )
constraints += [
    sa.CheckConstraint(
        "memory_available_bytes <= memory_total_bytes AND memory_used_bytes = memory_total_bytes - memory_available_bytes AND abs(memory_usage_percent - memory_used_bytes::numeric / memory_total_bytes * 100) <= 0.051",
        name="sample_memory_values",
    ),
    sa.CheckConstraint(
        "disk_used_bytes <= disk_total_bytes AND disk_free_bytes <= disk_total_bytes",
        name="sample_disk_values",
    ),
]
missing = " + ".join(
    f"({names[0]} IS NULL)::integer" for names in resource_columns.values()
)
allowed = json.dumps(
    [
        {"resource": r, "code": c}
        for r in resource_columns
        for c in ["COLLECTION_FAILED", "INVALID_VALUE"]
    ]
)
constraints.append(
    sa.CheckConstraint(
        f"jsonb_typeof(errors) = 'array' AND errors <@ '{allowed}'::jsonb",
        name="sample_safe_errors",
    )
)
matched = []
for resource, names in resource_columns.items():
    contains = " OR ".join(
        f'errors @> \'[{{"resource":"{resource}","code":"{code}"}}]\'::jsonb'
        for code in ["COLLECTION_FAILED", "INVALID_VALUE"]
    )
    matched.append(f"(({names[0]} IS NULL) = ({contains}))")
constraints.append(
    sa.CheckConstraint(
        f"(status = 'ok' AND ({missing}) = 0 AND failure_reason IS NULL AND collected_at IS NOT NULL AND errors = '[]'::jsonb) OR "
        f"(status = 'partial' AND ({missing}) BETWEEN 1 AND 3 AND failure_reason IS NULL AND collected_at IS NOT NULL AND jsonb_array_length(errors) = ({missing}) AND {' AND '.join(matched)}) OR "
        f"(status = 'failed' AND ({missing}) = 4 AND failure_reason IS NOT NULL AND failure_reason = 'COLLECTION_FAILED' AND ((collected_at IS NULL AND errors = '[]'::jsonb) OR (collected_at IS NOT NULL AND jsonb_array_length(errors) = 4 AND {' AND '.join(matched)}))) OR "
        f"(status = 'timeout' AND ({missing}) = 4 AND failure_reason IS NOT NULL AND failure_reason = 'COLLECTION_TIMEOUT' AND collected_at IS NULL AND errors = '[]'::jsonb)",
        name="sample_state",
    )
)
metric_samples = sa.Table("metric_samples", metadata, *columns, *constraints)
sa.Index(
    "ix_samples_server_time",
    metric_samples.c.server_id,
    metric_samples.c.observed_at,
    metric_samples.c.sample_id,
)
sa.Index(
    "ix_samples_cleanup_time", metric_samples.c.observed_at, metric_samples.c.sample_id
)


def upgrade():
    metadata.create_all(op.get_bind(), checkfirst=False)


def downgrade():
    raise RuntimeError(
        "Destructive downgrade is disabled; use a reviewed recovery plan"
    )
