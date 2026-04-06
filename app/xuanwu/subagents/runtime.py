# -*- coding: utf-8 -*-
"""Executable runtime manager for subagent lifecycle."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from app.xuanwu.session.context import ChatType, SessionKey, SessionScope
from app.xuanwu.subagents.models import (
    SpawnSubagentRequest,
    SubagentContextPack,
    SubagentExecutionRequest,
    SubagentExecutionResult,
    SubagentRunRecord,
    SubagentRunStatus,
    utc_now,
)

SubagentExecutor = Callable[[SubagentExecutionRequest], Awaitable[SubagentExecutionResult]]
SubagentRunTerminalHook = Callable[[SubagentRunRecord], Awaitable[None]]
SubagentBatchTerminalHook = Callable[[dict[str, Any]], Awaitable[None]]
SubagentStatusHook = Callable[[dict[str, Any]], Awaitable[None]]


class SubagentSpawnPolicyError(ValueError):
    """Raised when spawn is rejected by thread-level batch policy."""

    def __init__(self, outcome: str, message: str) -> None:
        super().__init__(message)
        self.outcome = outcome
        self.message = message


class SubagentRuntimeManager:
    """Manage detached subagent runs with persistence and control operations."""

    def __init__(
        self,
        *,
        workspace_path: str,
        max_spawn_depth: int = 1,
        max_children_per_session: int = 5,
        max_concurrent_subagents: int = 8,
        default_timeout_seconds: int = 900,
        steer_rate_limit_ms: int = 2000,
        max_queued_batches_per_controller: int = 1,
        stalled_after_seconds: int = 180,
        retention_seconds: int = 3600,
        sweep_interval_seconds: int = 60,
        on_run_terminal: Optional[SubagentRunTerminalHook] = None,
        on_batch_terminal: Optional[SubagentBatchTerminalHook] = None,
        on_status: Optional[SubagentStatusHook] = None,
    ) -> None:
        self.workspace_path = Path(workspace_path).resolve()
        self.max_spawn_depth = max(1, int(max_spawn_depth))
        self.max_children_per_session = max(1, int(max_children_per_session))
        self.max_concurrent_subagents = max(1, int(max_concurrent_subagents))
        self.default_timeout_seconds = max(0, int(default_timeout_seconds))
        self.steer_rate_limit_ms = max(0, int(steer_rate_limit_ms))
        self.max_queued_batches_per_controller = max(0, int(max_queued_batches_per_controller))
        self.stalled_after_seconds = max(30, int(stalled_after_seconds))
        self.retention_seconds = max(300, int(retention_seconds))
        self.sweep_interval_seconds = max(5, int(sweep_interval_seconds))

        self._runs: dict[str, dict[str, SubagentRunRecord]] = defaultdict(dict)
        self._tasks: dict[str, dict[str, asyncio.Task]] = defaultdict(dict)
        self._executors: dict[str, dict[str, SubagentExecutor]] = defaultdict(dict)
        self._controller_executors: dict[str, dict[str, SubagentExecutor]] = defaultdict(dict)
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._controller_queues: dict[str, dict[str, list[str]]] = defaultdict(
            lambda: defaultdict(list)
        )
        self._steer_limits: dict[str, float] = {}
        self._sweeper_task: Optional[asyncio.Task] = None
        self._started = False
        self._on_run_terminal = on_run_terminal
        self._on_batch_terminal = on_batch_terminal
        self._on_status = on_status

    async def start(self) -> None:
        """Restore persisted records and start housekeeping loops."""
        if self._started:
            return
        await self._restore_all_users()
        self._sweeper_task = asyncio.create_task(self._sweeper_loop())
        self._started = True

    async def stop(self) -> None:
        """Stop housekeeping and cancel active tasks."""
        if self._sweeper_task is not None:
            self._sweeper_task.cancel()
            try:
                await self._sweeper_task
            except asyncio.CancelledError:
                pass
            self._sweeper_task = None

        for user_id, user_tasks in self._tasks.items():
            for run_id, task in list(user_tasks.items()):
                record = self._runs.get(user_id, {}).get(run_id)
                if record is not None and not record.status.is_terminal:
                    record.status = SubagentRunStatus.KILLED
                    record.error = "runtime_stopped"
                    record.ended_at = utc_now()
                task.cancel()
        await self._persist_all()
        self._controller_queues.clear()
        self._controller_executors.clear()
        self._started = False

    async def spawn(
        self,
        request: SpawnSubagentRequest,
        *,
        executor: SubagentExecutor,
    ) -> SubagentRunRecord:
        """Register and schedule a detached subagent run."""
        self._validate_spawn_request(request)
        user_id = request.user_id
        lock = self._locks[user_id]
        selected_record: Optional[SubagentRunRecord] = None
        pending_status_events: list[dict[str, Any]] = []
        policy_error: Optional[SubagentSpawnPolicyError] = None
        async with lock:
            self._controller_executors[user_id][request.controller_session_key] = executor
            queue_on_busy = False
            if request.single_active_batch:
                idempotent = self._resolve_idempotent_run(
                    user_id=user_id,
                    controller_session_key=request.controller_session_key,
                    idempotency_key=request.idempotency_key,
                )
                if idempotent is not None:
                    idempotent.metadata.setdefault("spawn_outcome", "continue_current_batch")
                    selected_record = idempotent
                    pending_status_events.append(
                        self._build_status_payload(
                            idempotent,
                            event="spawn",
                            outcome="continue_current_batch",
                            message="Continuing current subagent batch.",
                            queue_depth=self._count_queued_for_controller(
                                user_id=user_id,
                                controller_session_key=request.controller_session_key,
                            ),
                        )
                    )

                active_run = None
                if selected_record is None:
                    active_run = self._latest_active_run_for_controller(
                        user_id=user_id,
                        controller_session_key=request.controller_session_key,
                    )
                if selected_record is None and active_run is not None:
                    if not request.queue_if_busy:
                        active_run.metadata.setdefault("spawn_outcome", "continue_current_batch")
                        selected_record = active_run
                        pending_status_events.append(
                            self._build_status_payload(
                                active_run,
                                event="spawn",
                                outcome="continue_current_batch",
                                message="Continuing current subagent batch.",
                                queue_depth=self._count_queued_for_controller(
                                    user_id=user_id,
                                    controller_session_key=request.controller_session_key,
                                ),
                            )
                        )
                    else:
                        queue_on_busy = True
                        queued_count = self._count_queued_for_controller(
                            user_id=user_id,
                            controller_session_key=request.controller_session_key,
                        )
                        if queued_count >= self.max_queued_batches_per_controller:
                            policy_error = SubagentSpawnPolicyError(
                                "rejected_queue_full",
                                "thread queue is full",
                            )

            if selected_record is None and policy_error is None:
                if (not queue_on_busy) and self._count_active_for_user(user_id) >= self.max_concurrent_subagents:
                    raise ValueError("max_concurrent_subagents limit reached")
                if (
                    (not queue_on_busy)
                    and
                    self._count_active_for_controller(user_id, request.controller_session_key)
                    >= self.max_children_per_session
                ):
                    raise ValueError("max_children_per_session limit reached")

            if selected_record is None and policy_error is None:
                run_id = SubagentRunRecord.generate_run_id()
                subagent_id = SubagentRunRecord.generate_subagent_id()
                timeout_seconds = (
                    request.timeout_seconds
                    if request.timeout_seconds > 0
                    else self.default_timeout_seconds
                )
                child_session_key = request.child_session_key or self._build_child_session_key(
                    requester_session_key=request.requester_session_key,
                    subagent_id=subagent_id,
                    user_id=request.user_id,
                )
                record = SubagentRunRecord(
                    run_id=run_id,
                    subagent_id=subagent_id,
                    user_id=request.user_id,
                    requester_session_key=request.requester_session_key,
                    controller_session_key=request.controller_session_key,
                    child_session_key=child_session_key,
                    task=request.task,
                    depth=request.depth,
                    timeout_seconds=timeout_seconds,
                    cleanup_policy=request.cleanup_policy,
                    label=request.label,
                    model=request.model,
                    parent_run_id=request.parent_run_id,
                    metadata={
                        **(request.metadata or {}),
                        "context_pack": request.context_pack.to_dict(),
                        "summary_chars": request.context_pack.summary_chars,
                        "tail_messages": request.context_pack.tail_messages,
                        "tail_chars": request.context_pack.tail_chars,
                        "truncated": request.context_pack.truncated,
                        "batch_id": request.batch_id or SubagentRunRecord.generate_run_id(),
                        "idempotency_key": request.idempotency_key or "",
                    },
                )
                should_queue = bool(queue_on_busy)
                self._runs[user_id][run_id] = record
                self._executors[user_id][run_id] = executor
                if should_queue:
                    record.metadata["spawn_outcome"] = "queued_next_request"
                    record.metadata["queue_state"] = "queued"
                    self._controller_queues[user_id][request.controller_session_key].append(run_id)
                    queue_depth = self._count_queued_for_controller(
                        user_id=user_id,
                        controller_session_key=request.controller_session_key,
                    )
                    pending_status_events.append(
                        self._build_status_payload(
                            record,
                            event="spawn",
                            outcome="queued_next_request",
                            message="Current batch is running. Request queued.",
                            queue_depth=queue_depth,
                        )
                    )
                    selected_record = record
                else:
                    record.metadata["spawn_outcome"] = "accepted"
                    self._start_run_task(user_id=user_id, run_id=run_id, executor=executor)
                    pending_status_events.append(
                        self._build_status_payload(
                            record,
                            event="spawn",
                            outcome="accepted",
                            message="Subagent request accepted.",
                            queue_depth=self._count_queued_for_controller(
                                user_id=user_id,
                                controller_session_key=request.controller_session_key,
                            ),
                        )
                    )
                    selected_record = record
                await self._persist_user(user_id)

        if policy_error is not None:
            await self._emit_status(
                {
                    "event": "spawn",
                    "outcome": policy_error.outcome,
                    "message": policy_error.message,
                    "user_id": user_id,
                    "controller_session_key": request.controller_session_key,
                    "queue_depth": self._count_queued_for_controller(
                        user_id=user_id,
                        controller_session_key=request.controller_session_key,
                    ),
                }
            )
            raise policy_error
        for payload in pending_status_events:
            await self._emit_status(payload)
        if selected_record is None:
            raise RuntimeError("subagent spawn produced no record")
        return selected_record

    def _start_run_task(self, *, user_id: str, run_id: str, executor: SubagentExecutor) -> None:
        task = asyncio.create_task(
            self._execute_run(
                user_id=user_id,
                run_id=run_id,
                executor=executor,
            )
        )
        self._tasks[user_id][run_id] = task

    def _resolve_idempotent_run(
        self,
        *,
        user_id: str,
        controller_session_key: str,
        idempotency_key: str,
    ) -> Optional[SubagentRunRecord]:
        normalized_key = (idempotency_key or "").strip()
        if not normalized_key:
            return None
        for item in self._runs.get(user_id, {}).values():
            if item.controller_session_key != controller_session_key:
                continue
            if str(item.metadata.get("idempotency_key", "")).strip() != normalized_key:
                continue
            if item.status.is_terminal:
                continue
            return item
        return None

    def _is_queued(self, record: SubagentRunRecord) -> bool:
        return str(record.metadata.get("queue_state", "")).strip().lower() == "queued"

    def _count_queued_for_controller(self, *, user_id: str, controller_session_key: str) -> int:
        queue = self._controller_queues.get(user_id, {}).get(controller_session_key, [])
        total = 0
        for run_id in queue:
            record = self._runs.get(user_id, {}).get(run_id)
            if record is None:
                continue
            if record.status.is_terminal:
                continue
            total += 1
        return total

    def _latest_active_run_for_controller(
        self,
        *,
        user_id: str,
        controller_session_key: str,
    ) -> Optional[SubagentRunRecord]:
        candidates = [
            item
            for item in self._runs.get(user_id, {}).values()
            if item.controller_session_key == controller_session_key
            and item.status in {SubagentRunStatus.PENDING, SubagentRunStatus.RUNNING}
            and not self._is_queued(item)
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda item: item.created_at, reverse=True)
        return candidates[0]

    def _pop_next_queued_for_controller(
        self,
        *,
        user_id: str,
        controller_session_key: str,
    ) -> Optional[SubagentRunRecord]:
        queue = self._controller_queues.get(user_id, {}).get(controller_session_key, [])
        while queue:
            next_run_id = queue.pop(0)
            record = self._runs.get(user_id, {}).get(next_run_id)
            if record is None or record.status.is_terminal:
                continue
            record.metadata.pop("queue_state", None)
            record.metadata["spawn_outcome"] = "accepted_from_queue"
            return record
        return None

    async def _activate_next_queued_for_controller(
        self,
        *,
        user_id: str,
        controller_session_key: str,
    ) -> Optional[SubagentRunRecord]:
        if self._latest_active_run_for_controller(
            user_id=user_id,
            controller_session_key=controller_session_key,
        ) is not None:
            return None
        next_record = self._pop_next_queued_for_controller(
            user_id=user_id,
            controller_session_key=controller_session_key,
        )
        if next_record is None:
            return None
        executor = self._executors.get(user_id, {}).get(next_record.run_id)
        if executor is None:
            next_record.status = SubagentRunStatus.FAILED
            next_record.error = "executor_unavailable_for_queued_run"
            next_record.ended_at = utc_now()
            return next_record
        self._start_run_task(user_id=user_id, run_id=next_record.run_id, executor=executor)
        await self._persist_user(user_id)
        return next_record

    def _collect_batch_runs(
        self,
        *,
        user_id: str,
        controller_session_key: str,
        batch_id: str,
    ) -> list[SubagentRunRecord]:
        normalized_batch_id = (batch_id or "").strip()
        if not normalized_batch_id:
            return []
        return [
            item
            for item in self._runs.get(user_id, {}).values()
            if item.controller_session_key == controller_session_key
            and str(item.metadata.get("batch_id", "")).strip() == normalized_batch_id
        ]

    def _try_build_batch_receipt_locked(
        self,
        *,
        user_id: str,
        controller_session_key: str,
        batch_id: str,
    ) -> Optional[dict[str, Any]]:
        runs = self._collect_batch_runs(
            user_id=user_id,
            controller_session_key=controller_session_key,
            batch_id=batch_id,
        )
        if not runs:
            return None
        if not all(item.status.is_terminal for item in runs):
            return None
        if any(bool(item.metadata.get("batch_receipt_emitted")) for item in runs):
            return None

        completed = sum(1 for item in runs if item.status == SubagentRunStatus.COMPLETED)
        failed = sum(
            1
            for item in runs
            if item.status in {SubagentRunStatus.FAILED, SubagentRunStatus.TIMED_OUT}
        )
        canceled = sum(1 for item in runs if item.status == SubagentRunStatus.KILLED)
        for item in runs:
            item.metadata["batch_receipt_emitted"] = True
        return {
            "user_id": user_id,
            "controller_session_key": controller_session_key,
            "batch_id": batch_id,
            "completed": completed,
            "failed": failed,
            "canceled": canceled,
            "total": len(runs),
            "run_ids": [item.run_id for item in runs],
        }

    async def _emit_run_terminal(self, record: SubagentRunRecord) -> None:
        if self._on_run_terminal is None:
            return
        try:
            await self._on_run_terminal(record)
        except Exception:
            return

    async def _emit_batch_terminal(self, payload: dict[str, Any]) -> None:
        if self._on_batch_terminal is None:
            return
        try:
            await self._on_batch_terminal(payload)
        except Exception:
            return

    async def _emit_status(self, payload: dict[str, Any]) -> None:
        if self._on_status is None:
            return
        try:
            await self._on_status(dict(payload))
        except Exception:
            return

    def _build_status_payload(
        self,
        record: SubagentRunRecord,
        *,
        event: str,
        outcome: str = "",
        message: str = "",
        queue_depth: Optional[int] = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "event": event,
            "user_id": record.user_id,
            "controller_session_key": record.controller_session_key,
            "requester_session_key": record.requester_session_key,
            "run_id": record.run_id,
            "subagent_id": record.subagent_id,
            "status": record.status.value,
            "batch_id": str((record.metadata or {}).get("batch_id", "")),
            "queue_state": str((record.metadata or {}).get("queue_state", "")),
            "spawn_outcome": str((record.metadata or {}).get("spawn_outcome", "")),
            "child_session_key": record.child_session_key,
            "stalled": bool((record.metadata or {}).get("stalled", False)),
            "updated_at": utc_now().isoformat(),
        }
        if outcome:
            payload["outcome"] = outcome
        if message:
            payload["message"] = message
        if queue_depth is not None:
            payload["queue_depth"] = int(queue_depth)
        if record.error:
            payload["error"] = str(record.error)
        return payload

    async def get_run(self, user_id: str, run_id: str) -> Optional[SubagentRunRecord]:
        """Return a run by identifier."""
        return self._runs.get(user_id, {}).get(run_id)

    async def list_controlled_runs(
        self,
        user_id: str,
        controller_session_key: str,
    ) -> list[SubagentRunRecord]:
        """List runs visible to controller sorted by creation time desc."""
        records = [
            item
            for item in self._runs.get(user_id, {}).values()
            if item.controller_session_key == controller_session_key
            or item.requester_session_key == controller_session_key
        ]
        records.sort(key=lambda item: item.created_at, reverse=True)
        return records

    async def list_runs_view(
        self,
        user_id: str,
        controller_session_key: str,
        recent_minutes: int = 30,
    ) -> dict[str, Any]:
        """Return active/recent view used by `subagents list`."""
        records = await self.list_controlled_runs(user_id, controller_session_key)
        now = utc_now()
        recent_cutoff = now - timedelta(minutes=max(1, int(recent_minutes)))
        active: list[SubagentRunRecord] = []
        recent: list[SubagentRunRecord] = []
        for item in records:
            if item.status in {SubagentRunStatus.PENDING, SubagentRunStatus.RUNNING}:
                if item.status == SubagentRunStatus.RUNNING and item.started_at is not None:
                    elapsed = (now - item.started_at).total_seconds()
                    item.metadata["stalled"] = elapsed >= self.stalled_after_seconds
                active.append(item)
                continue
            if item.ended_at and item.ended_at >= recent_cutoff:
                recent.append(item)
        active_batch = self._latest_active_run_for_controller(
            user_id=user_id,
            controller_session_key=controller_session_key,
        )
        return {
            "total": len(records),
            "active": active,
            "recent": recent,
            "active_batch_id": (
                str((active_batch.metadata or {}).get("batch_id", ""))
                if active_batch is not None
                else ""
            ),
            "queue_depth": self._count_queued_for_controller(
                user_id=user_id,
                controller_session_key=controller_session_key,
            ),
        }

    async def resolve_controlled_target(
        self,
        user_id: str,
        controller_session_key: str,
        target: str,
    ) -> Optional[SubagentRunRecord]:
        """Resolve target by run_id/subagent_id/prefix for controller-owned runs."""
        normalized = (target or "").strip()
        if not normalized:
            return None
        records = await self.list_controlled_runs(user_id, controller_session_key)
        if not records:
            return None
        exact_run = [item for item in records if item.run_id == normalized]
        if len(exact_run) == 1:
            return exact_run[0]
        exact_sub = [item for item in records if item.subagent_id == normalized]
        if len(exact_sub) == 1:
            return exact_sub[0]
        prefix = [
            item
            for item in records
            if item.run_id.startswith(normalized) or item.subagent_id.startswith(normalized)
        ]
        if len(prefix) == 1:
            return prefix[0]
        return None

    async def kill_all_for_controller(
        self,
        user_id: str,
        controller_session_key: str,
    ) -> int:
        """Kill all active runs controlled by requester session."""
        records = await self.list_controlled_runs(user_id, controller_session_key)
        total = 0
        for item in records:
            if item.status in {SubagentRunStatus.PENDING, SubagentRunStatus.RUNNING}:
                total += await self.kill_run(user_id, item.run_id, reason="killed", cascade=True)
        return total

    async def kill_batch(
        self,
        *,
        user_id: str,
        controller_session_key: str,
        batch_id: str,
        reason: str = "killed_batch",
    ) -> int:
        """Kill all runs belonging to one batch under the same controller."""
        normalized_batch_id = (batch_id or "").strip()
        if not normalized_batch_id:
            return 0
        records = await self.list_controlled_runs(user_id, controller_session_key)
        targets = [
            item.run_id
            for item in records
            if str(item.metadata.get("batch_id", "")).strip() == normalized_batch_id
            and item.status in {SubagentRunStatus.PENDING, SubagentRunStatus.RUNNING}
        ]
        total = 0
        for run_id in targets:
            total += await self.kill_run(user_id, run_id, reason=reason, cascade=True)
        return total

    async def kill_run(
        self,
        user_id: str,
        run_id: str,
        *,
        reason: str = "killed",
        cascade: bool = True,
    ) -> int:
        """Kill a run and optionally all descendants."""
        lock = self._locks[user_id]
        async with lock:
            targets = [run_id]
            if cascade:
                targets.extend(self._collect_descendants(user_id, run_id))
            killed = 0
            now = utc_now()
            affected_controllers: set[str] = set()
            terminal_records: list[SubagentRunRecord] = []
            batch_receipts: list[dict[str, Any]] = []
            activated_records: list[SubagentRunRecord] = []
            for target_run_id in targets:
                record = self._runs.get(user_id, {}).get(target_run_id)
                if record is None or record.status.is_terminal:
                    continue
                affected_controllers.add(record.controller_session_key)
                record.metadata["kill_reason"] = reason
                record.metadata["partial"] = True
                task = self._tasks.get(user_id, {}).get(target_run_id)
                if task is not None:
                    task.cancel()
                record.status = SubagentRunStatus.KILLED
                record.error = reason
                record.ended_at = now
                queue = self._controller_queues.get(user_id, {}).get(record.controller_session_key, [])
                if target_run_id in queue:
                    queue[:] = [item for item in queue if item != target_run_id]
                terminal_records.append(SubagentRunRecord.from_dict(record.to_dict()))
                killed += 1
            if killed > 0:
                for controller_session_key in affected_controllers:
                    activated = await self._activate_next_queued_for_controller(
                        user_id=user_id,
                        controller_session_key=controller_session_key,
                    )
                    if activated is not None:
                        activated_records.append(SubagentRunRecord.from_dict(activated.to_dict()))
                for record in terminal_records:
                    batch_id = str((record.metadata or {}).get("batch_id", "")).strip()
                    if not batch_id:
                        continue
                    summary = self._try_build_batch_receipt_locked(
                        user_id=user_id,
                        controller_session_key=record.controller_session_key,
                        batch_id=batch_id,
                    )
                    if summary is not None:
                        batch_receipts.append(summary)
                await self._persist_user(user_id)
        for item in terminal_records:
            await self._emit_run_terminal(item)
            await self._emit_status(
                self._build_status_payload(
                    item,
                    event="run_terminal",
                    outcome=item.status.value,
                    message="Subagent run reached terminal state.",
                    queue_depth=self._count_queued_for_controller(
                        user_id=user_id,
                        controller_session_key=item.controller_session_key,
                    ),
                )
            )
        for item in activated_records:
            await self._emit_status(
                self._build_status_payload(
                    item,
                    event="run_activated",
                    outcome="accepted_from_queue",
                    message="Queued subagent request is now running.",
                    queue_depth=self._count_queued_for_controller(
                        user_id=user_id,
                        controller_session_key=item.controller_session_key,
                    ),
                )
            )
        for receipt in batch_receipts:
            await self._emit_batch_terminal(receipt)
        return killed

    async def steer_run(
        self,
        *,
        user_id: str,
        controller_session_key: str,
        run_id: str,
        message: str,
    ) -> Optional[SubagentRunRecord]:
        """Restart a run with steering message and return replacement record."""
        target = await self.get_run(user_id, run_id)
        if target is None:
            return None
        if (
            target.controller_session_key != controller_session_key
            and target.requester_session_key != controller_session_key
        ):
            raise ValueError("forbidden")
        if target.status not in {SubagentRunStatus.PENDING, SubagentRunStatus.RUNNING}:
            return None
        if self.steer_rate_limit_ms > 0:
            now_ms = datetime.now(timezone.utc).timestamp() * 1000.0
            rate_key = f"{controller_session_key}:{target.child_session_key}"
            last_ms = self._steer_limits.get(rate_key, 0.0)
            if now_ms - last_ms < self.steer_rate_limit_ms:
                raise ValueError("steer rate limit exceeded")
            self._steer_limits[rate_key] = now_ms

        executor = self._executors.get(user_id, {}).get(run_id)
        if executor is None:
            return None

        await self.kill_run(user_id, run_id, reason="steer_restart", cascade=False)
        composed_task = self._compose_steer_task(target.task, message)
        context_pack = target.metadata.get("context_pack", {})
        replacement = await self.spawn(
            SpawnSubagentRequest(
                user_id=user_id,
                requester_session_key=target.requester_session_key,
                controller_session_key=target.controller_session_key,
                task=composed_task,
                depth=target.depth,
                timeout_seconds=target.timeout_seconds,
                label=target.label,
                model=target.model,
                parent_run_id=target.parent_run_id,
                cleanup_policy=target.cleanup_policy,
                context_pack=target_context_pack_from_dict(context_pack),
                child_session_key=target.child_session_key,
                metadata={
                    **dict(target.metadata),
                    "replaces_run_id": target.run_id,
                    "steer_message": message,
                },
                batch_id=str((target.metadata or {}).get("batch_id", "")),
                single_active_batch=True,
                queue_if_busy=False,
            ),
            executor=executor,
        )
        return replacement

    async def retry_run(
        self,
        *,
        user_id: str,
        controller_session_key: str,
        run_id: str,
        edited_task: str = "",
    ) -> Optional[SubagentRunRecord]:
        """Retry one terminal run using the same or edited task context."""
        target = await self.get_run(user_id, run_id)
        if target is None:
            return None
        if (
            target.controller_session_key != controller_session_key
            and target.requester_session_key != controller_session_key
        ):
            raise ValueError("forbidden")
        if not target.status.is_terminal:
            return None
        executor = self._controller_executors.get(user_id, {}).get(target.controller_session_key)
        if executor is None:
            return None
        retry_task = (edited_task or "").strip() or target.task
        context_pack = target.metadata.get("context_pack", {})
        replacement = await self.spawn(
            SpawnSubagentRequest(
                user_id=user_id,
                requester_session_key=target.requester_session_key,
                controller_session_key=target.controller_session_key,
                task=retry_task,
                depth=target.depth,
                timeout_seconds=target.timeout_seconds,
                label=target.label,
                model=target.model,
                parent_run_id=target.parent_run_id,
                cleanup_policy=target.cleanup_policy,
                context_pack=target_context_pack_from_dict(context_pack),
                metadata={
                    **dict(target.metadata),
                    "retries_run_id": target.run_id,
                    "retry_mode": "retry_with_edit" if edited_task.strip() else "retry_same_context",
                },
                single_active_batch=True,
                queue_if_busy=True,
            ),
            executor=executor,
        )
        return replacement

    async def _execute_run(
        self,
        *,
        user_id: str,
        run_id: str,
        executor: SubagentExecutor,
    ) -> None:
        record = self._runs.get(user_id, {}).get(run_id)
        if record is None:
            return
        lock = self._locks[user_id]
        started_snapshot: Optional[SubagentRunRecord] = None
        async with lock:
            record.status = SubagentRunStatus.RUNNING
            record.started_at = utc_now()
            started_snapshot = SubagentRunRecord.from_dict(record.to_dict())
            await self._persist_user(user_id)
        if started_snapshot is not None:
            await self._emit_status(
                self._build_status_payload(
                    started_snapshot,
                    event="run_started",
                    outcome="running",
                    message="Subagent run started.",
                    queue_depth=self._count_queued_for_controller(
                        user_id=user_id,
                        controller_session_key=started_snapshot.controller_session_key,
                    ),
                )
            )

        exec_request = SubagentExecutionRequest(
            run_id=record.run_id,
            subagent_id=record.subagent_id,
            user_id=record.user_id,
            child_session_key=record.child_session_key,
            requester_session_key=record.requester_session_key,
            controller_session_key=record.controller_session_key,
            parent_run_id=record.parent_run_id,
            task=record.task,
            depth=record.depth,
            timeout_seconds=record.timeout_seconds,
            context_pack=target_context_pack_from_dict(record.metadata.get("context_pack", {})),
            metadata=dict(record.metadata),
        )

        try:
            if record.timeout_seconds > 0:
                result = await asyncio.wait_for(
                    executor(exec_request),
                    timeout=record.timeout_seconds,
                )
            else:
                result = await executor(exec_request)
            status = result.status
            output = result.output
            error = result.error
            metadata_updates = dict(result.metadata)
        except asyncio.TimeoutError:
            status = SubagentRunStatus.TIMED_OUT
            output = ""
            error = f"timed out after {record.timeout_seconds}s"
            metadata_updates = {}
        except asyncio.CancelledError:
            status = SubagentRunStatus.KILLED
            output = ""
            error = str(record.metadata.get("kill_reason", "killed"))
            metadata_updates = {}
        except Exception as exc:  # noqa: BLE001
            status = SubagentRunStatus.FAILED
            output = ""
            error = str(exc)
            metadata_updates = {}
        finally:
            lock = self._locks[user_id]
            terminal_record: Optional[SubagentRunRecord] = None
            batch_receipt: Optional[dict[str, Any]] = None
            activated_record: Optional[SubagentRunRecord] = None
            async with lock:
                current = self._runs.get(user_id, {}).get(run_id)
                if current is not None:
                    if current.status == SubagentRunStatus.KILLED:
                        status = SubagentRunStatus.KILLED
                        error = current.error or error
                    current.status = status
                    current.output = output
                    current.error = error
                    current.ended_at = utc_now()
                    if status in {SubagentRunStatus.TIMED_OUT, SubagentRunStatus.KILLED}:
                        current.metadata["partial"] = True
                    current.metadata.update(metadata_updates)
                    terminal_record = SubagentRunRecord.from_dict(current.to_dict())
                self._tasks.get(user_id, {}).pop(run_id, None)
                self._executors.get(user_id, {}).pop(run_id, None)
                controller_session_key = current.controller_session_key if current else ""
                if controller_session_key:
                    activated_record = await self._activate_next_queued_for_controller(
                        user_id=user_id,
                        controller_session_key=controller_session_key,
                    )
                    batch_id = str((current.metadata or {}).get("batch_id", "")).strip() if current else ""
                    if batch_id:
                        batch_receipt = self._try_build_batch_receipt_locked(
                            user_id=user_id,
                            controller_session_key=controller_session_key,
                            batch_id=batch_id,
                        )
                await self._persist_user(user_id)
            if terminal_record is not None:
                await self._emit_run_terminal(terminal_record)
                await self._emit_status(
                    self._build_status_payload(
                        terminal_record,
                        event="run_terminal",
                        outcome=terminal_record.status.value,
                        message="Subagent run reached terminal state.",
                        queue_depth=self._count_queued_for_controller(
                            user_id=user_id,
                            controller_session_key=terminal_record.controller_session_key,
                        ),
                    )
                )
            if activated_record is not None:
                activated_snapshot = SubagentRunRecord.from_dict(activated_record.to_dict())
                await self._emit_status(
                    self._build_status_payload(
                        activated_snapshot,
                        event="run_activated",
                        outcome="accepted_from_queue",
                        message="Queued subagent request is now running.",
                        queue_depth=self._count_queued_for_controller(
                            user_id=user_id,
                            controller_session_key=activated_snapshot.controller_session_key,
                        ),
                    )
                )
            if batch_receipt is not None:
                await self._emit_batch_terminal(batch_receipt)

    async def _restore_all_users(self) -> None:
        users_root = self.workspace_path / "users"
        if not users_root.exists():
            return
        for item in users_root.iterdir():
            if not item.is_dir():
                continue
            user_id = item.name
            await self._restore_user(user_id)

    async def _restore_user(self, user_id: str) -> None:
        path = self._snapshot_path(user_id)
        if not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        records = payload.get("runs", [])
        restored: dict[str, SubagentRunRecord] = {}
        mutated = False
        now = utc_now()
        for raw in records:
            try:
                record = SubagentRunRecord.from_dict(raw)
            except Exception:
                continue
            if record.status in {SubagentRunStatus.PENDING, SubagentRunStatus.RUNNING}:
                record.status = SubagentRunStatus.ORPHANED
                record.error = "orphaned_after_restart"
                record.ended_at = now
                mutated = True
            restored[record.run_id] = record
        self._runs[user_id] = restored
        if mutated:
            await self._persist_user(user_id)

    async def _persist_all(self) -> None:
        for user_id in list(self._runs.keys()):
            await self._persist_user(user_id)

    async def _persist_user(self, user_id: str) -> None:
        records = list(self._runs.get(user_id, {}).values())
        records.sort(key=lambda item: item.created_at)
        payload = {"runs": [item.to_dict() for item in records], "updated_at": utc_now().isoformat()}
        snapshot_path = self._snapshot_path(user_id)
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = snapshot_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(snapshot_path)

        ledger_path = self._ledger_path(user_id)
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    async def _sweeper_loop(self) -> None:
        while True:
            await asyncio.sleep(self.sweep_interval_seconds)
            await self._sweep_once()

    async def _sweep_once(self) -> None:
        cutoff = utc_now() - timedelta(seconds=self.retention_seconds)
        for user_id, records in list(self._runs.items()):
            lock = self._locks[user_id]
            async with lock:
                removable = [
                    run_id
                    for run_id, record in records.items()
                    if record.status.is_terminal
                    and record.ended_at is not None
                    and record.ended_at < cutoff
                ]
                if not removable:
                    continue
                for run_id in removable:
                    record = records.get(run_id)
                    records.pop(run_id, None)
                    self._tasks.get(user_id, {}).pop(run_id, None)
                    self._executors.get(user_id, {}).pop(run_id, None)
                    if record is not None:
                        queue = self._controller_queues.get(user_id, {}).get(
                            record.controller_session_key,
                            [],
                        )
                        if run_id in queue:
                            queue[:] = [item for item in queue if item != run_id]
                await self._persist_user(user_id)

    def _snapshot_path(self, user_id: str) -> Path:
        return (
            self.workspace_path
            / "users"
            / user_id
            / "sessions"
            / "subagent_runs.json"
        )

    def _ledger_path(self, user_id: str) -> Path:
        return (
            self.workspace_path
            / "users"
            / user_id
            / "sessions"
            / "subagent_runs.log.jsonl"
        )

    def _validate_spawn_request(self, request: SpawnSubagentRequest) -> None:
        if not request.user_id.strip():
            raise ValueError("user_id is required")
        if not request.requester_session_key.strip():
            raise ValueError("requester_session_key is required")
        if not request.controller_session_key.strip():
            raise ValueError("controller_session_key is required")
        if not request.task.strip():
            raise ValueError("task is required")
        if request.depth <= 0:
            raise ValueError("depth must be >= 1")
        if request.depth > self.max_spawn_depth:
            raise ValueError("max_spawn_depth exceeded")

    def _count_active_for_user(self, user_id: str) -> int:
        return sum(
            1
            for item in self._runs.get(user_id, {}).values()
            if item.status in {SubagentRunStatus.PENDING, SubagentRunStatus.RUNNING}
            and not self._is_queued(item)
        )

    def _count_active_for_controller(self, user_id: str, controller_session_key: str) -> int:
        return sum(
            1
            for item in self._runs.get(user_id, {}).values()
            if item.controller_session_key == controller_session_key
            and item.status in {SubagentRunStatus.PENDING, SubagentRunStatus.RUNNING}
            and not self._is_queued(item)
        )

    def _collect_descendants(self, user_id: str, run_id: str) -> list[str]:
        descendants: list[str] = []
        queue = [run_id]
        while queue:
            parent_id = queue.pop(0)
            for item in self._runs.get(user_id, {}).values():
                if item.parent_run_id == parent_id and item.run_id not in descendants:
                    descendants.append(item.run_id)
                    queue.append(item.run_id)
        return descendants

    def _build_child_session_key(
        self,
        *,
        requester_session_key: str,
        subagent_id: str,
        user_id: str,
    ) -> str:
        parsed = SessionKey.from_string(requester_session_key)
        key = SessionKey(
            agent_id=parsed.agent_id or "main",
            user_id=user_id or parsed.user_id or "default",
            channel="subagent",
            account_id="runtime",
            chat_type=ChatType.THREAD,
            peer_id=subagent_id,
            thread_id=subagent_id,
        )
        return key.to_string(scope=SessionScope.PER_ACCOUNT_CHANNEL_PEER)

    @staticmethod
    def _compose_steer_task(task: str, message: str) -> str:
        return (
            f"{task}\n\n"
            "[Steer Update]\n"
            f"{message}\n"
            "Please continue the same task with this updated direction."
        )


def target_context_pack_from_dict(data: dict[str, Any]) -> SubagentContextPack:
    """Convert persisted context payload to context pack model."""
    return SubagentContextPack.from_dict(data)
