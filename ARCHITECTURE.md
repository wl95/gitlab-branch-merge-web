# 工程结构说明

## 后端

- `webapp.py`：HTTP 服务入口、路由处理、任务调度。
- `utils/app_config.py`：配置文件路径、`config.ini` 全局配置读写、工程配置规范化、变量解析。
- `utils/runtime_store.py`：运行时 JSON 文件读写，包括配置方案、分支操作 undo、危险操作审计日志。
- `utils/app_logging.py`：供前端轮询展示的内存日志队列。
- `gitlab_merge.py`：Git 命令执行、分支合并、分支操作、commit 查询等 Git 领域逻辑。

## 前端

- `frontend/src/api/`：后端接口封装。
- `frontend/src/router/`：前端路由配置。
- `frontend/src/views/`：页面级入口。当前工程合并管理台位于 `ProjectMergeView.vue`。
- `frontend/src/stores/`：Pinia 状态。通用数据规范化逻辑拆到同目录独立模块。
- `frontend/src/components/`：页面内可复用业务组件和通用组件，不再放页面入口。
- `frontend/src/utils/`：纯工具函数。
- `frontend/src/styles/index.css`：样式唯一入口；后续新增样式文件从这里汇总。
- `frontend/src/styles/main.css`：当前历史主样式文件，后续按模块逐步拆分。

## 拆分原则

- HTTP handler 不直接承载配置读写、文件存储、Git 领域逻辑。
- Store 只保留状态和 action，数据规范化、localStorage 读写和纯函数优先拆到独立模块。
- 样式按入口统一导入，后续按页面或组件域逐步从 `main.css` 拆出。
