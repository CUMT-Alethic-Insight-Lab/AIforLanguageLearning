# 安全问题积压清单（暂不处理）

更新时间：2026-05-19

说明：

- 本文档仅记录已确认的安全类问题，当前不作为修复重点。
- 当前审计主线切换为核心业务逻辑、结果可信度、演示可用性问题。

## P0

1. `backend_fastapi/app/routers/system.py`
   - `/api/system/config` 未鉴权即可修改运行时配置与部分 settings。

2. `backend_fastapi/app/routers/model_routing.py`
   - `/config`、`/context/clear`、`/context/{conversation_id}` 未鉴权。

3. `backend_fastapi/app/interfaces/prompt_registry_router.py`
   - Prompt 创建、发布、废弃未鉴权。

4. `backend_fastapi/app/interfaces/storage_router.py`
   - 上传、分片上传、预签名 URL 接口未鉴权。
   - 客户端可自定义 bucket/key。
   - 上传接口一次性读入整个文件，存在 DoS 面。

5. `backend_fastapi/app/interfaces/auth_router.py`
   - refresh token 与 access token 未做类型区分，access token 可刷新。

6. `backend_fastapi/app/main.py`
   - `/ws/v1` 直接信任 query 参数中的 `user_id`、`conversation_id`。

7. `backend_fastapi/app/interfaces/knowledge_graph_router.py`
   - `/relations/add` 未鉴权即可写图谱关系。

## P1

1. `backend_fastapi/app/settings.py`
   - JWT secret、MinIO access key、MinIO secret key 存在可预测默认值。

2. `backend_fastapi/app/infrastructure/security.py`
   - `_get_secret()` 仍保留开发用兜底默认密钥。

3. `backend_fastapi/app/interfaces/admin_router.py`
   - `/backups/restore` 对 `filename` 未做 `basename` 归一化。

4. `backend_fastapi/app/interfaces/admin_router.py`
   - 管理员重置密码未复用密码强度校验。

## 备注

- `backend_fastapi/app/interfaces/tasks_router.py` 的未鉴权问题已在之前修复，不再列为待办。
- 后续修复时建议按“鉴权 -> 凭据/密钥 -> WebSocket 身份绑定 -> 文件/对象存储约束”的顺序处理。
