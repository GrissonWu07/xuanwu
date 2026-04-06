# -*- coding: utf-8 -*-
"""
FastAPI application entry point for XuanWu.

This module creates and configures the FastAPI application, including:
- Static file serving for the frontend
- API routes for session management and agent execution
- CORS middleware for development
- Health check endpoint

Usage:
    uvicorn app.xuanwu.main:app --host 0.0.0.0 --port 9000
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote


from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent.parent / ".env", override=False)

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.xuanwu.api.routes import create_router, APIContext, install_request_validation_logging, set_api_context
from app.xuanwu.api.webhook_dispatch import WebhookDispatchManager
from app.xuanwu.api.channel_hooks import (
    router as channel_hooks_router,
    set_channel_manager as set_channel_hooks_manager,
)
from app.xuanwu.api.channels import router as channels_router, set_channel_manager
from app.xuanwu.api.agent_info import router as agent_info_router
from app.xuanwu.api.api_routes import router as db_api_router
from app.xuanwu.session.manager import SessionManager
from app.xuanwu.session.queue import SessionQueue
from app.xuanwu.session.router import SessionManagerRouter
from app.xuanwu.skills.registry import SkillRegistry
from app.xuanwu.tools.registration import register_builtin_tools
from app.xuanwu.tools.catalog import ToolProfile
from app.xuanwu.agent.runner import AgentRunner
from app.xuanwu.agent.prompt_builder import PromptBuilder, PromptBuilderConfig
from app.xuanwu.core.config import get_config, get_config_path
from app.xuanwu.core.provider_registry import ServiceProviderRegistry
from app.xuanwu.core.provider_scanner import ProviderScanner
from app.xuanwu.core.workspace import WorkspaceInitializer
from app.xuanwu.agent.agent_definition import AgentLoader
from app.xuanwu.channels import ChannelRegistry
from app.xuanwu.channels.manager import ChannelManager
# Import channel handlers from providers
from app.xuanwu.channels.handlers.feishu import FeishuHandler
from app.xuanwu.channels.handlers.dingtalk import DingTalkHandler
from app.xuanwu.channels.handlers.wecom import WeComHandler
from app.xuanwu.auth import AuthRegistry
from app.xuanwu.auth.models import UserInfo
from app.xuanwu.auth.shadow_store import ShadowUserStore
from app.xuanwu.agent.agent_pool import AgentInstancePool
from app.xuanwu.agent.token_policy import DynamicTokenPolicy
from app.xuanwu.hooks.runtime import HookRuntime, HookRuntimeContext
from app.xuanwu.hooks.runtime_builtin import register_builtin_hook_handlers
from app.xuanwu.hooks.runtime_models import HookEventType
from app.xuanwu.hooks.runtime_script import HookScriptHandlerDefinition
from app.xuanwu.hooks.runtime_sinks import ContextSink, MemorySink
from app.xuanwu.hooks.runtime_store import HookStateStore
from app.xuanwu.heartbeat.agent_executor import AgentHeartbeatExecutor
from app.xuanwu.heartbeat.channel_executor import ChannelHeartbeatExecutor
from app.xuanwu.heartbeat.events import emit_heartbeat_event_to_hook_runtime
from app.xuanwu.heartbeat.models import (
    HeartbeatJobDefinition,
    HeartbeatJobType,
    HeartbeatTargetDescriptor,
    HeartbeatTargetType,
)
from app.xuanwu.heartbeat.runtime import HeartbeatRuntime, HeartbeatRuntimeContext
from app.xuanwu.heartbeat.store import HeartbeatStateStore
from app.xuanwu.session.context import ChatType, SessionKey, SessionScope, TranscriptEntry
from app.xuanwu.core.token_health_store import TokenHealthStore
from app.xuanwu.core.token_interceptor import TokenHealthInterceptor
from app.xuanwu.core.token_pool import TokenEntry, TokenPool
from app.xuanwu.db.database import DatabaseConfig, init_database, get_db_manager
from app.xuanwu.db.orm.user import UserService
from app.xuanwu.db.orm.model_config import ModelConfigService
from app.xuanwu.subagents.runtime import SubagentRuntimeManager
from app.xuanwu.subagents.streaming import build_subagent_status_stream_id
from app.xuanwu.thread_files.service import ThreadFileService
from app.xuanwu.api.attachment_links import (
    AttachmentLinkSigner,
    resolve_attachment_link_secret,
    resolve_attachment_link_ttl_seconds,
)
from app.xuanwu.bootstrap.app_factory_helpers import (
    StaticFileCacheMiddleware,
    mount_frontend,
    register_core_routers,
    setup_auth_middleware_from_config,
)
from app.xuanwu.bootstrap.startup_helpers import (
    build_token_entries_from_db,
    build_provider_instances_from_db,
    build_token_entries,
    check_and_prompt_for_providers,
    create_pydantic_model,
    derive_provider_namespace,
    ensure_default_local_admin,
    load_agent_config_from_db,
    merge_provider_instances,
    merge_token_entries,
    print_root_plugins,
    run_mysql_alembic_upgrade,
    scan_plugin_names,
)



_global_provider_registry: Optional[ServiceProviderRegistry] = None


# Global context components
_session_manager: Optional[SessionManager] = None
_session_manager_router: Optional[SessionManagerRouter] = None
_session_queue: Optional[SessionQueue] = None
_skill_registry: Optional[SkillRegistry] = None
_agent_runner: Optional[AgentRunner] = None
_channel_manager: Optional[ChannelManager] = None
_hook_state_store: Optional[HookStateStore] = None
_memory_sink: Optional[MemorySink] = None
_context_sink: Optional[ContextSink] = None
_hook_runtime: Optional[HookRuntime] = None
_heartbeat_runtime: Optional[HeartbeatRuntime] = None
_heartbeat_store: Optional[HeartbeatStateStore] = None
_heartbeat_task: Optional[asyncio.Task] = None
_subagent_runtime: Optional[SubagentRuntimeManager] = None


def _list_workspace_runtime_user_ids(workspace_path: str | Path) -> set[str]:
    users_dir = Path(workspace_path).resolve() / "users"
    if not users_dir.exists():
        return set()
    return {
        item.name
        for item in users_dir.iterdir()
        if item.is_dir() and item.name not in {"default", "anonymous"}
    }


async def _list_shadow_runtime_user_ids(workspace_path: str | Path) -> set[str]:
    store = ShadowUserStore(workspace_path=str(Path(workspace_path).resolve()))
    users = await store.list_all()
    return {
        user.user_id
        for user in users
        if user.user_id and user.user_id not in {"default", "anonymous"}
    }


async def _list_db_runtime_user_ids(db_initialized: bool) -> set[str]:
    if not db_initialized:
        return set()
    try:
        async with get_db_manager().get_session() as session:
            users, _ = await UserService.list_all(session, page=1, page_size=1000)
    except Exception as exc:
        print(f"[XuanWu] Warning: Failed to load runtime users from database: {exc}")
        return set()
    return {
        user.username
        for user in users
        if getattr(user, "username", "") and user.username not in {"default", "anonymous"}
    }


def _list_active_channel_runtime_user_ids(channel_manager: Optional[ChannelManager]) -> set[str]:
    if channel_manager is None:
        return set()
    return {
        str(item.get("user_id", "")).strip()
        for item in channel_manager.list_active_connection_descriptors()
        if str(item.get("user_id", "")).strip() not in {"", "default", "anonymous"}
    }


async def _collect_runtime_user_ids(
    workspace_path: str | Path,
    *,
    db_initialized: bool,
    channel_manager: Optional[ChannelManager] = None,
) -> list[str]:
    user_ids: set[str] = set()
    user_ids.update(_list_workspace_runtime_user_ids(workspace_path))
    user_ids.update(await _list_shadow_runtime_user_ids(workspace_path))
    user_ids.update(await _list_db_runtime_user_ids(db_initialized))
    user_ids.update(_list_active_channel_runtime_user_ids(channel_manager))
    return sorted(
        user_id
        for user_id in user_ids
        if user_id and user_id not in {"default", "anonymous"}
    )


def _resolve_builtin_skills_root() -> Path:
    """Return built-in skills directory under application package."""
    return (Path(__file__).resolve().parent / "skills").resolve()

@asynccontextmanager
async def lifespan(app: FastAPI):


    """Application lifespan handler for startup and shutdown."""
    global _session_manager, _session_manager_router, _session_queue, _skill_registry, _agent_runner, _global_provider_registry, _channel_manager, _hook_state_store, _memory_sink, _context_sink, _hook_runtime, _heartbeat_runtime, _heartbeat_store, _heartbeat_task, _subagent_runtime
    
    config = get_config()
    config_path = get_config_path()
    config_root = config_path.parent if config_path is not None else Path.cwd()
    providers_root = (config_root / config.providers_root).resolve()
    skills_root = (config_root / config.skills_root).resolve()
    channels_root = (config_root / config.channels_root).resolve()
    builtin_skills_root = _resolve_builtin_skills_root()

    provider_plugins = scan_plugin_names(providers_root)
    skill_plugins = scan_plugin_names(skills_root, md_skill_mode=True)
    channel_plugins = scan_plugin_names(channels_root)
    builtin_skill_plugins = scan_plugin_names(builtin_skills_root, md_skill_mode=True)
    print_root_plugins("providers_root plugins", providers_root, provider_plugins)
    print_root_plugins("skills_root plugins", skills_root, skill_plugins)
    print_root_plugins("channels_root plugins", channels_root, channel_plugins)
    print_root_plugins("built-in skills plugins", builtin_skills_root, builtin_skill_plugins)

    # Get workspace path from config
    workspace_path = config.workspace.path

    
    # Initialize workspace directory structure
    workspace_initializer = WorkspaceInitializer(workspace_path)
    was_initialized = workspace_initializer.is_initialized()
    workspace_initializer.initialize()
    if not was_initialized:
        print(f"[XuanWu] Initialized workspace at: {workspace_path}")

    check_and_prompt_for_providers(providers_root)

    # Initialize database if configured
    db_initialized = False
    if config.database:
        try:
            db_config = DatabaseConfig.from_config({
                "database": {
                    "type": config.database.type,
                    "sqlite": {"path": config.database.sqlite.path} if config.database.sqlite else {},
                    "mysql": {
                        "host": config.database.mysql.host,
                        "port": config.database.mysql.port,
                        "database": config.database.mysql.database,
                        "user": config.database.mysql.user,
                        "password": config.database.mysql.password,
                        "charset": config.database.mysql.charset,
                    } if config.database.mysql else {},
                    "pool_size": config.database.pool_size,
                    "max_overflow": config.database.max_overflow,
                    "echo": config.database.echo,
                }
            })
            await init_database(db_config)

            if db_config.db_type == "sqlite":
                # SQLite: rely on ORM models to auto-create schema
                await get_db_manager().create_tables()
                print("[XuanWu] SQLite initialized via ORM models")
            elif db_config.db_type == "mysql":
                # MySQL: enterprise mode, schema/data changes managed by Alembic
                await run_mysql_alembic_upgrade(db_config)
                print("[XuanWu] MySQL initialized via Alembic migrations")
            else:
                raise RuntimeError(f"Unsupported database type: {db_config.db_type}")

            db_initialized = True
        except Exception as e:
            print(f"[XuanWu] Failed to initialize database ({config.database.type}): {e}")
            raise RuntimeError(f"Database startup failed: {e}") from e

    
    if db_initialized:
        await ensure_default_local_admin(config)

    # Register built-in channel handlers (enterprise messaging platforms)
    ChannelRegistry.register("feishu", FeishuHandler)

    ChannelRegistry.register("dingtalk", DingTalkHandler)
    ChannelRegistry.register("wecom", WeComHandler)
    print(f"[XuanWu] Registered built-in channel handlers")
    
    # Initialize ChannelManager
    _channel_manager = ChannelManager(workspace_path)
    set_channel_manager(_channel_manager)
    set_channel_hooks_manager(_channel_manager)
    print(f"[XuanWu] Channel manager initialized")
    
    # Scan providers for channel and auth extensions
    providers_dir = providers_root
    scan_results = ProviderScanner.scan_providers(providers_dir)
    print(f"[XuanWu] Provider scan complete: {len(scan_results['channels'])} channels, {len(scan_results['auth'])} auth providers")
    
    # Load agent definitions - try database first, fallback to file-based
    agent_loader = AgentLoader(workspace_path)
    main_agent_config = None
    
    if db_initialized:
        try:
            async with get_db_manager().get_session() as session:
                main_agent_config = await load_agent_config_from_db(session, "main")
                if main_agent_config:
                    print(f"[XuanWu] Loaded agent from database: {main_agent_config.display_name}")
        except Exception as e:
            print(f"[XuanWu] Warning: Failed to load agent from database: {e}")
    
    # Fallback to file-based agent config
    if main_agent_config is None:
        main_agent_config = agent_loader.load_agent("main")
        print(f"[XuanWu] Loaded agent from files: {main_agent_config.display_name}")
    
    # Initialize SessionManager with new workspace-based path
    _session_manager = SessionManager(
        workspace_path=workspace_path,
        user_id="default",
        reset_mode=config.reset.mode,
        daily_reset_hour=config.reset.daily_hour,
        idle_reset_minutes=config.reset.idle_minutes,
    )
    _session_manager_router = SessionManagerRouter.from_manager(_session_manager)
    _session_queue = SessionQueue(max_concurrent=config.agent_defaults.max_concurrent)
    _api_context_holder: dict[str, Any] = {"context": None}

    def _build_subagent_next_step_suggestion(
        *,
        completed: int,
        failed: int,
        canceled: int,
        artifact_count: int,
    ) -> str:
        if failed > 0 and completed <= 0:
            return "Next step: use Retry with edit to fix failed tasks, then rerun the batch."
        if failed > 0:
            return "Next step: review completed artifacts first, then retry failed runs with edited prompts."
        if canceled > 0 and completed > 0:
            return "Next step: validate completed artifacts and restart canceled runs only if needed."
        if artifact_count > 0:
            return "Next step: open and validate generated artifacts, then continue follow-up in this chat."
        return "Next step: continue this conversation with one focused follow-up request."

    async def _collect_subagent_artifact_links(
        user_id: str,
        run_ids: list[str],
    ) -> list[dict[str, Any]]:
        if _subagent_runtime is None or _session_manager_router is None:
            return []
        scoped_manager = _session_manager_router.for_user(user_id)
        signer = AttachmentLinkSigner(
            secret_key=resolve_attachment_link_secret(),
            default_ttl_seconds=resolve_attachment_link_ttl_seconds(),
        )
        collected: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for run_id in run_ids:
            record = await _subagent_runtime.get_run(user_id, run_id)
            if record is None:
                continue
            child_key = str(record.child_session_key or "").strip()
            if not child_key:
                continue
            try:
                parsed = SessionKey.from_string(child_key)
            except Exception:
                continue
            thread_id = parsed.thread_id or "main"
            service = ThreadFileService(
                workspace_path=str(scoped_manager.workspace_path),
                user_id=user_id,
                thread_id=thread_id,
            )
            artifacts = await service.list_current_thread_artifacts()
            for artifact in artifacts:
                dedupe_key = (child_key, artifact.artifact_id)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                signed_url, expires_at = signer.build_signed_download_url(
                    session_key=child_key,
                    entry_id=artifact.artifact_id,
                )
                collected.append(
                    {
                        "run_id": run_id,
                        "subagent_id": record.subagent_id,
                        "entry_id": artifact.artifact_id,
                        "name": artifact.name,
                        "download_url": signed_url,
                        "expires_at": expires_at,
                        "child_session_key": child_key,
                    }
                )
                if len(collected) >= 8:
                    return collected
        return collected

    async def _push_subagent_status_event(payload: dict[str, Any]) -> None:
        api_ctx = _api_context_holder.get("context")
        if api_ctx is None:
            return
        user_id = str(payload.get("user_id", "")).strip()
        controller_session_key = str(payload.get("controller_session_key", "")).strip()
        if not user_id or not controller_session_key:
            return
        stream_id = build_subagent_status_stream_id(user_id, controller_session_key)
        api_ctx.sse_manager.create_stream(stream_id)
        api_ctx.sse_manager.push_subagent_status(stream_id, payload)

    async def _on_subagent_run_terminal(record) -> None:
        try:
            scoped_manager = _session_manager_router.for_user(record.user_id)
            status = str(record.status.value)
            summary = (record.output or "").strip()
            if summary and len(summary) > 280:
                summary = summary[:277].rstrip() + "..."
            if not summary:
                summary = str(record.error or "no summary")
            message = (
                f"[Subagent {record.subagent_id}] {status}\n"
                f"Run: {record.run_id}\n"
                f"{summary}"
            )
            await scoped_manager.append_transcript(
                record.controller_session_key,
                TranscriptEntry(role="assistant", content=message),
            )
            await _push_subagent_status_event(
                {
                    "event": "run_terminal_receipt",
                    "user_id": record.user_id,
                    "controller_session_key": record.controller_session_key,
                    "run_id": record.run_id,
                    "subagent_id": record.subagent_id,
                    "status": status,
                    "message": summary,
                }
            )
        except Exception:
            return

    async def _on_subagent_batch_terminal(payload: dict[str, Any]) -> None:
        try:
            user_id = str(payload.get("user_id", "")).strip()
            session_key = str(payload.get("controller_session_key", "")).strip()
            if not user_id or not session_key:
                return
            scoped_manager = _session_manager_router.for_user(user_id)
            completed = int(payload.get("completed", 0) or 0)
            failed = int(payload.get("failed", 0) or 0)
            canceled = int(payload.get("canceled", 0) or 0)
            total = int(payload.get("total", 0) or 0)
            run_ids = [str(item) for item in payload.get("run_ids", []) if str(item).strip()]
            artifact_links = await _collect_subagent_artifact_links(user_id, run_ids)
            suggestion = _build_subagent_next_step_suggestion(
                completed=completed,
                failed=failed,
                canceled=canceled,
                artifact_count=len(artifact_links),
            )
            artifact_lines: list[str] = []
            for item in artifact_links:
                encoded_child_key = quote(str(item["child_session_key"]), safe="")
                fallback_url = (
                    f"/api/sessions/{encoded_child_key}/attachments/"
                    f"{item['entry_id']}/content"
                )
                artifact_url = str(item.get("download_url") or "").strip() or fallback_url
                artifact_lines.append(
                    f"- [{item['name']}]({artifact_url}) · {item['subagent_id']}"
                )
            message = (
                f"[Subagent Batch {str(payload.get('batch_id', ''))[-8:]}] completed\n"
                f"total={total} completed={completed} failed={failed} canceled={canceled}"
            )
            if artifact_lines:
                message = message + "\n\nArtifacts:\n" + "\n".join(artifact_lines)
            message = message + f"\n\n{suggestion}"
            await scoped_manager.append_transcript(
                session_key,
                TranscriptEntry(role="assistant", content=message),
            )
            await _push_subagent_status_event(
                {
                    "event": "batch_terminal_receipt",
                    "user_id": user_id,
                    "controller_session_key": session_key,
                    "batch_id": str(payload.get("batch_id", "")),
                    "total": total,
                    "completed": completed,
                    "failed": failed,
                    "canceled": canceled,
                    "artifact_count": len(artifact_links),
                    "next_step": suggestion,
                }
            )
        except Exception:
            return

    async def _on_subagent_status(payload: dict[str, Any]) -> None:
        await _push_subagent_status_event(payload)

    _subagent_runtime = SubagentRuntimeManager(
        workspace_path=workspace_path,
        max_spawn_depth=config.subagent_runtime.max_spawn_depth,
        max_children_per_session=config.subagent_runtime.max_children_per_session,
        max_concurrent_subagents=config.subagent_runtime.max_concurrent_subagents,
        default_timeout_seconds=config.subagent_runtime.default_timeout_seconds,
        steer_rate_limit_ms=config.subagent_runtime.steer_rate_limit_ms,
        max_queued_batches_per_controller=config.subagent_runtime.max_queued_batches_per_controller,
        stalled_after_seconds=config.subagent_runtime.stalled_after_seconds,
        retention_seconds=config.subagent_runtime.retention_seconds,
        sweep_interval_seconds=config.subagent_runtime.sweep_interval_seconds,
        on_run_terminal=_on_subagent_run_terminal,
        on_batch_terminal=_on_subagent_batch_terminal,
        on_status=_on_subagent_status,
    )
    await _subagent_runtime.start()
    _hook_state_store = HookStateStore(workspace_path=workspace_path)
    _memory_sink = MemorySink(workspace_path=workspace_path)
    _context_sink = ContextSink(_hook_state_store)
    _hook_runtime = HookRuntime(
        HookRuntimeContext(
            workspace_path=workspace_path,
            hook_state_store=_hook_state_store,
            memory_sink=_memory_sink,
            context_sink=_context_sink,
            session_manager_router=_session_manager_router,
        )
    )
    register_builtin_hook_handlers(_hook_runtime)
    for handler_config in config.hooks_runtime.script_handlers:
        event_types = {HookEventType(event_name) for event_name in handler_config.events}
        _hook_runtime.register_script_handler(
            HookScriptHandlerDefinition(
                module_name=handler_config.module,
                event_types=event_types,
                command=list(handler_config.command),
                timeout_seconds=handler_config.timeout_seconds,
                enabled=handler_config.enabled,
                cwd=handler_config.cwd,
                priority=handler_config.priority,
            )
        )
    _skill_registry = SkillRegistry()
    
    _global_provider_registry = ServiceProviderRegistry()
    _global_provider_registry.load_from_directory(providers_root)

    config_provider_instances: dict[str, dict[str, dict[str, Any]]] = {
        provider_type: dict(instances)
        for provider_type, instances in (config.service_providers or {}).items()
        if isinstance(instances, dict)
    }
    merged_provider_instances = config_provider_instances

    if db_initialized:
        try:
            async with get_db_manager().get_session() as session:
                db_provider_instances = await build_provider_instances_from_db(session)
                if db_provider_instances:
                    merged_provider_instances = merge_provider_instances(
                        db_provider_instances,
                        config_provider_instances,
                    )
                    print(
                        "[XuanWu] Loaded provider configs from database and merged with JSON"
                    )
        except Exception as e:
            print(f"[XuanWu] Warning: Failed to load provider configs from database: {e}")

    if merged_provider_instances:
        _global_provider_registry.load_instances_from_config(merged_provider_instances)

    available_providers = {}
    provider_instances = _global_provider_registry.get_all_instance_configs()

    for provider_type in _global_provider_registry.list_providers():
        instances = _global_provider_registry.list_instances(provider_type)
        if instances:
            available_providers[provider_type] = instances
    
    # Register built-in tools (exec, read, write, web_search, etc.)
    registered_tools = register_builtin_tools(_skill_registry, profile=ToolProfile.FULL)
    print(f"[XuanWu] Registered {len(registered_tools)} built-in tools")
    
    # Load skills from multiple sources (priority: workspace > global > built-in)

    # 1. External provider skills (from providers_root config)
    if providers_root.exists():
        for provider_path in providers_root.iterdir():
            if provider_path.is_dir() and not provider_path.name.startswith(("_", ".")):
                provider_skills = provider_path / "skills"
                if provider_skills.exists():
                    provider_namespace = derive_provider_namespace(provider_path.name)
                    _skill_registry.load_from_directory(
                        str(provider_skills),
                        location="provider",
                        provider=provider_namespace
                    )

    # 2. Built-in skills (from app package)
    if builtin_skills_root.exists():
        _skill_registry.load_from_directory(str(builtin_skills_root), location="built-in")

    # 3. Standalone skills (from skills_root config)
    if skills_root.exists():
        _skill_registry.load_from_directory(str(skills_root), location="skills-root")

    from pydantic_ai import Agent
    from app.xuanwu.core.deps import SkillDeps

    # Load token configurations from both JSON and database.
    # Priority: DB tokens override same token_id from JSON, while JSON tokens are still loaded.
    config_token_entries, config_primary_token_id = build_token_entries(config)
    token_entries = list(config_token_entries)
    primary_token_id = config_primary_token_id

    if token_entries:
        print(f"[XuanWu] Loaded {len(token_entries)} tokens from JSON config")

    if db_initialized:
        try:
            async with get_db_manager().get_session() as session:
                db_token_entries, db_primary_token_id = await build_token_entries_from_db(session)
                if db_token_entries:
                    print(f"[XuanWu] Loaded {len(db_token_entries)} tokens from database")
                    token_entries = merge_token_entries(db_token_entries, token_entries)
                    primary_token_id = db_primary_token_id or primary_token_id
                    print(f"[XuanWu] Combined token pool: {len(token_entries)} (database + JSON)")
        except Exception as e:
            print(f"[XuanWu] Warning: Failed to load tokens from database: {e}")

    if not token_entries:
        raise RuntimeError("No token configurations found. Please configure tokens in database or xuanwu.json")

    if primary_token_id and not any(t.token_id == primary_token_id for t in token_entries):
        print(f"[XuanWu] Warning: primary token '{primary_token_id}' not found, using first token")
        primary_token_id = token_entries[0].token_id
    elif not primary_token_id:
        primary_token_id = token_entries[0].token_id


    token_pool = TokenPool()
    for token in token_entries:
        token_pool.register_token(token)

    # Load model configs from DB and register as token entries
    # Model configs can override token entries with the same name
    if db_initialized:
        try:
            async with get_db_manager().get_session() as session:
                db_model_configs = await ModelConfigService.list_active(session)
                for mc in db_model_configs:
                    entry = TokenEntry(
                        token_id=mc.name,
                        provider=mc.provider,
                        model=mc.model_id,
                        base_url=mc.base_url or "",
                        api_key=ModelConfigService.get_decrypted_api_key(mc) or "",
                        api_type=mc.api_type or "openai",
                        priority=mc.priority or 0,
                        weight=mc.weight or 100,
                        context_window=mc.context_window,
                    )
                    token_pool.register_token(entry)
                if db_model_configs:
                    print(f"[XuanWu] Loaded {len(db_model_configs)} model configs from database")
        except Exception as e:
            print(f"[XuanWu] Warning: Failed to load model configs from database: {e}")

    health_store = TokenHealthStore(workspace_path)
    restored_health = health_store.load()
    for token_id, health in restored_health.items():
        token_pool.restore_health(token_id, health)

    token_policy = DynamicTokenPolicy(
        token_pool,
        strategy=config.model.selection_strategy,
        primary_token_id=primary_token_id,
    )
    agent_pool = AgentInstancePool(max_concurrent_per_instance=4)
    token_interceptor = TokenHealthInterceptor(token_pool, health_store)

    agent_configs: dict[str, Any] = {"main": main_agent_config}

    def _build_agent_for(agent_id: str, token: TokenEntry) -> Any:
        agent_cfg = agent_configs.get(agent_id)
        if agent_cfg is None:
            agent_cfg = agent_loader.load_agent(agent_id)
            agent_configs[agent_id] = agent_cfg
        model_instance = create_pydantic_model(token)
        built_agent = Agent(
            model_instance,
            deps_type=SkillDeps,
            system_prompt=agent_cfg.system_prompt or "You are XuanWu, an enterprise AI assistant.",
        )
        _skill_registry.register_to_agent(built_agent)
        return built_agent

    seed_token = token_pool.tokens.get(primary_token_id) or token_entries[0]
    agent = _build_agent_for("main", seed_token)

    # Create AgentRunner
    prompt_builder = PromptBuilder(PromptBuilderConfig(workspace_path=workspace_path))
    _agent_runner = AgentRunner(
        agent=agent,
        session_manager=_session_manager,
        session_manager_router=_session_manager_router,
        prompt_builder=prompt_builder,
        session_queue=_session_queue,
        hook_runtime=_hook_runtime,
        agent_id="main",
        token_policy=token_policy,
        agent_pool=agent_pool,
        token_interceptor=token_interceptor,
        agent_factory=_build_agent_for,
        tool_gate_model_classifier_enabled=config.tool_gate.enable_model_classifier,
    )

    
    # Set agent runner on channel manager for message processing
    _channel_manager.set_agent_runner(_agent_runner)
    _channel_manager.set_session_manager_router(_session_manager_router)
    _channel_manager.set_subagent_runtime(_subagent_runtime)

    async def _run_agent_heartbeat(job: HeartbeatJobDefinition) -> dict[str, Any]:
        session_manager = _session_manager_router.for_user(job.owner_user_id)
        heartbeat_target = job.target
        if heartbeat_target and heartbeat_target.session_key:
            heartbeat_session_key = heartbeat_target.session_key
        elif job.isolated_session:
            heartbeat_session_key = SessionKey(
                agent_id="main",
                user_id=job.owner_user_id,
                channel="heartbeat",
                account_id="runtime",
                chat_type=ChatType.THREAD,
                peer_id="heartbeat",
                thread_id=job.job_id,
            ).to_string(scope=SessionScope.PER_ACCOUNT_CHANNEL_PEER)
        else:
            heartbeat_session_key = SessionKey(
                agent_id="main",
                user_id=job.owner_user_id,
            ).to_string(scope=SessionScope.MAIN)

        heartbeat_md = ""
        heartbeat_filename = config.heartbeat.agent_turn.heartbeat_file
        heartbeat_candidates = [
            Path(workspace_path) / "agents" / "main" / heartbeat_filename,
            Path(workspace_path) / heartbeat_filename,
        ]
        for heartbeat_md_path in heartbeat_candidates:
            if heartbeat_md_path.exists():
                heartbeat_md = heartbeat_md_path.read_text(encoding="utf-8").strip()
                break
        heartbeat_run_id = f"heartbeat-{job.job_id}"
        heartbeat_message = heartbeat_md or (
            "Run a lightweight heartbeat check. If no action is required, respond with HEARTBEAT_OK."
        )
        deps = SkillDeps(
            user_info=UserInfo(user_id=job.owner_user_id, display_name=job.owner_user_id),
            session_key=heartbeat_session_key,
            session_manager=session_manager,
            extra={"run_id": heartbeat_run_id, "heartbeat_job_id": job.job_id},
        )
        assistant_chunks: list[str] = []
        error_text = ""
        async for event in _agent_runner.run(
            session_key=heartbeat_session_key,
            user_message=heartbeat_message,
            deps=deps,
            max_tool_calls=10,
            timeout_seconds=120,
        ):
            if event.type == "assistant" and event.content:
                assistant_chunks.append(event.content)
            elif event.type == "error":
                error_text = event.error or "heartbeat agent run failed"
                break
        if error_text:
            raise RuntimeError(error_text)
        assistant_message = "".join(assistant_chunks).strip() or "HEARTBEAT_OK"
        return {
            "assistant_message": assistant_message,
            "system_prompt": "heartbeat",
            "message_history": [],
            "tool_calls": [],
            "session_title": "Heartbeat",
            "session_key": heartbeat_session_key,
            "run_id": heartbeat_run_id,
        }

    async def _run_channel_heartbeat(job: HeartbeatJobDefinition) -> dict[str, Any]:
        channel_type = str(job.metadata.get("channel_type", ""))
        connection_id = str(job.metadata.get("connection_id", ""))
        result = await _channel_manager.probe_connection(job.owner_user_id, channel_type, connection_id)
        if not result.get("healthy", False):
            result["reconnect_attempted"] = True
            result["reconnected"] = await _channel_manager.reconnect_connection(
                job.owner_user_id,
                channel_type,
                connection_id,
            )
            if result["reconnected"]:
                refreshed = await _channel_manager.probe_connection(
                    job.owner_user_id,
                    channel_type,
                    connection_id,
                )
                refreshed["reconnected"] = True
                refreshed["summary"] = "reconnected"
                return refreshed
        result.setdefault("summary", "healthy" if result.get("healthy") else "connection_failed")
        return result

    async def _bridge_heartbeat_event(event) -> None:
        if _hook_runtime is None:
            return
        await emit_heartbeat_event_to_hook_runtime(_hook_runtime, event)

    async def _build_agent_heartbeat_jobs() -> list[HeartbeatJobDefinition]:
        if not config.heartbeat.agent_turn.enabled:
            return []
        user_ids = await _collect_runtime_user_ids(
            workspace_path,
            db_initialized=db_initialized,
            channel_manager=_channel_manager,
        )
        jobs: list[HeartbeatJobDefinition] = []
        for user_id in user_ids:
            jobs.append(
                HeartbeatJobDefinition(
                    job_id=f"hb-agent-main-{user_id}",
                    job_type=HeartbeatJobType.AGENT_TURN,
                    owner_user_id=user_id,
                    every_seconds=config.heartbeat.agent_turn.every_seconds,
                    target=HeartbeatTargetDescriptor.from_dict(
                        config.heartbeat.agent_turn.target.model_dump()
                    ),
                    active_hours_timezone=config.heartbeat.defaults.active_hours.timezone,
                    active_hours_start=config.heartbeat.defaults.active_hours.start,
                    active_hours_end=config.heartbeat.defaults.active_hours.end,
                    isolated_session=config.heartbeat.agent_turn.isolated_session,
                    light_context=config.heartbeat.agent_turn.light_context,
                )
            )
        return jobs

    def _build_channel_heartbeat_jobs() -> list[HeartbeatJobDefinition]:
        if not config.heartbeat.channel_connection.enabled:
            return []
        jobs: list[HeartbeatJobDefinition] = []
        for item in _channel_manager.list_active_connection_descriptors():
            jobs.append(
                HeartbeatJobDefinition(
                    job_id=f"hb-channel-{item['user_id']}-{item['channel_type']}-{item['connection_id']}",
                    job_type=HeartbeatJobType.CHANNEL_CONNECTION,
                    owner_user_id=item["user_id"],
                    every_seconds=config.heartbeat.channel_connection.check_interval_seconds,
                    target=HeartbeatTargetDescriptor(
                        type=HeartbeatTargetType.CHANNEL_CONNECTION,
                        user_id=item["user_id"],
                        channel=item["channel_type"],
                        account_id=item["connection_id"],
                    ),
                    active_hours_timezone=config.heartbeat.defaults.active_hours.timezone,
                    active_hours_start=config.heartbeat.defaults.active_hours.start,
                    active_hours_end=config.heartbeat.defaults.active_hours.end,
                    metadata={
                        "channel_type": item["channel_type"],
                        "connection_id": item["connection_id"],
                    },
                )
            )
        return jobs

    if config.heartbeat.enabled:
        _heartbeat_store = HeartbeatStateStore(workspace_path=workspace_path)
        _heartbeat_runtime = HeartbeatRuntime(
            HeartbeatRuntimeContext(
                store=_heartbeat_store,
                agent_executor=AgentHeartbeatExecutor(_run_agent_heartbeat),
                channel_executor=ChannelHeartbeatExecutor(
                    _run_channel_heartbeat,
                    failure_threshold=config.heartbeat.channel_connection.failure_threshold,
                    degraded_threshold=config.heartbeat.channel_connection.degraded_threshold,
                    reconnect_backoff_seconds=config.heartbeat.channel_connection.reconnect_backoff_seconds,
                ),
                emit_event=_bridge_heartbeat_event,
                max_concurrent_jobs=config.heartbeat.runtime.max_concurrent_jobs,
                emit_runtime_events=config.heartbeat.runtime.emit_runtime_events,
                persist_local_event_log=config.heartbeat.runtime.persist_local_event_log,
            )
        )

        async def _heartbeat_loop() -> None:
            while True:
                for job in await _build_agent_heartbeat_jobs():
                    _heartbeat_runtime.register_job(job)
                for job in _build_channel_heartbeat_jobs():
                    _heartbeat_runtime.register_job(job)
                await _heartbeat_runtime.run_once()
                await asyncio.sleep(config.heartbeat.runtime.tick_seconds)

        _heartbeat_task = asyncio.create_task(_heartbeat_loop())
    
    # Auto-start enabled channel connections for default user
    async def start_enabled_connections(db_ready: bool):
        """Start all enabled channel connections on startup."""
        if not db_ready:
            print("[XuanWu] Skipping channel auto-start: database not initialized")
            return
        try:
            user_ids = await _collect_runtime_user_ids(
                workspace_path,
                db_initialized=db_ready,
                channel_manager=_channel_manager,
            )
            for user_id in user_ids:
                connections = await _channel_manager.get_user_connections_async(user_id)
                for conn in connections:
                    if conn.get("enabled"):
                        channel_type = conn.get("channel_type")
                        connection_id = conn.get("id")
                        print(
                            f"[XuanWu] Starting channel connection: "
                            f"{user_id}/{channel_type}/{connection_id}"
                        )
                        success = await _channel_manager.initialize_connection(
                            user_id, channel_type, connection_id
                        )
                        if success:
                            print(
                                f"[XuanWu] Channel connection started: "
                                f"{user_id}/{channel_type}/{connection_id}"
                            )
                        else:
                            print(
                                f"[XuanWu] Failed to start channel: "
                                f"{user_id}/{channel_type}/{connection_id}"
                            )
        except Exception as e:
            print(f"[XuanWu] Error starting channel connections: {e}")
    
    # Schedule connection startup (will run after event loop starts)
    asyncio.create_task(start_enabled_connections(db_initialized))


    webhook_manager = WebhookDispatchManager(config.webhook, _skill_registry)
    webhook_manager.validate_startup()
    
    print(f"[XuanWu] Agent created with model: {seed_token.provider}/{seed_token.model}")


    # Expose config on app.state so routes (e.g. SSO) can access it
    # Preserve existing auth config if already set by create_app()
    existing_auth = getattr(app.state.config, 'auth', None) if hasattr(app.state, 'config') else None
    app.state.config = config
    
    # Coerce auth dict → AuthConfig object so SSO routes can call .provider / .oidc
    from app.xuanwu.auth.config import AuthConfig
    auth_source = config.auth if config.auth is not None else existing_auth
    
    if auth_source is not None:
        if isinstance(auth_source, dict):
            auth_obj = AuthConfig(**auth_source)
        elif isinstance(auth_source, AuthConfig):
            auth_obj = auth_source
        else:
            auth_obj = None
        
        if auth_obj and auth_obj.enabled:
            app.state.config.auth = auth_obj
            print(f"[XuanWu] Auth configured with provider='{auth_obj.provider}'")
        else:
            app.state.config.auth = None
            print("[XuanWu] Auth disabled or not configured")
    else:
        app.state.config.auth = None
        print("[XuanWu] Auth config not present, running in anonymous mode")

    api_context = APIContext(
        session_manager=_session_manager,
        session_manager_router=_session_manager_router,
        hook_state_store=_hook_state_store,
        memory_sink=_memory_sink,
        context_sink=_context_sink,
        hook_runtime=_hook_runtime,
        heartbeat_runtime=_heartbeat_runtime,
        session_queue=_session_queue,
        skill_registry=_skill_registry,
        agent_runner=_agent_runner,
        agent_runners={"main": _agent_runner},
        service_provider_registry=_global_provider_registry,
        available_providers=available_providers,
        provider_instances=provider_instances,
        webhook_manager=webhook_manager,
        subagent_runtime=_subagent_runtime,
    )

    set_api_context(api_context)
    _api_context_holder["context"] = api_context
    
    print("[XuanWu] Application started successfully")
    print(f"[XuanWu] Session storage: {_session_manager.sessions_dir}")
    print(f"[XuanWu] Skills loaded: {len(_skill_registry.list_skills())} executable, {len(_skill_registry.list_md_skills())} markdown")
    
    yield
    
    # Cleanup on shutdown
    print("[XuanWu] Application shutting down")
    if _heartbeat_task is not None:
        _heartbeat_task.cancel()
        try:
            await _heartbeat_task
        except asyncio.CancelledError:
            pass
    if _subagent_runtime is not None:
        await _subagent_runtime.stop()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="XuanWu Enterprise Assistant",
        description="AI-powered enterprise assistant framework",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:9000",
            "http://127.0.0.1:9000",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_request_validation_logging(app)
    app.add_middleware(StaticFileCacheMiddleware)

    frontend_dir = Path(__file__).parent.parent / "frontend"
    mount_frontend(app, frontend_dir)

    register_core_routers(
        app,
        api_router=create_router(),
        channel_hooks_router=channel_hooks_router,
        channels_router=channels_router,
        agent_info_router=agent_info_router,
        db_api_router=db_api_router,
    )

    # SPA catch-all: serve index.html for all non-API, non-static routes
    # This MUST be AFTER all include_router calls to avoid intercepting API requests
    if frontend_dir.exists():
        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_catch_all(full_path: str):
            """SPA catch-all: serve index.html for all non-API, non-static routes"""
            # Skip API routes - should not reach here, but safety check
            if full_path.startswith("api/"):
                return JSONResponse(status_code=404, content={"detail": "API endpoint not found"})
            index_file = frontend_dir / "index.html"
            if index_file.exists():
                return FileResponse(str(index_file))
            return {"error": "Frontend index.html not found"}

    setup_auth_middleware_from_config(app)
    return app


# Create the application instance
app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.xuanwu.main:app",
        host="0.0.0.0",
        port=9000,
        reload=True,
    )
