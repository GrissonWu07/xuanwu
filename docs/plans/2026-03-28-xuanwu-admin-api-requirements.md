# XuanWu Admin API Requirements

**Date:** 2026-03-28

## Goal

为 `control-plane` 提供可透传的 `XuanWu` 管理 API。  
本期 `XuanWu` 只真实实现三类对象的后端能力：

- `Agent`
- `Model Provider`
- `Model Config`

这些数据的唯一真源和持久化都在 `XuanWu`。`control-plane` 只负责前端、鉴权、审计和 API 透传，不保存副本。

## Scope

### In Scope

- `Agent` 管理 API
- `Model Provider` 管理 API
- `Model Config` 管理 API
- 服务间鉴权
- 文件落盘持久化
- 统一错误码和响应格式
- 列表分页、检索、状态过滤
- 引用约束校验

### Out of Scope

以下模块本期不做真实后端实现：

- `Template`
- `Feature`
- `MCP`
- `Knowledge / RAG`
- `Prompt / Workflow`

### Explicitly Forbidden

- 不提供 `Skill` 安装 API
- 不提供 `Skill` 上传 API
- 不提供 `Skill` marketplace API
- 不支持用户动态安装第三方 skill

## Architecture

- `control-plane` 是唯一对外后台入口
- `XuanWu` 是智能体配置域的内部服务
- `control-plane -> XuanWu` 通过 HTTP 调用
- `XuanWu` 对本期三类对象提供真实 CRUD
- 运行时 API 与管理 API 必须分层，不能继续混用旧的 `/api/*` 语义

建议新增独立管理域前缀：

- `/xuanwu/v1/admin/agents`
- `/xuanwu/v1/admin/model-providers`
- `/xuanwu/v1/admin/models`

## Service-to-Service Contract

`control-plane -> XuanWu` 每个管理请求必须带：

- `X-Xiaozhi-Control-Plane-Secret`
- `X-Request-Id`

要求：

- `X-Xiaozhi-Control-Plane-Secret` 错误或缺失时返回 `401`
- `X-Request-Id` 原样记录到日志，便于问题追踪

## Response Format

### Success

```json
{
  "ok": true,
  "data": {}
}
```

### Error

```json
{
  "ok": false,
  "error": {
    "code": "resource_conflict",
    "message": "Model is referenced by one or more agents.",
    "details": {
      "resource_id": "model-gpt4o-primary"
    }
  }
}
```

## Error Codes

- `400` 请求格式错误
- `401` 鉴权失败
- `404` 资源不存在
- `409` 唯一性或引用冲突
- `422` 业务校验失败
- `500` 内部错误

建议错误代码枚举：

- `invalid_request`
- `unauthorized_control_plane`
- `resource_not_found`
- `resource_conflict`
- `validation_failed`
- `internal_error`

## Data Persistence

本期允许使用文件存储，不要求上数据库。

建议目录：

- `data/admin/agents/*.yaml`
- `data/admin/model_providers/*.yaml`
- `data/admin/models/*.yaml`

要求：

- 重启后数据可恢复
- 写入操作必须原子化
- 列表查询必须从持久层真实读取
- 不依赖 `control-plane` 做缓存真源

## Common Query Parameters

列表接口至少支持：

- `page`
- `page_size`
- `keyword`
- `status`

列表返回结构：

```json
{
  "ok": true,
  "data": {
    "items": [],
    "total": 0,
    "page": 1,
    "page_size": 20
  }
}
```

## Agent API

### Endpoints

- `POST /xuanwu/v1/admin/agents`
- `GET /xuanwu/v1/admin/agents`
- `GET /xuanwu/v1/admin/agents/{agent_id}`
- `PUT /xuanwu/v1/admin/agents/{agent_id}`
- `DELETE /xuanwu/v1/admin/agents/{agent_id}`

### Agent Model

```json
{
  "id": "agent_customer_support",
  "name": "Customer Support Agent",
  "description": "Handles customer support conversations.",
  "system_prompt": "You are a helpful customer support assistant.",
  "model_bindings": {
    "chat": "model_openai_gpt4o_default"
  },
  "status": "active",
  "version": 3,
  "created_at": "2026-03-28T10:00:00Z",
  "updated_at": "2026-03-28T10:20:00Z"
}
```

### Required Fields

- `id`
- `name`
- `system_prompt`
- `model_bindings`
- `status`

### Optional Fields

- `description`

### Validation Rules

- `id` 只允许稳定标识格式，建议小写字母、数字、下划线、中划线
- `name` 不能为空
- `name` 在有效作用域内唯一
- `system_prompt` 不能为空
- `model_bindings` 至少包含一个绑定
- `model_bindings` 中的每个值都必须引用已存在的 `Model Config`
- `status` 仅允许 `active` 或 `inactive`
- 更新成功后 `version` 自动递增

### Delete Rules

- 如果该 `Agent` 被后续运行时编排直接引用，可返回 `409`
- 不允许静默删除已被引用的对象

## Model Provider API

### Endpoints

- `POST /xuanwu/v1/admin/model-providers`
- `GET /xuanwu/v1/admin/model-providers`
- `GET /xuanwu/v1/admin/model-providers/{provider_id}`
- `PUT /xuanwu/v1/admin/model-providers/{provider_id}`
- `DELETE /xuanwu/v1/admin/model-providers/{provider_id}`

### Model Provider Model

```json
{
  "id": "provider_openai_primary",
  "name": "OpenAI Primary",
  "provider_type": "openai",
  "base_url": "https://api.openai.com/v1",
  "api_key_ref": "secret://providers/openai/primary",
  "status": "active",
  "config": {
    "timeout_seconds": 60
  },
  "created_at": "2026-03-28T10:00:00Z",
  "updated_at": "2026-03-28T10:00:00Z"
}
```

### Required Fields

- `id`
- `name`
- `provider_type`
- `base_url`
- `api_key_ref`
- `status`

### Validation Rules

- `name` 唯一
- `provider_type` 必须属于受支持列表
- `base_url` 必须是合法 URL
- `api_key_ref` 只存引用，不能回显密钥明文
- `status` 仅允许 `active` 或 `inactive`

### Delete Rules

- 若仍有 `Model Config` 引用该 provider，返回 `409`

## Model Config API

### Endpoints

- `POST /xuanwu/v1/admin/models`
- `GET /xuanwu/v1/admin/models`
- `GET /xuanwu/v1/admin/models/{model_id}`
- `PUT /xuanwu/v1/admin/models/{model_id}`
- `DELETE /xuanwu/v1/admin/models/{model_id}`

### Model Config Model

```json
{
  "id": "model_openai_gpt4o_default",
  "provider_id": "provider_openai_primary",
  "model_type": "chat",
  "model_name": "gpt-4o",
  "label": "GPT-4o Default",
  "capabilities": [
    "text"
  ],
  "params": {
    "temperature": 0.7,
    "max_tokens": 4096
  },
  "status": "active",
  "created_at": "2026-03-28T10:00:00Z",
  "updated_at": "2026-03-28T10:00:00Z"
}
```

### Required Fields

- `id`
- `provider_id`
- `model_type`
- `model_name`
- `label`
- `status`

### Validation Rules

- `provider_id` 必须引用已存在的 `Model Provider`
- `model_type` 必须属于受支持列表
- `label` 在同一 `provider_id` 下唯一
- `params` 必须通过结构化校验
- `status` 仅允许 `active` 或 `inactive`

### Delete Rules

- 若仍被任一 `Agent.model_bindings` 引用，返回 `409`

## Idempotency and Update Semantics

- `POST` 用于创建新资源
- `PUT` 用于全量更新现有资源
- 对不存在资源执行 `PUT` 返回 `404`
- 更新时不允许偷偷删除未显式给出的关键字段

## Logging

每个管理请求至少记录：

- `request_id`
- `resource_type`
- `resource_id`
- `operation`
- `result`
- `error_code`（如失败）

禁止在日志中输出：

- 明文 API key
- 明文 secret
- 不必要的大段 prompt 内容

## Compatibility Guidance

当前 `XuanWu` 代码已有以下可复用能力：

- `Model Config` 现有 CRUD 可以部分复用
- 现有 provider 能力发现接口可保留为内部辅助能力

但以下部分需要重构或重做：

- 旧 `agent-configs` 数据模型不满足本期 `Agent` 管理模型
- 旧 `provider-configs` 语义过宽，不等同于本期 `Model Provider`
- 运行时 `/api/*` 和管理 `/xuanwu/v1/admin/*` 必须分层

## Non-Goals

本期不做：

- Agent 运行时编译接口
- Template/Feature/MCP/Knowledge/Prompt/Workflow 的真实持久化
- Skill 安装或市场能力
- 后台前端页面
- control-plane 侧透传实现

## Test Requirements

至少覆盖以下测试：

### Agent

- 创建成功
- 列表分页成功
- 详情查询成功
- 更新后 `version` 递增
- 绑定不存在 `Model Config` 时返回 `422`
- 删除被引用对象时返回 `409`

### Model Provider

- 创建成功
- 名称唯一性冲突返回 `409`
- 非法 `base_url` 返回 `422`
- 删除被 `Model Config` 引用时返回 `409`

### Model Config

- 创建成功
- 引用不存在 `provider_id` 返回 `422`
- 同 provider 下重复 `label` 返回 `409`
- 删除被 `Agent` 引用时返回 `409`

### Security

- 缺失 `X-Xiaozhi-Control-Plane-Secret` 返回 `401`
- 错误 secret 返回 `401`

### Persistence

- 创建后重启服务仍可查询
- 更新后磁盘数据同步变化
- 删除后磁盘文件被清理

## Acceptance Criteria

实现完成后必须满足：

- `Agent / Model Provider / Model Config` 三类 CRUD 全可用
- 数据真实落盘在 `XuanWu`
- `control-plane` 可直接透传调用
- `control-plane` 不保存这三类对象副本
- 删除引用中资源时稳定返回 `409`
- 管理 API 与运行时 API 有明确边界
- 未实现模块没有被误做成半成品 API
- `Skill` 没有安装入口
