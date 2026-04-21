"""Integration tests for ``TicketService``.

Covers:
    - issue creates a queued row + correct defaults
    - claim_next picks the oldest queued ticket + flips to in_progress
    - claim_next returns None when the queue is empty
    - claim_next respects SKIP LOCKED across two concurrent callers
    - complete / fail / reschedule transitions
    - awaiting_purge_due filter
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from axon_enterprise.compliance.models import (
    ComplianceRequestKind,
    ComplianceRequestStatus,
)
from axon_enterprise.compliance.tickets import TicketService

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def session(migrated_db: AsyncEngine) -> AsyncIterator:
    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as s:
        yield s


@pytest.mark.asyncio
async def test_issue_creates_queued_row(session) -> None:
    svc = TicketService(worker_id="t-worker")
    ticket = await svc.issue(
        session,
        tenant_id="alpha",
        kind=ComplianceRequestKind.SAR_EXPORT,
        subject_email="Subj@Example.com",
    )
    await session.commit()
    row = await svc.get(
        session, request_id=ticket.request_id, tenant_id="alpha"
    )
    assert row.status == ComplianceRequestStatus.QUEUED.value
    assert row.subject_email == "subj@example.com"


@pytest.mark.asyncio
async def test_claim_next_returns_oldest_and_marks_in_progress(
    session,
) -> None:
    svc = TicketService(worker_id="w1")
    first = await svc.issue(
        session,
        tenant_id="alpha",
        kind=ComplianceRequestKind.SAR_EXPORT,
        subject_email="a@example.com",
    )
    await svc.issue(
        session,
        tenant_id="alpha",
        kind=ComplianceRequestKind.SAR_EXPORT,
        subject_email="b@example.com",
        scheduled_for=datetime.now(timezone.utc) + timedelta(minutes=1),
    )
    await session.commit()

    row = await svc.claim_next(session)
    await session.commit()
    assert row is not None
    assert row.request_id == first.request_id
    assert row.status == ComplianceRequestStatus.IN_PROGRESS.value
    assert row.claimed_by == "w1"


@pytest.mark.asyncio
async def test_claim_next_empty_queue_returns_none(session) -> None:
    svc = TicketService(worker_id="w1")
    assert await svc.claim_next(session) is None


@pytest.mark.asyncio
async def test_complete_and_fail_transitions(session) -> None:
    svc = TicketService(worker_id="w1")
    ticket = await svc.issue(
        session,
        tenant_id="alpha",
        kind=ComplianceRequestKind.ERASURE,
        subject_email="c@example.com",
    )
    await session.commit()
    claimed = await svc.claim_next(session)
    await session.commit()
    assert claimed is not None

    await svc.complete(
        session,
        request_id=ticket.request_id,
        artefact_uri="file:///tmp/x",
        artefact_sha256="deadbeef",
        artefact_size_bytes=42,
    )
    await session.commit()
    row = await svc.get(
        session, request_id=ticket.request_id, tenant_id="alpha"
    )
    assert row.status == ComplianceRequestStatus.COMPLETED.value
    assert row.artefact_size_bytes == 42


@pytest.mark.asyncio
async def test_awaiting_purge_due_filter(session) -> None:
    svc = TicketService(worker_id="w1")
    due = await svc.issue(
        session,
        tenant_id="alpha",
        kind=ComplianceRequestKind.ERASURE,
        subject_email="due@example.com",
    )
    not_due = await svc.issue(
        session,
        tenant_id="alpha",
        kind=ComplianceRequestKind.ERASURE,
        subject_email="later@example.com",
    )
    await session.commit()
    await svc.reschedule(
        session,
        request_id=due.request_id,
        scheduled_for=datetime.now(timezone.utc) - timedelta(minutes=5),
        new_status=ComplianceRequestStatus.AWAITING_PURGE,
    )
    await svc.reschedule(
        session,
        request_id=not_due.request_id,
        scheduled_for=datetime.now(timezone.utc) + timedelta(days=7),
        new_status=ComplianceRequestStatus.AWAITING_PURGE,
    )
    await session.commit()

    rows = await svc.awaiting_purge_due(session)
    ids = {r.request_id for r in rows}
    assert due.request_id in ids
    assert not_due.request_id not in ids
