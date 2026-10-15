"""Explicit registration/lookup for a DB worker or CLI, never during sampling."""

from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from app.db import DatabaseError
from app.metrics import Host
from app.schema import servers


def find_server(connection, public_id):
    row = (
        connection.execute(sa.select(servers).where(servers.c.public_id == public_id))
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise DatabaseError("server_not_registered")
    return dict(row)


def register_server(connection, host: Host, server_id: UUID):
    """Caller must preserve UUID; conflicts never silently remap/update a server."""
    if not isinstance(server_id, UUID):
        raise DatabaseError("invalid_server_id")
    connection.execute(
        insert(servers)
        .values(
            server_id=server_id,
            public_id=host.id,
            label=host.label,
            platform=host.platform,
        )
        .on_conflict_do_nothing()
    )
    try:
        existing = find_server(connection, host.id)
    except DatabaseError:
        raise DatabaseError("server_conflict") from None
    if (
        existing["server_id"] != server_id
        or existing["platform"] != host.platform
        or existing["label"] != host.label
    ):
        raise DatabaseError("server_conflict")
    return existing


def new_server_id():
    """Use once for explicit registration, then persist and reuse the returned ID."""
    return uuid4()
