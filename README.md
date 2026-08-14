# GitLab 分支批量合并管理台

面向 GitLab 的多工程分支批量管理 Web 工具：将各工程的源分支合并到多个目标分支，支持分支创建 / 删除 / 重命名、commit 选择合入（cherry-pick）、合并撤回（undo）、本地仓库扫描导入、配置方案管理。

## 功能点

- **多工程批量合并**：源分支 → 多个目标分支，自动 clone / 拉取本地仓库，本地有改动时拒绝操作；支持 dry-run 演练
- **分支批量管理**：多工程同时创建（支持一次输入多个分支名）、删除（受保护分支禁止删除）、重命名远程分支
- **Commit 选择合入**：分支 commit 分页浏览、`源..目标` 区间预览、单个 commit diff 查看、cherry-pick 精准合入
- **合并撤回**：合并前记录快照（before/after SHA），一键还原最近一次合并
- **配置方案**：整套工程配置存为方案，一键保存 / 切换 / 删除
- **仓库扫描导入**：扫描文件夹下所有 Git 仓库，一键加入工程列表
- **实时日志**：后台线程执行合并，前端逐条实时显示进度

## 快速开始

### 环境要求

- Python 3.8+
- Git（须已配置 SSH 访问 GitLab/GitHub）
- Node.js 16+（仅前端构建需要）

### 启动

```bash
# 1. 构建前端（输出到 dist/，由后端直接伺服）
cd frontend
npm install
npm run build
cd ..

# 2. 复制并修改配置
cp config.ini.example config.ini

# 3. 启动 Web 管理台（默认 8765 端口）
./start_webapp.sh
# 自定义端口：./start_webapp.sh 9000
```

浏览器访问 http://127.0.0.1:8765/

### 命令行模式（脚本化 / 定时任务）

```bash
python3 gitlab_merge.py config.ini --dry-run            # 演练：只打印将要执行的命令
python3 gitlab_merge.py config.ini --project demo1      # 只处理指定工程（可多次指定）
```

## 配置说明

`config.ini`（需自行创建，参照 `config.ini.example`）：

- `[DEFAULT]`：日志级别等通用项
- `[project:xxx]`：每段一个工程，包含 `ssh_host`（远程地址）、`project_path`、`source_branch`（源分支）、`target_branches`（目标分支，逗号分隔）、`local_dir`（本地仓库目录，留空自动 clone 到 `repos/`）

## 技术栈

- 后端：Python 标准库（`http.server` 线程池）+ 封装 git 命令，零第三方依赖
- 前端：Vue3 + Element Plus + Pinia + Vite，构建产物由后端伺服，单进程部署

## 目录结构

```
.
├── webapp.py            # Web 服务（API + 静态资源伺服）
├── gitlab_merge.py      # 核心 Git 操作库 + CLI
├── start_webapp.sh      # 启动脚本
├── frontend/            # Vue3 前端源码
├── repos/               # 本地仓库缓存（不入库）
└── dist/                # 前端构建产物（不入库）
```
