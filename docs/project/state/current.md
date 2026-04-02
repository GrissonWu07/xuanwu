# Current State

## Objective
- Implement a unified heartbeat framework that aligns with OpenClaw heartbeat semantics while also adding per-channel long-connection heartbeat monitoring and recovery.

## Completed
- Reviewed canonical architecture/module/development docs.
- Inspected current SSE/WebSocket heartbeat behavior and channel connection lifecycle.
- Verified AtlasClaw currently has API transport heartbeat pieces but no unified heartbeat runtime for agent turns plus channel long connections.
- Verified OpenClaw heartbeat semantics and configuration surface from official docs.
- Finalized the recommended architecture as a unified `HeartbeatRuntime` with typed jobs.
- Wrote the design spec for the unified heartbeat runtime.
- Completed the document alignment review across `state`, `task`, and `spec`, with task/spec scope and decisions now synchronized.
- Implemented `app/atlasclaw/heartbeat/` runtime modules, executors, target resolution, state store, and event bridge.
- Wired heartbeat configuration into `config_schema.py` and startup initialization in `main.py`.
- Added channel probe and reconnect support to `ChannelManager`.
- Added heartbeat-specific unit, integration, and E2E coverage.
- Updated canonical docs to describe heartbeat runtime architecture and development standards.
- Replaced the previous default-bucket startup behavior with per-user agent heartbeat job registration based on existing isolated user sources.
- Replaced default-only channel auto-start with per-user enabled connection startup using the same isolated user discovery path.
- Completed implementation-to-spec/task/state alignment review.
- Re-ran full backend unit tests and full live-server E2E successfully.
- Completed a final standalone code review for heartbeat changes.

## In Progress
- None.

## Risks / Decisions
- Heartbeat must remain separate from Hook scheduling, but emit standard events for Hook Runtime consumers.
- AtlasClaw should align to OpenClaw semantics while extending target routing to support user chat, channels, sessions, threads, and group chats.
- Channel heartbeat is primarily self-healing and should alert only after repeated failures.

## Next Step
- Wait for user review of the completed heartbeat implementation before making any local commit or push.
