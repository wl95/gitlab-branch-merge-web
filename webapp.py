#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitLab 分支合并 Web 管理台

在浏览器中配置工程（SSH 地址、源分支、多个目标分支），
点击按钮一键执行合并，实时查看日志。

启动：
  python3 webapp.py                # 默认 http://127.0.0.1:8765/
  python3 webapp.py --port 9000    # 自定义端口
"""

import argparse
import configparser
import json
import logging
import mimetypes
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import gitlab_merge as gm

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.ini"
PROFILES_FILE = BASE_DIR / "profiles.json"
UNDO_FILE = BASE_DIR / "merge_undo.json"
BRANCH_OP_UNDO_FILE = BASE_DIR / "branch_op_undo.json"
AUDIT_LOG_FILE = BASE_DIR / "danger_audit_log.json"
gm.UNDO_FILE = str(UNDO_FILE)


# ---------------------------------------------------------------- 日志存储

class LogStore:
    """内存日志环形存储，供前端按增量轮询。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._entries = []
        self._next_id = 1

    def add(self, text):
        with self._lock:
            eid = self._next_id
            self._next_id += 1
            self._entries.append((eid, text))
            return eid

    def since(self, n):
        with self._lock:
            return [(eid, t) for eid, t in self._entries if eid > n]

    def all(self):
        with self._lock:
            return list(self._entries)

    def clear(self):
        with self._lock:
            self._entries.clear()
            self._next_id = 1


class QueueLogHandler(logging.Handler):
    def __init__(self, store):
        super().__init__()
        self._store = store

    def emit(self, record):
        try:
            self._store.add(self.format(record))
        except Exception:
            pass


log_store = LogStore()
STATE = {"busy": False, "lock": threading.Lock()}


def setup_logging():
    handler = QueueLogHandler(log_store)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


# ---------------------------------------------------------------- 配置读写

def load_projects():
    """读取配置文件中的工程列表（结构完整，含默认值派生字段）。"""
    try:
        _default, projects = gm.load_config(str(CONFIG_FILE))
        return projects
    except SystemExit:
        return []


def _read_cfg():
    """从 config.ini 读出 ConfigParser（含 [global] 等所有段）。"""
    cfg = configparser.ConfigParser()
    if CONFIG_FILE.exists():
        cfg.read(str(CONFIG_FILE), encoding="utf-8")
    return cfg


def load_global():
    """读取 [global] 段下的全局分支设置（用于跨工程的批量源/目标分支）。"""
    cfg = _read_cfg()
    if not cfg.has_section("global"):
        return {"ssh_host": "", "source_branch": "", "target_branches": []}
    targets_str = cfg.get("global", "target_branches", fallback="")
    return {
        "ssh_host": cfg.get("global", "ssh_host", fallback=""),
        "source_branch": cfg.get("global", "source_branch", fallback=""),
        "target_branches": [t.strip() for t in targets_str.split(",") if t.strip()],
    }


def save_global(g):
    """把全局面板的值写入 [global] 段（不与其他段冲突）。"""
    g = g or {}
    cfg = _read_cfg()
    if not cfg.has_section("global"):
        cfg.add_section("global")
    cfg.set("global", "ssh_host", (g.get("ssh_host") or "").strip())
    cfg.set("global", "source_branch", (g.get("source_branch") or "").strip())
    tgts = g.get("target_branches") or []
    if isinstance(tgts, str):
        tgts = [t.strip() for t in tgts.split(",") if t.strip()]
    if not isinstance(tgts, list):
        tgts = []
    cfg.set("global", "target_branches", ",".join(t.strip() for t in tgts if t.strip()))
    with open(str(CONFIG_FILE), "w", encoding="utf-8") as f:
        cfg.write(f)


def auto_project_name(s, i):
    """工程名称自动生成：优先用项目路径最后一段，其次 SSH 地址中的路径，回退 projectN。"""
    name = (s.get("name") or "").strip()
    if name:
        return name
    path = (s.get("project_path") or "").strip("/")
    if path:
        return path.split("/")[-1]
    host = (s.get("ssh_host") or "").strip()
    if gm._is_full_url(host):
        p = gm.extract_path_from_url(host)
        if p:
            return p.split("/")[-1]
    return f"project{i}"


# ---------------------------------------------------------------- 分支查询

def fetch_branches(host, info=None):
    """获取远程仓库的全部分支（git ls-remote --heads）。

    info 可含 project_path、local_dir、ssh_port：
    - 若提供了 local_dir 且是本地仓库，优先用本地仓库读取 origin url，
      无需网络即可快速返回（并且与合并时使用的仓库一致）；
    - 否则走 build_remote_url 构造地址 + ls-remote 远程查询。
    返回排序后的分支名列表（含 HEAD 分支）。
    """
    info = info or {}
    project_path = (info.get("project_path") or "").strip("/")
    local_dir = (info.get("local_dir") or "").strip()
    ssh_port = info.get("ssh_port") or 22

    remote_url = ""
    # 优先使用本地仓库的 origin url，保证与合并实际使用的地址一致
    if local_dir and gm.is_git_repo(local_dir):
        cfg_path = _git_config_path(local_dir)
        if cfg_path:
            remote_url = _git_origin_url(cfg_path)
    if not remote_url:
        try:
            remote_url = gm.build_remote_url({
                "ssh_host": host, "project_path": project_path,
                "ssh_port": ssh_port,
            })
        except Exception:
            remote_url = host

    cwd = str(BASE_DIR)
    proc = gm.run_git(
        ["ls-remote", "--heads", remote_url], cwd, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "git ls-remote 失败")
    branches = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line or "\t" not in line:
            continue
        _, ref = line.split("\t", 1)
        if ref.startswith("refs/heads/"):
            branches.append(ref[len("refs/heads/"):])
    return sorted(set(branches))


# ---------------------------------------------------------------- 文件夹扫描

def _git_config_path(repo_dir):
    """返回仓库 .git 实际 config 文件路径（兼容 .git 目录与 worktree 的 .git 文件）。"""
    git_path = Path(repo_dir) / ".git"
    if git_path.is_dir():
        return git_path / "config"
    if git_path.is_file():
        # worktree / submodule 场景：.git 内为 "gitdir: <path>"
        try:
            for line in git_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if line.startswith("gitdir:"):
                    gd = Path(line.split(":", 1)[1].strip())
                    if not gd.is_absolute():
                        gd = Path(repo_dir) / gd
                    return gd / "config"
        except Exception:
            pass
    return None


def _git_origin_url(config_path):
    """从 git config 文件中读取 remote "origin" 的 url。"""
    try:
        cfg = configparser.ConfigParser()
        cfg.read(str(config_path), encoding="utf-8")
        for sec in cfg.sections():
            if sec.lower().startswith('remote "origin"'):
                return cfg.get(sec, "url", fallback="").strip()
    except Exception:
        pass
    return ""


# 常见无需扫描的目录（避免递归扫描耗时与误报）
_SKIP_DIRS = {
    "node_modules", "vendor", ".git", ".svn", ".hg", "__pycache__",
    "dist", "build", "target", ".idea", ".vscode", "venv", ".venv", "Pods",
}


def scan_git_repos(folder):
    """递归扫描文件夹下所有 git 仓库子目录，读取每个仓库的 remote url。

    返回 (repos, warnings)，其中 repos 为 [{name, path, ssh_host, project_path}, ...]，
    warnings 为扫描过程中遇到的无权限/异常目录说明。
    """
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"文件夹不存在或不可读: {root}")

    repos, seen = [], set()
    warnings = []
    stack = [(root, 0)]

    while stack:
        d, depth = stack.pop()
        try:
            if _git_config_path(d) is not None:
                config_path = _git_config_path(d)
                if config_path and config_path.exists():
                    cfg_key = str(config_path.resolve())
                    if cfg_key not in seen:
                        url = _git_origin_url(config_path)
                        if url:
                            seen.add(cfg_key)
                            repos.append({
                                "name": d.name,
                                "path": str(d),
                                "ssh_host": url,
                                "project_path": gm.extract_path_from_url(url),
                            })
                        # 是仓库但无 origin 地址，也记录一下
                        elif cfg_key not in seen:
                            seen.add(cfg_key)
                            warnings.append(f"{d}: 是 git 仓库但没有 remote origin 地址")
            # 递归进入子目录（最多 6 层）
            if depth < 6:
                for sub in sorted(d.iterdir(), key=lambda x: x.name):
                    if not sub.is_dir():
                        continue
                    if sub.name in _SKIP_DIRS:
                        continue
                    stack.append((sub, depth + 1))
        except PermissionError:
            warnings.append(f"{d}: 无权限读取（可检查 系统设置→隐私与安全性→完全磁盘访问）")
        except OSError as e:
            warnings.append(f"{d}: {e}")

    repos.sort(key=lambda r: r["name"].lower())
    return repos, warnings


def normalize_projects(submitted):
    """把前端提交的简化配置补全为 process_project 所需的完整结构。"""
    try:
        _default, existing = gm.load_config(str(CONFIG_FILE))
    except SystemExit:
        _default, existing = {}, []
    projects = []
    for i, s in enumerate(submitted, 1):
        name = auto_project_name(s, i)
        base = next((e for e in existing if e["name"] == name), None)
        p = dict(base) if base else dict(_default)
        p["name"] = name
        p["ssh_host"] = (s.get("ssh_host") or "").strip()
        p["project_path"] = (s.get("project_path") or "").strip("/")
        p["source_branch"] = (s.get("source_branch") or "").strip()
        targets = s.get("target_branches") or []
        if isinstance(targets, str):
            targets = targets.split(",")
        p["target_branches"] = [t.strip() for t in targets if t.strip()]
        # 优先使用前端扫描时传入的本地仓库目录（本地已 clone，直接复用）
        submitted_local = (s.get("local_dir") or "").strip()
        if submitted_local:
            p["local_dir"] = submitted_local
        if not p.get("local_dir"):
            dir_part = (p.get("project_path")
                        or gm.extract_path_from_url(p["ssh_host"])
                        or name)
            p["local_dir"] = os.path.join(
                p.get("local_dir_base", "./repos"), dir_part.replace("/", "__"))
        projects.append(p)
    return projects


def save_projects(projects):
    """将工程列表写回 config.ini（保留 [default] 等其他段）。"""
    cfg = configparser.ConfigParser()
    if CONFIG_FILE.exists():
        cfg.read(str(CONFIG_FILE), encoding="utf-8")
    for sec in list(cfg.sections()):
        if sec.lower().startswith("project"):
            cfg.remove_section(sec)
    for i, p in enumerate(projects, 1):
        name = (p.get("name") or "").strip() or f"project{i}"
        sec = f"project:{name}"
        cfg.add_section(sec)
        cfg.set(sec, "ssh_host", (p.get("ssh_host") or "").strip())
        pp = (p.get("project_path") or "").strip()
        if pp:
            cfg.set(sec, "project_path", pp)
        cfg.set(sec, "source_branch", (p.get("source_branch") or "").strip())
        targets = p.get("target_branches") or []
        if isinstance(targets, str):
            targets = [t.strip() for t in targets.split(",") if t.strip()]
        cfg.set(sec, "target_branches", ",".join(targets))
        local_dir = (p.get("local_dir") or "").strip()
        if local_dir:
            cfg.set(sec, "local_dir", local_dir)
    with open(str(CONFIG_FILE), "w", encoding="utf-8") as f:
        cfg.write(f)


# ---------------------------------------------------------------- 配置方案（profiles）

def load_profiles():
    """读取全部已保存的配置方案：{name: {updated, projects, global}}"""
    if not PROFILES_FILE.exists():
        return {}
    try:
        with open(str(PROFILES_FILE), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_profile(name, projects, global_cfg):
    """把当前配置保存为一个命名方案（按名称覆盖）。"""
    data = load_profiles()
    data[name] = {
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "projects": projects,
        "global": global_cfg or {},
    }
    with open(str(PROFILES_FILE), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def delete_profile(name):
    data = load_profiles()
    if name in data:
        del data[name]
        with open(str(PROFILES_FILE), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def save_branch_op_undo(action, items):
    if not items:
        return
    with open(str(BRANCH_OP_UNDO_FILE), "w", encoding="utf-8") as f:
        json.dump({
            "action": action,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "items": items,
        }, f, ensure_ascii=False, indent=2)


def load_branch_op_undo():
    if not BRANCH_OP_UNDO_FILE.exists():
        return None
    try:
        with open(str(BRANCH_OP_UNDO_FILE), "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("items"):
            return data
    except (OSError, ValueError):
        pass
    return None


def clear_branch_op_undo():
    try:
        if BRANCH_OP_UNDO_FILE.exists():
            BRANCH_OP_UNDO_FILE.unlink()
    except OSError:
        pass


def load_audit_logs():
    if not AUDIT_LOG_FILE.exists():
        return []
    try:
        with open(str(AUDIT_LOG_FILE), "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        return [sanitize_audit_entry(x) for x in data if isinstance(x, dict)]
    except (OSError, ValueError):
        return []


GIT_ADDRESS_KEYS = {"ssh_host", "git_url", "remote_url", "repo_url", "repository_url"}


def redact_git_address(value):
    """保留审计定位信息，去掉可能存在的用户名、密码或 token。"""
    s = str(value or "").strip()
    if not s:
        return ""
    if "://" in s:
        scheme, rest = s.split("://", 1)
        if "@" in rest:
            rest = "***@" + rest.rsplit("@", 1)[1]
        return f"{scheme}://{rest}"
    if "@" in s and ":" in s:
        return "***@" + s.rsplit("@", 1)[1]
    return s


def sanitize_audit_payload(value, git_addresses=None):
    git_addresses = git_addresses if git_addresses is not None else []
    if isinstance(value, dict):
        out = {}
        for k, child in value.items():
            if k in GIT_ADDRESS_KEYS:
                addr = redact_git_address(child)
                if addr and addr not in git_addresses:
                    git_addresses.append(addr)
                continue
            out[k] = sanitize_audit_payload(child, git_addresses)
        return out
    if isinstance(value, list):
        return [sanitize_audit_payload(child, git_addresses) for child in value]
    return value


def sanitize_audit_entry(entry):
    raw_payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
    git_addresses = []
    safe_payload = sanitize_audit_payload(raw_payload, git_addresses)
    for addr in entry.get("git_addresses") or []:
        redacted = redact_git_address(addr)
        if redacted and redacted not in git_addresses:
            git_addresses.append(redacted)
    safe = dict(entry)
    safe["payload"] = safe_payload
    safe["git_addresses"] = git_addresses
    safe["commands"] = collect_commands({"payload": safe_payload, "commands": entry.get("commands") or []})
    return safe


def append_audit_log(action, title, detail="", undo_type="", payload=None):
    payload = payload or {}
    git_addresses = []
    safe_payload = sanitize_audit_payload(payload, git_addresses)
    logs = load_audit_logs()
    logs.insert(0, {
        "id": f"{int(time.time() * 1000)}-{len(logs)}",
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "action": action,
        "title": title,
        "detail": detail,
        "undo_type": undo_type,
        "git_addresses": git_addresses,
        "payload": safe_payload,
        "commands": collect_commands(safe_payload),
    })
    with open(str(AUDIT_LOG_FILE), "w", encoding="utf-8") as f:
        json.dump(logs[:300], f, ensure_ascii=False, indent=2)


def delete_audit_logs(ids):
    idset = {str(i) for i in (ids or []) if str(i)}
    if not idset:
        return 0
    logs = load_audit_logs()
    kept = [x for x in logs if str(x.get("id")) not in idset]
    removed = len(logs) - len(kept)
    if removed:
        with open(str(AUDIT_LOG_FILE), "w", encoding="utf-8") as f:
            json.dump(kept, f, ensure_ascii=False, indent=2)
    return removed


def collect_commands(value):
    commands = []

    def walk(v):
        if isinstance(v, dict):
            for k, child in v.items():
                if k == "commands" and isinstance(child, list):
                    commands.extend(str(c) for c in child if c)
                else:
                    walk(child)
        elif isinstance(v, list):
            for child in v:
                walk(child)

    walk(value)
    seen = set()
    out = []
    for cmd in commands:
        if cmd in seen:
            continue
        seen.add(cmd)
        out.append(cmd)
    return out


def suggest_profile_name(global_cfg):
    """根据全局目标分支自动生成方案名（目标分支同名）。"""
    g = global_cfg or {}
    targets = g.get("target_branches") or []
    if isinstance(targets, str):
        targets = [t.strip() for t in targets.split(",") if t.strip()]
    return targets[0] if targets else ""


def profile_summary(name, data):
    """生成方案列表所需的摘要信息（含源分支与目标分支说明）。"""
    projects = data.get("projects") or []
    g = data.get("global") or {}
    targets = g.get("target_branches") or []
    if isinstance(targets, str):
        targets = [t.strip() for t in targets.split(",") if t.strip()]

    # 源分支：优先取全局配置，否则从各工程去重提取
    source = (g.get("source_branch") or "").strip()
    source_branches = []
    if source:
        source_branches = [source]
    else:
        for p in projects:
            sb = (p.get("source_branch") or "").strip()
            if sb and sb not in source_branches:
                source_branches.append(sb)

    # 工程名列表：让用户知道方案里具体包含哪几个工程
    project_names = []
    for i, p in enumerate(projects):
        pn = auto_project_name(p, i + 1)
        if pn and pn not in project_names:
            project_names.append(pn)

    return {
        "name": name,
        "updated": data.get("updated", ""),
        "project_count": len(projects),
        "project_names": project_names,
        "source_branches": source_branches,
        "target_branches": targets,
    }


# ---------------------------------------------------------------- 后台合并

def start_merge(projects):
    """后台线程执行合并任务，返回是否成功启动。"""
    with STATE["lock"]:
        if STATE["busy"]:
            return False
        STATE["busy"] = True

    def worker():
        try:
            save_projects(projects)
            logging.info("=" * 20)
            logging.info("开始执行合并任务，共 %d 个项目", len(projects))
            ok_all = True
            all_undo = []
            for p in projects:
                try:
                    ok, undo_items = gm.process_project(p, dry_run=False)
                    all_undo.extend(undo_items or [])
                    if not ok:
                        ok_all = False
                except SystemExit as e:
                    logging.error("项目 [%s] 处理中止: %s", p.get("name"), e)
                    ok_all = False
                except Exception as e:
                    logging.error("项目 [%s] 异常: %s", p.get("name"), e)
                    ok_all = False
            # 保存本次合并的可撤回快照（供「撤回合并」使用）
            if all_undo:
                # 为每个分支补齐本次合并的 commit 列表（用于详情展示）
                for it in all_undo:
                    try:
                        commits = gm.list_merged_commits(it)
                    except Exception as e:
                        logging.warning("获取 [%s/%s] commit 列表失败: %s",
                                        it.get("name"), it.get("branch"), e)
                        commits = []
                    it["commits"] = commits
                    it["commit_count"] = len(commits)
                gm.save_undo(all_undo)
                append_audit_log(
                    "merge",
                    "执行合并",
                    f"共 {len(projects)} 个工程，{len(all_undo)} 个分支可撤回",
                    "merge",
                    {"items": all_undo},
                )
                logging.info("已记录 %d 个分支的合并快照，可在界面撤回", len(all_undo))
            logging.info("任务结束：%s",
                         "全部成功" if ok_all else "存在失败，请人工检查")
        finally:
            with STATE["lock"]:
                STATE["busy"] = False

    threading.Thread(target=worker, daemon=True).start()
    return True


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # 静默访问日志

    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, path, ctype):
        try:
            data = Path(path).read_bytes()
        except FileNotFoundError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        # 禁止浏览器启发式缓存，确保每次部署后拿到最新资源
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        # 预检请求直接返回允许
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _read_body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return {}
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def _serve_dist(self, path):
        """伺服前端构建产物 dist/ 下的静态资源，失败返回 False。"""
        dist_root = BASE_DIR / "dist"
        if not dist_root.exists():
            return False
        if path in ("/", "/index.html"):
            if (dist_root / "index.html").is_file():
                self._serve_file(dist_root / "index.html",
                                 "text/html; charset=utf-8")
                return True
            return False
        rel = path.lstrip("/")
        if not rel:
            return False
        target = (dist_root / rel).resolve()
        try:
            target.relative_to(dist_root.resolve())
        except ValueError:
            return False  # 防止路径穿越
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            return False
        ctype = mimetypes.guess_type(str(target))[0] \
            or "application/octet-stream"
        self._serve_file(target, ctype)
        return True

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/", "/index.html"):
            # 优先伺服前端构建产物，其次回退到原生 index.html
            if not self._serve_dist(path):
                self._serve_file(BASE_DIR / "index.html",
                                 "text/html; charset=utf-8")
        elif path == "/api/profiles":
            data = load_profiles()
            self._send_json({
                "ok": True,
                "profiles": [profile_summary(n, d) for n, d in data.items()],
            })
        elif path == "/api/state":
            self._send_json({"busy": STATE["busy"],
                             "projects": load_projects(),
                             "global": load_global()})
        elif path == "/api/logs":
            q = parse_qs(parsed.query)
            since = int(q.get("since", ["0"])[0] or 0)
            entries = log_store.since(since)
            new_since = entries[-1][0] if entries else since
            self._send_json({"logs": entries, "since": new_since})
        elif path == "/api/logs/all":
            entries = log_store.all()
            new_since = entries[-1][0] if entries else 0
            self._send_json({"logs": entries, "since": new_since})
        elif path == "/api/audit/logs":
            self._send_json({"ok": True, "logs": load_audit_logs()})
        elif path == "/api/clear":
            log_store.clear()
            self._send_json({"ok": True})
        elif path == "/api/merge/undo":
            # 查询最近一次合并的可撤回记录
            data = gm.load_undo()
            if not data or not data.get("items"):
                self._send_json({"ok": True, "has_undo": False})
                return

            # 懒补：旧 undo 快照（升级前的合并）可能没有 commits 字段，
            # 在这里为缺失的 item 实时拉取并写回 JSON，后续访问即 fast path。
            need_persist = False
            for it in data["items"]:
                if "commits" not in it and it.get("before_sha") and it.get("after_sha"):
                    try:
                        it["commits"] = gm.list_merged_commits(it)
                    except Exception as e:
                        logging.warning("补齐 [%s/%s] commit 失败: %s",
                                        it.get("name"), it.get("branch"), e)
                        it["commits"] = []
                    it["commit_count"] = len(it["commits"])
                    need_persist = True
            if need_persist:
                try:
                    gm.save_undo(data["items"], merged_at=data.get("merged_at"))
                except Exception as e:
                    logging.warning("写回补齐后的 undo 快照失败: %s", e)

            self._send_json({
                "ok": True,
                "has_undo": True,
                "merged_at": data.get("merged_at", ""),
                "items": [{
                    "name": it.get("name", ""),
                    "branch": it.get("branch", ""),
                    "source_branch": it.get("source_branch", ""),
                    "before_sha": (it.get("before_sha") or "")[:8],
                    "after_sha": (it.get("after_sha") or "")[:8],
                    "commit_count": len(it.get("commits") or []),
                    "commits": it.get("commits") or [],
                } for it in data["items"]],
            })
        elif path in ("/api/branch/undo", "/api/branch/create/undo"):
            data = load_branch_op_undo()
            if not data:
                self._send_json({"ok": True, "has_undo": False})
                return
            self._send_json({
                "ok": True,
                "has_undo": True,
                "action": data.get("action", ""),
                "created_at": data.get("created_at", ""),
                "items": [{
                    "name": it.get("name", ""),
                    "branch_name": it.get("branch_name", ""),
                    "old_name": it.get("old_name", ""),
                    "new_name": it.get("new_name", ""),
                    "sha": (it.get("sha") or "")[:8],
                    "project": {
                        "name": (it.get("project") or {}).get("name", ""),
                        "ssh_host": (it.get("project") or {}).get("ssh_host", ""),
                        "project_path": (it.get("project") or {}).get("project_path", ""),
                        "local_dir": (it.get("project") or {}).get("local_dir", ""),
                    },
                } for it in data.get("items", [])],
            })
        elif not self._serve_dist(path):
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        body = self._read_body()
        if parsed.path == "/api/branches":
            host = (body.get("ssh_host") or "").strip()
            if not host:
                self._send_json({"ok": False, "error": "请先填写 SSH 地址"}, code=400)
                return
            try:
                branches = fetch_branches(host, body)
                self._send_json({"ok": True, "branches": branches})
            except Exception as e:
                self._send_json({"ok": False, "error": f"获取分支失败: {e}"}, code=400)
        elif parsed.path == "/api/branch/create":
            projects = normalize_projects(body.get("projects", []))
            raw = body.get("branch_names")
            if raw is None:
                raw = body.get("branch_name") or ""
            if isinstance(raw, str):
                # 兼容单个分支名；也支持用逗号/换行分隔的多个名字
                raw = [s for s in raw.replace("\n", ",").split(",") if s.strip()]
            branch_names = [str(s).strip() for s in raw if str(s).strip()]
            from_branch = (body.get("from_branch") or "").strip()
            if not projects:
                self._send_json({"ok": False, "error": "请至少选择一个工程"}, code=400)
                return
            if not branch_names:
                self._send_json({"ok": False, "error": "请填写要创建的分支名"}, code=400)
                return
            results = []
            undo_items = []
            for bn in branch_names:
                for p in projects:
                    try:
                        ok, msg, commands, meta = gm.create_branch(p, bn, from_branch or None)
                        results.append({"name": f"{p['name']}（{bn}）",
                                        "ok": True, "message": msg,
                                        "commands": commands})
                        undo_items.append({
                            "name": p["name"],
                            "branch_name": meta["branch_name"],
                            "sha": meta["sha"],
                            "project": p,
                        })
                    except Exception as e:
                        results.append({"name": f"{p['name']}（{bn}）",
                                        "ok": False, "error": str(e),
                                        "commands": getattr(e, "commands", [])})
            if undo_items:
                save_branch_op_undo("create", undo_items)
                append_audit_log(
                    "branch_create",
                    "创建分支",
                    f"基于 {from_branch} 创建：{', '.join(branch_names)}；成功 {len(undo_items)} 个远程分支",
                    "branch",
                    {
                        "request": {
                            "projects": projects,
                            "branch_names": branch_names,
                            "from_branch": from_branch,
                        },
                        "results": results,
                        "undo_items": undo_items,
                    },
                )
            self._send_json({"ok": True, "action": "create",
                             "branch_names": branch_names, "results": results,
                             "undo_count": len(undo_items)})
        elif parsed.path == "/api/branch/delete":
            projects = normalize_projects(body.get("projects", []))
            raw = body.get("branch_names")
            if raw is None:
                raw = body.get("branch_name") or ""
            if isinstance(raw, str):
                raw = [s for s in raw.replace("\n", ",").split(",") if s.strip()]
            branch_names = [str(s).strip() for s in raw if str(s).strip()]
            if not projects:
                self._send_json({"ok": False, "error": "请至少选择一个工程"}, code=400)
                return
            if not branch_names:
                self._send_json({"ok": False, "error": "请填写要删除的分支名"}, code=400)
                return
            results = []
            undo_items = []
            for bn in branch_names:
                for p in projects:
                    try:
                        ok, msg, commands, meta = gm.delete_branch(p, bn)
                        results.append({"name": f"{p['name']}（{bn}）", "ok": True,
                                        "message": msg, "commands": commands})
                        undo_items.append({
                            "name": p["name"],
                            "branch_name": meta["branch_name"],
                            "sha": meta["sha"],
                            "project": p,
                        })
                    except Exception as e:
                        results.append({"name": f"{p['name']}（{bn}）", "ok": False,
                                        "error": str(e),
                                        "commands": getattr(e, "commands", [])})
            if undo_items:
                save_branch_op_undo("delete", undo_items)
                append_audit_log(
                    "branch_delete",
                    "删除分支",
                    f"删除分支：{', '.join(branch_names)}；成功 {len(undo_items)} 个远程分支，可按原 SHA 恢复",
                    "branch",
                    {
                        "request": {
                            "projects": projects,
                            "branch_names": branch_names,
                        },
                        "results": results,
                        "undo_items": undo_items,
                    },
                )
            self._send_json({"ok": True, "action": "delete",
                             "branch_names": branch_names, "results": results,
                             "undo_count": len(undo_items)})
        elif parsed.path == "/api/branch/rename":
            projects = normalize_projects(body.get("projects", []))
            old_name = (body.get("old_name") or "").strip()
            new_name = (body.get("new_name") or "").strip()
            if not projects:
                self._send_json({"ok": False, "error": "请至少选择一个工程"}, code=400)
                return
            if not old_name:
                self._send_json({"ok": False, "error": "请填写要重命名的原分支名"}, code=400)
                return
            if not new_name:
                self._send_json({"ok": False, "error": "请填写新分支名"}, code=400)
                return
            results = []
            undo_items = []
            for p in projects:
                try:
                    ok, msg, commands, meta = gm.rename_branch(p, old_name, new_name)
                    results.append({"name": p["name"], "ok": True, "message": msg,
                                    "commands": commands})
                    undo_items.append({
                        "name": p["name"],
                        "old_name": meta["old_name"],
                        "new_name": meta["new_name"],
                        "sha": meta["sha"],
                        "project": p,
                    })
                except Exception as e:
                    results.append({"name": p["name"], "ok": False, "error": str(e),
                                    "commands": getattr(e, "commands", [])})
            if undo_items:
                save_branch_op_undo("rename", undo_items)
                append_audit_log(
                    "branch_rename",
                    "重命名分支",
                    f"{old_name} -> {new_name}；成功重命名 {len(undo_items)} 个远程分支",
                    "branch",
                    {
                        "request": {
                            "projects": projects,
                            "old_name": old_name,
                            "new_name": new_name,
                        },
                        "results": results,
                        "undo_items": undo_items,
                    },
                )
            self._send_json({"ok": True, "action": "rename",
                             "old_name": old_name, "new_name": new_name,
                             "results": results, "undo_count": len(undo_items)})
        elif parsed.path in ("/api/branch/undo", "/api/branch/create/undo"):
            data = load_branch_op_undo()
            items = (data or {}).get("items") or []
            if not items:
                self._send_json({"ok": False, "error": "暂无可撤回的分支操作记录"}, code=400)
                return
            action = data.get("action")
            results = []
            for it in items:
                p = it.get("project") or {}
                label = it.get("name") or p.get("name") or p.get("ssh_host")
                try:
                    if action == "create":
                        branch_name = (it.get("branch_name") or "").strip()
                        ok, msg, commands, _meta = gm.delete_branch(
                            p, branch_name, allow_protected=True)
                        name = f"{label}（{branch_name}）"
                    elif action == "delete":
                        branch_name = (it.get("branch_name") or "").strip()
                        ok, msg, commands, _meta = gm.create_branch_at_sha(
                            p, branch_name, it.get("sha"))
                        name = f"{label}（{branch_name}）"
                    elif action == "rename":
                        old_name = (it.get("old_name") or "").strip()
                        new_name = (it.get("new_name") or "").strip()
                        ok, msg, commands, _meta = gm.rename_branch(
                            p, new_name, old_name, allow_protected_old=True)
                        name = f"{label}（{new_name} → {old_name}）"
                    else:
                        raise RuntimeError("未知的分支撤回类型")
                    results.append({"name": name, "ok": True,
                                    "message": msg, "commands": commands})
                except Exception as e:
                    results.append({"name": label, "ok": False, "error": str(e),
                                    "commands": getattr(e, "commands", [])})
            if all(r.get("ok") for r in results):
                clear_branch_op_undo()
                append_audit_log(
                    f"undo_{action}",
                    "撤回分支操作",
                    f"已撤回 {len(results)} 个远程分支操作",
                    "",
                    {"action": action},
                )
            self._send_json({"ok": True, "action": f"undo_{action}",
                             "results": results,
                             "cleared": all(r.get("ok") for r in results)})
        elif parsed.path == "/api/scan":
            folder = (body.get("folder") or "").strip()
            if not folder:
                self._send_json({"ok": False, "error": "请填写文件夹路径"}, code=400)
                return
            try:
                repos, warnings = scan_git_repos(folder)
                self._send_json({"ok": True, "folder": folder,
                                 "repos": repos, "warnings": warnings})
            except ValueError as e:
                self._send_json({"ok": False, "error": str(e)}, code=400)
            except Exception as e:
                self._send_json({"ok": False, "error": f"扫描失败: {e}"}, code=400)
        elif parsed.path == "/api/save":
            projects = normalize_projects(body.get("projects", []))
            save_projects(projects)
            if isinstance(body.get("global"), dict):
                save_global(body["global"])
            self._send_json({"ok": True,
                             "projects": load_projects(),
                             "global": load_global()})
        elif parsed.path == "/api/audit/log":
            append_audit_log(
                body.get("action") or "frontend",
                body.get("title") or "危险操作",
                body.get("detail") or "",
                body.get("undo_type") or "",
                body.get("payload") if isinstance(body.get("payload"), dict) else {},
            )
            self._send_json({"ok": True})
        elif parsed.path == "/api/audit/log/delete":
            ids = body.get("ids") or []
            if isinstance(ids, str):
                ids = [ids]
            removed = delete_audit_logs(ids)
            self._send_json({"ok": True, "removed": removed})
        elif parsed.path == "/api/profile/save":
            name = (body.get("name") or "").strip()
            projects = normalize_projects(body.get("projects", []))
            global_cfg = body.get("global") if isinstance(body.get("global"), dict) else None
            # 名称留空时，自动按全局目标分支命名
            if not name:
                name = suggest_profile_name(global_cfg)
            if not name:
                self._send_json({"ok": False, "error": "请输入方案名称（或先设置全局目标分支）"}, code=400)
                return
            save_profile(name, projects, global_cfg)
            self._send_json({"ok": True, "name": name})
        elif parsed.path == "/api/profile/load":
            name = (body.get("name") or "").strip()
            data = load_profiles()
            if name not in data:
                self._send_json({"ok": False, "error": f"方案「{name}」不存在"}, code=404)
                return
            entry = data[name]
            projects = normalize_projects(entry.get("projects", []))
            save_projects(projects)
            if isinstance(entry.get("global"), dict):
                save_global(entry["global"])
            # 直接返回 normalize 后的方案数据，避免 gm.load_config 严格校验
            # （含未填 ssh_host 的工程）导致 load_projects 返回空列表
            self._send_json({"ok": True,
                             "projects": projects,
                             "global": entry.get("global") or load_global()})
        elif parsed.path == "/api/profile/delete":
            name = (body.get("name") or "").strip()
            if not name:
                self._send_json({"ok": False, "error": "缺少方案名称"}, code=400)
                return
            data = load_profiles()
            if name in data:
                append_audit_log(
                    "profile_delete",
                    "删除配置方案",
                    f"删除方案「{name}」",
                    "profile_delete",
                    {"name": name, "profile": data[name]},
                )
            delete_profile(name)
            self._send_json({"ok": True})
        elif parsed.path == "/api/profile/restore":
            name = (body.get("name") or "").strip()
            profile = body.get("profile")
            if not name or not isinstance(profile, dict):
                self._send_json({"ok": False, "error": "缺少方案恢复数据"}, code=400)
                return
            data = load_profiles()
            data[name] = profile
            with open(str(PROFILES_FILE), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            append_audit_log("profile_restore", "恢复配置方案", f"恢复方案「{name}」")
            self._send_json({"ok": True})
        elif parsed.path == "/api/commits":
            branch = (body.get("branch") or "").strip()
            if not branch:
                self._send_json({"ok": False, "error": "请选择分支"}, code=400)
                return
            try:
                page = max(1, int(body.get("page", 1)))
            except (TypeError, ValueError):
                page = 1
            try:
                page_size = min(200, max(1, int(body.get("page_size", 50))))
            except (TypeError, ValueError):
                page_size = 50
            try:
                conf = normalize_projects([body])[0]
                offset = (page - 1) * page_size
                commits = gm.list_commits(conf, branch,
                                          count=page_size, offset=offset)
                total = gm.count_commits(conf, branch)
                has_more = offset + len(commits) < total
                self._send_json({"ok": True, "commits": commits, "page": page,
                                 "page_size": page_size, "total": total,
                                 "has_more": has_more})
            except Exception as e:
                self._send_json({"ok": False, "error": f"获取 commit 失败: {e}"}, code=400)
        elif parsed.path == "/api/merge/range":
            # 返回 source..target 之间的 commits（本次将合并进 target 的）
            local_dir = (body.get("local_dir") or "").strip()
            source = (body.get("source_branch") or "").strip()
            target = (body.get("target_branch") or "").strip()
            if not (local_dir and source and target):
                self._send_json({"ok": False, "error": "缺少 local_dir / source_branch / target_branch"}, code=400)
                return
            try:
                # 默认拉到 500，足够覆盖大部分分支；硬上限 1000，避免误传超大值打爆仓库
                limit = min(1000, max(1, int(body.get("limit") or 500)))
            except (TypeError, ValueError):
                limit = 500
            try:
                items, total = gm.range_commits(local_dir, source, target, limit=limit)
                self._send_json({"ok": True, "items": items, "total": total,
                                 "source": source, "target": target,
                                 "limit": limit,
                                 "truncated": total > len(items)})
            except Exception as e:
                self._send_json({"ok": False, "error": f"获取 commits 失败: {e}"}, code=400)
        elif parsed.path == "/api/commit/diff":
            # 单个 commit 的改动详情（stat + patch）
            local_dir = (body.get("local_dir") or "").strip()
            sha = (body.get("sha") or "").strip()
            if not (local_dir and sha):
                self._send_json({"ok": False, "error": "缺少 local_dir / sha"}, code=400)
                return
            try:
                data = gm.commit_diff(local_dir, sha)
                if not data:
                    self._send_json({"ok": False, "error": "无法读取 commit diff"}, code=400)
                    return
                self._send_json({"ok": True, **data})
            except Exception as e:
                self._send_json({"ok": False, "error": f"读取 diff 失败: {e}"}, code=400)
        elif parsed.path == "/api/cherry-pick":
            target = (body.get("target_branch") or "").strip()
            commits = body.get("commits") or []
            if isinstance(commits, str):
                commits = [c.strip() for c in commits.split(",") if c.strip()]
            if not target:
                self._send_json({"ok": False, "error": "请选择目标分支"}, code=400)
                return
            if not commits:
                self._send_json({"ok": False, "error": "请至少选择一个 commit"}, code=400)
                return
            try:
                conf = normalize_projects([body])[0]
                msg = gm.cherry_pick_commits(conf, commits, target)
                append_audit_log(
                    "cherry_pick",
                    "Cherry-Pick",
                    f"{conf.get('name') or conf.get('ssh_host')} -> {target}，{len(commits)} 个 commit",
                    "",
                    {
                        "project": conf,
                        "target_branch": target,
                        "commits": commits,
                        "message": msg,
                    },
                )
                self._send_json({"ok": True, "message": msg})
            except Exception as e:
                self._send_json({"ok": False, "error": f"pick 失败: {e}"}, code=400)
        elif parsed.path == "/api/merge":
            projects = normalize_projects(body.get("projects", []))
            if not projects:
                self._send_json({"ok": False, "error": "没有可执行的工程"}, code=400)
                return
            if start_merge(projects):
                self._send_json({"ok": True, "status": "started"})
            else:
                self._send_json({"ok": False, "error": "已有合并任务在运行"}, code=409)
        elif parsed.path == "/api/merge/undo":
            # 执行撤回：后台线程逐条还原，日志实时反馈
            with STATE["lock"]:
                if STATE["busy"]:
                    self._send_json({"ok": False, "error": "已有任务在运行，请稍后再试"}, code=409)
                    return
                STATE["busy"] = True

            def undo_worker():
                try:
                    logging.info("=" * 20)
                    logging.info("开始撤回最近一次合并")
                    data = gm.load_undo()
                    items = (data or {}).get("items") or []
                    ok_all = True
                    for it in items:
                        try:
                            msg = gm.undo_merge_item(it)
                            logging.info(msg)
                        except SystemExit as e:
                            logging.error("撤回失败: %s", e)
                            ok_all = False
                        except Exception as e:
                            logging.error("撤回异常: %s", e)
                            ok_all = False
                    logging.info("撤回结束：%s",
                                 "全部成功" if ok_all else "存在失败，请人工检查")
                    # 撤回完成后清除快照，避免重复撤回
                    gm.clear_undo()
                    append_audit_log(
                        "undo_merge",
                        "撤回合并",
                        "已执行最近一次合并撤回" if ok_all else "合并撤回存在失败",
                        "",
                        {},
                    )
                finally:
                    with STATE["lock"]:
                        STATE["busy"] = False

            threading.Thread(target=undo_worker, daemon=True).start()
            self._send_json({"ok": True, "status": "started"})
        else:
            self.send_error(404)


def main():
    parser = argparse.ArgumentParser(description="GitLab 分支合并 Web 管理台")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=8765, help="监听端口")
    args = parser.parse_args()

    setup_logging()
    log_store.clear()
    logging.info("GitLab 合并管理台已启动: http://%s:%d/", args.host, args.port)

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logging.info("已停止")


if __name__ == "__main__":
    main()
