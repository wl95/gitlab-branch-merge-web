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
import html
import json
import logging
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlparse, urlunparse
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import gitlab_merge as gm
from utils.app_logging import log_store, setup_logging
from utils.app_config import (
    BASE_DIR,
    CONFIG_FILE,
    PROFILES_FILE,
    UNDO_FILE,
    load_global,
    load_projects,
    normalize_projects,
    project_repo_dir,
    resolve_config_vars,
    save_global,
    save_projects,
)
from utils.runtime_store import (
    append_audit_log,
    clear_branch_op_undo,
    delete_audit_logs,
    delete_profile,
    load_audit_logs,
    load_branch_op_undo,
    load_profiles,
    profile_summary,
    save_branch_op_undo,
    save_profile,
    suggest_profile_name,
)
gm.UNDO_FILE = str(UNDO_FILE)


STATE = {"busy": False, "lock": threading.Lock()}


def _commit_report(projects, start_date, end_date, authors=None):
    author_filter = set(a for a in (authors or []) if a)
    date_title = start_date if start_date == end_date else f"{start_date} 至 {end_date}"
    project_items = []
    all_authors = set()
    total = 0

    for conf in projects:
        name = conf.get("name") or conf.get("project_path") or conf.get("ssh_host") or "未命名工程"
        branch = (conf.get("source_branch") or "").strip()
        local_dir = (conf.get("local_dir") or "").strip()
        if not branch and local_dir and gm.is_git_repo(local_dir):
            proc = gm.run_git(["branch", "--show-current"], local_dir, check=False)
            branch = (proc.stdout or "").strip()
        if not branch:
            project_items.append({
                "name": name,
                "branch": "",
                "commits": [],
                "authors": [],
                "count": 0,
                "error": "缺少源分支",
            })
            continue
        try:
            commits = gm.list_commits_by_period(conf, branch, start_date, end_date)
            for c in commits:
                if c.get("author"):
                    all_authors.add(c["author"])
            if author_filter:
                commits = [c for c in commits if c.get("author") in author_filter]
            project_authors = sorted({c.get("author") for c in commits if c.get("author")})
            total += len(commits)
            project_items.append({
                "name": name,
                "branch": branch,
                "commits": commits,
                "authors": project_authors,
                "count": len(commits),
            })
        except Exception as e:
            project_items.append({
                "name": name,
                "branch": branch,
                "commits": [],
                "authors": [],
                "count": 0,
                "error": str(e),
            })

    lines = [f"# {date_title} 提交统计", "", "## 汇总",
             f"- 工程数：{len(project_items)}", f"- Commit 数：{total}"]
    if author_filter:
        lines.append(f"- 提交人：{', '.join(sorted(author_filter))}")
    lines.append("")

    by_author = {}
    for item in project_items:
        for c in item.get("commits") or []:
            by_author.setdefault(c.get("author") or "未知提交人", []).append({
                **c,
                "project": item["name"],
            })
    if by_author:
        lines.append("## 按提交人")
        for author in sorted(by_author):
            lines.append(f"- {author}（{len(by_author[author])}）")
            for c in by_author[author]:
                lines.append(f"  - [{c['project']}] {c['subject']}（{c['short']}）")
        lines.append("")

    lines.append("## 按工程")
    for item in project_items:
        title = f"### {item['name']}"
        if item.get("branch"):
            title += f"（{item['branch']}）"
        lines.append(title)
        if item.get("error"):
            lines.append(f"- 统计失败：{item['error']}")
        elif not item["commits"]:
            lines.append("- 无提交")
        else:
            grouped = {}
            for c in item["commits"]:
                grouped.setdefault(c.get("author") or "未知提交人", []).append(c)
            for author in sorted(grouped):
                lines.append(f"- {author}（{len(grouped[author])}）")
                for c in grouped[author]:
                    lines.append(f"  - {c['short']} {c['subject']}")
        lines.append("")

    return {
        "projects": project_items,
        "authors": sorted(all_authors),
        "total": total,
        "markdown": "\n".join(lines).strip() + "\n",
    }


# ---------------------------------------------------------------- 分支查询

def _gitlab_base_url(raw_url):
    """从 GitLab 页面/API 地址里提取站点根地址。"""
    raw = (raw_url or "").strip()
    if not raw:
        raise ValueError("请填写 GitLab 项目页地址")
    parsed = urlparse(raw if "://" in raw else "http://" + raw)
    if not parsed.netloc:
        raise ValueError("GitLab 地址格式不正确")
    return urlunparse((parsed.scheme or "http", parsed.netloc, "", "", "", "")).rstrip("/")


def _gitlab_request(base_url, api_path, token="", params=None, api_version="v4",
                    token_in_query=False, timeout=20):
    request_params = dict(params or {})
    if token and token_in_query:
        request_params["private_token"] = token
    query = urlencode(request_params)
    url = f"{base_url}/api/{api_version}{api_path}"
    if query:
        url += "?" + query
    headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 GitLabBranchMergeWeb/1.0",
        "Connection": "close",
    }
    if token and not token_in_query:
        headers["PRIVATE-TOKEN"] = token
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=timeout) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            data = json.loads(resp.read().decode(charset))
            next_page = resp.headers.get("X-Next-Page", "")
            return data, next_page
    except HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"GitLab API {api_version} {e.code}: {detail or e.reason}") from e
    except Exception:
        return _gitlab_request_curl(url, token, token_in_query, timeout)


def _gitlab_request_curl(url, token="", token_in_query=False, timeout=20):
    cmd = [
        "curl",
        "-sS",
        "--max-time", str(timeout),
        "-H", "Accept: application/json",
        "-H", "User-Agent: Mozilla/5.0 GitLabBranchMergeWeb/1.0",
    ]
    if token and not token_in_query:
        cmd.extend(["-H", f"PRIVATE-TOKEN: {token}"])
    cmd.append(url)
    proc = subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"curl 失败 [{proc.returncode}]")
    try:
        data = json.loads(proc.stdout or "null")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"GitLab API 返回非 JSON: {(proc.stdout or '')[:200]}") from e
    return data, ""


def _gitlab_paginated(base_url, api_path, token="", params=None, max_pages=20,
                      api_version="v4", token_in_query=False, timeout=20):
    out = []
    page = 1
    base_params = dict(params or {})
    while page and page <= max_pages:
        data, next_page = _gitlab_request(base_url, api_path, token, {
            **base_params,
            "page": page,
            "per_page": base_params.get("per_page") or 100,
        }, api_version=api_version, token_in_query=token_in_query, timeout=timeout)
        if isinstance(data, list):
            out.extend(data)
        else:
            raise RuntimeError("GitLab API 返回格式异常")
        page = int(next_page) if str(next_page).isdigit() else 0
    return out


def _gitlab_current_user(base_url, token, api_version="v4", token_in_query=False):
    data, _next_page = _gitlab_request(
        base_url, "/user", token, api_version=api_version,
        token_in_query=token_in_query)
    if not isinstance(data, dict) or not data.get("id"):
        raise RuntimeError("无法识别当前 GitLab 用户，请确认 Token 权限")
    return data


def _branch_names_from_gitlab(base_url, project_id, token, api_version="v4",
                              token_in_query=False):
    attempts = [
        (api_version, token_in_query),
        (api_version, not token_in_query),
        ("v3" if api_version == "v4" else "v4", token_in_query),
        ("v3" if api_version == "v4" else "v4", not token_in_query),
    ]
    errors = []
    for version, in_query in attempts:
        try:
            branches = _gitlab_paginated(
                base_url,
                f"/projects/{quote(str(project_id), safe='')}/repository/branches",
                token,
                {"per_page": 100},
                max_pages=30,
                api_version=version,
                token_in_query=in_query,
                timeout=6,
            )
            names = sorted(b.get("name") for b in branches if isinstance(b, dict) and b.get("name"))
            if names:
                return names
        except Exception as e:
            errors.append(f"{version} {'query' if in_query else 'header'}: {e}")
    raise RuntimeError("；".join(errors) or "GitLab 未返回分支")


def _gitlab_project_params():
    return {
        "order_by": "last_activity_at",
        "sort": "desc",
        "per_page": 100,
    }


def _dedupe_gitlab_projects(projects):
    seen = set()
    out = []
    for p in projects:
        if not isinstance(p, dict):
            continue
        key = p.get("id") or p.get("path_with_namespace") or p.get("ssh_url_to_repo")
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def _fetch_gitlab_projects_v4(base_url, token, scope, token_in_query=False):
    params = _gitlab_project_params()
    if scope == "membership":
        user = _gitlab_current_user(
            base_url, token, api_version="v4", token_in_query=token_in_query)
        candidates = [
            (f"/users/{quote(str(user['id']), safe='')}/projects", params),
            ("/projects", {**params, "membership": "true"}),
            ("/projects", {**params, "owned": "true"}),
        ]
        projects = []
        for api_path, api_params in candidates:
            projects.extend(_gitlab_paginated(
                base_url,
                api_path,
                token,
                api_params,
                max_pages=30,
                api_version="v4",
                token_in_query=token_in_query,
            ))
        return _dedupe_gitlab_projects(projects), "v4", token_in_query
    return _gitlab_paginated(
        base_url,
        "/projects",
        token,
        params,
        max_pages=30,
        api_version="v4",
        token_in_query=token_in_query,
    ), "v4", token_in_query


def _fetch_gitlab_projects_v3(base_url, token, scope, token_in_query=False):
    params = _gitlab_project_params()
    if scope == "membership":
        projects = []
        for api_path in ("/projects", "/projects/owned", "/projects/all"):
            try:
                projects.extend(_gitlab_paginated(
                    base_url,
                    api_path,
                    token,
                    params,
                    max_pages=30,
                    api_version="v3",
                    token_in_query=token_in_query,
                ))
            except Exception:
                if api_path == "/projects":
                    raise
        return _dedupe_gitlab_projects(projects), "v3", token_in_query
    return _gitlab_paginated(
        base_url,
        "/projects/all",
        token,
        params,
        max_pages=30,
        api_version="v3",
        token_in_query=token_in_query,
    ), "v3", token_in_query


def fetch_gitlab_projects(page_url, token="", include_branches=True, scope="membership"):
    """通过 GitLab API 获取可访问的项目及分支。"""
    base_url = _gitlab_base_url(page_url)
    scope = scope if scope in ("membership", "all") else "membership"
    if scope == "membership" and not token:
        raise ValueError("同步「Your projects」需要填写 GitLab Private Token（read_api 权限）")
    warnings = []
    projects = []
    api_version = "v4"
    token_in_query = False
    attempts = (
        ("v4 header", lambda: _fetch_gitlab_projects_v4(base_url, token, scope, False)),
        ("v4 query", lambda: _fetch_gitlab_projects_v4(base_url, token, scope, True)),
        ("v3 header", lambda: _fetch_gitlab_projects_v3(base_url, token, scope, False)),
        ("v3 query", lambda: _fetch_gitlab_projects_v3(base_url, token, scope, True)),
    )
    attempt_counts = []
    for label, fn in attempts:
        try:
            projects, api_version, token_in_query = fn()
            attempt_counts.append(f"{label}: {len(projects)}")
            if projects:
                if label != "v4 header":
                    warnings.append(f"已使用 {label} 读取 GitLab 工程")
                break
        except Exception as e:
            attempt_counts.append(f"{label}: 失败")
            warnings.append(f"{label} 读取失败：{e}")
    if not projects:
        warnings.append("所有 GitLab 项目接口均返回 0，尝试结果：" + "；".join(attempt_counts))
    should_fetch_branches = include_branches and len(projects) <= 20
    if include_branches and len(projects) > 20:
        warnings.append(f"已获取 {len(projects)} 个工程；为避免请求过久，已跳过批量分支同步，加入工程后会按单工程加载分支")
    out = []
    for p in projects:
        if not isinstance(p, dict):
            continue
        project_id = p.get("id")
        path = p.get("path_with_namespace") or p.get("path") or ""
        item = {
            "id": project_id,
            "name": p.get("name") or p.get("path") or path,
            "ssh_host": p.get("ssh_url_to_repo") or "",
            "http_url": p.get("http_url_to_repo") or p.get("web_url") or "",
            "web_url": p.get("web_url") or "",
            "project_path": path,
            "path": path,
            "branches": [],
            "gitlab_api_version": api_version,
            "gitlab_token_in_query": token_in_query,
        }
        if should_fetch_branches and project_id:
            try:
                item["branches"] = _branch_names_from_gitlab(
                    base_url, project_id, token, api_version, token_in_query)
            except Exception as e:
                warnings.append(f"{path or item['name']} 分支读取失败：{e}")
        out.append(item)
    return out, warnings


def diagnose_gitlab_projects(page_url, token=""):
    """返回 GitLab 项目同步的关键诊断信息，不回显 Token。"""
    base_url = _gitlab_base_url(page_url)
    result = {"base_url": base_url, "user": None, "checks": []}

    def add_check(name, fn):
        try:
            value = fn()
            result["checks"].append({"name": name, "ok": True, **value})
        except Exception as e:
            result["checks"].append({"name": name, "ok": False, "error": str(e)})

    if token:
        add_check("v4_version", lambda: {
            "version": _gitlab_request(base_url, "/version", token, api_version="v4")[0].get("version", "")
        })
        add_check("v3_version", lambda: {
            "version": _gitlab_request(base_url, "/version", token, api_version="v3", token_in_query=True)[0].get("version", "")
        })
        add_check("current_user", lambda: {
            "user": _gitlab_current_user(base_url, token, api_version="v4"),
        })
        user_check = next((c for c in result["checks"] if c["name"] == "current_user" and c["ok"]), None)
        if user_check:
            result["user"] = user_check.get("user")
            uid = result["user"].get("id")
            add_check("v4_users_id_projects", lambda: {
                "count": len(_gitlab_paginated(
                    base_url,
                    f"/users/{quote(str(uid), safe='')}/projects",
                    token,
                    {"order_by": "last_activity_at", "sort": "desc", "per_page": 100},
                    max_pages=30,
                    api_version="v4",
                ))
            })
        add_check("v4_membership_projects", lambda: {
            "count": len(_gitlab_paginated(
                base_url,
                "/projects",
                token,
                {"membership": "true", "order_by": "last_activity_at", "sort": "desc", "per_page": 100},
                max_pages=30,
                api_version="v4",
            ))
        })
        add_check("v3_current_user", lambda: {
            "user": _gitlab_current_user(base_url, token, api_version="v3"),
        })
        add_check("v3_projects", lambda: {
            "count": len(_gitlab_paginated(
                base_url,
                "/projects",
                token,
                {"order_by": "last_activity_at", "sort": "desc", "per_page": 100},
                max_pages=30,
                api_version="v3",
            ))
        })
        add_check("v3_query_projects", lambda: {
            "count": len(_gitlab_paginated(
                base_url,
                "/projects",
                token,
                {"order_by": "last_activity_at", "sort": "desc", "per_page": 100},
                max_pages=30,
                api_version="v3",
                token_in_query=True,
            ))
        })
        add_check("v3_owned_projects", lambda: {
            "count": len(_gitlab_paginated(
                base_url,
                "/projects/owned",
                token,
                {"order_by": "last_activity_at", "sort": "desc", "per_page": 100},
                max_pages=30,
                api_version="v3",
                token_in_query=True,
            ))
        })
        add_check("v3_all_projects", lambda: {
            "count": len(_gitlab_paginated(
                base_url,
                "/projects/all",
                token,
                {"order_by": "last_activity_at", "sort": "desc", "per_page": 100},
                max_pages=30,
                api_version="v3",
                token_in_query=True,
            ))
        })
    add_check("v4_visible_projects", lambda: {
        "count": len(_gitlab_paginated(
            base_url,
            "/projects",
            token,
            {"order_by": "last_activity_at", "sort": "desc", "per_page": 100},
            max_pages=30,
            api_version="v4",
        ))
    })
    return result


def fetch_branches(host, info=None):
    """获取远程仓库的全部分支（git ls-remote --heads）。

    info 可含 project_path、local_dir、ssh_port：
    - 若提供了 local_dir 且是本地仓库，优先用本地仓库读取 origin url，
      无需网络即可快速返回（并且与合并时使用的仓库一致）；
    - 否则走 build_remote_url 构造地址 + ls-remote 远程查询。
    返回排序后的分支名列表（含 HEAD 分支）。
    """
    info = info or {}
    gitlab_token = (info.get("gitlab_token") or "").strip()
    gitlab_url = (info.get("gitlab_url") or "").strip()
    gitlab_project_id = info.get("gitlab_project_id")
    gitlab_api_version = (info.get("gitlab_api_version") or "v4").strip()
    gitlab_token_in_query = bool(info.get("gitlab_token_in_query"))
    if gitlab_token and gitlab_url and gitlab_project_id:
        return _branch_names_from_gitlab(
            _gitlab_base_url(gitlab_url),
            gitlab_project_id,
            gitlab_token,
            gitlab_api_version,
            gitlab_token_in_query,
        )
    global_cfg = info.get("global") if isinstance(info.get("global"), dict) else None
    host = resolve_config_vars(host, global_cfg)
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
    ".di-cache",
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
        # 开发期优先保证每次重启/刷新都拿到最新资源
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(data)

    def _serve_index_file(self, path):
        index_path = Path(path)
        try:
            text = index_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            self.send_error(404)
            return
        dist_root = BASE_DIR / "dist"

        def version_asset(match):
            quote_char, asset_path = match.group(1), match.group(2)
            clean_path = asset_path.split("?", 1)[0]
            asset_file = (dist_root / clean_path.lstrip("/")).resolve()
            try:
                asset_file.relative_to(dist_root.resolve())
                version = str(int(asset_file.stat().st_mtime))
            except Exception:
                version = str(int(index_path.stat().st_mtime))
            return f'{quote_char}{html.escape(clean_path)}?v={version}{quote_char}'

        text = re.sub(r'(["\'])(/assets/[^"\']+\.(?:js|css))(?:\?[^"\']*)?\1', version_asset, text)
        data = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
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
                self._serve_index_file(dist_root / "index.html")
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

    def _serve_dist_index(self):
        dist_index = BASE_DIR / "dist" / "index.html"
        if dist_index.is_file():
            self._serve_index_file(dist_index)
            return True
        return False

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
        elif path == "/api/commit/report/ping":
            self._send_json({"ok": True, "feature": "commit-report"})
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
            if "." not in Path(path).name and self._serve_dist_index():
                return
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        body = self._read_body()
        request_global = body.get("global") if isinstance(body.get("global"), dict) else None
        if parsed.path == "/api/branches":
            host = (body.get("ssh_host") or "").strip()
            has_gitlab_api = bool(body.get("gitlab_token") and body.get("gitlab_url") and body.get("gitlab_project_id"))
            local_dir = (body.get("local_dir") or "").strip()
            has_local_repo = bool(local_dir and gm.is_git_repo(local_dir))
            if not host and not has_gitlab_api and not has_local_repo:
                self._send_json({"ok": False, "error": "请先填写 SSH 地址或使用远程 GitLab 工程"}, code=400)
                return
            try:
                branches = fetch_branches(host, body)
                current_branch = ""
                local_dir = (body.get("local_dir") or "").strip()
                if local_dir and gm.is_git_repo(local_dir):
                    current_proc = gm.run_git(
                        ["rev-parse", "--abbrev-ref", "HEAD"],
                        local_dir,
                        check=False,
                    )
                    if current_proc.returncode == 0:
                        current_branch = current_proc.stdout.strip()
                self._send_json({
                    "ok": True,
                    "branches": branches,
                    "current_branch": current_branch,
                })
            except Exception as e:
                self._send_json({"ok": False, "error": f"获取分支失败: {e}"}, code=400)
        elif parsed.path == "/api/branch/create":
            projects = normalize_projects(body.get("projects", []), global_cfg=request_global)
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
            projects = normalize_projects(body.get("projects", []), global_cfg=request_global)
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
            projects = normalize_projects(body.get("projects", []), global_cfg=request_global)
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
        elif parsed.path == "/api/branch/switch-local":
            projects = normalize_projects(body.get("projects", []), global_cfg=request_global)
            fallback_branch = (body.get("branch_name") or "").strip()
            if not projects:
                self._send_json({"ok": False, "error": "请至少选择一个工程"}, code=400)
                return
            results = []
            for p in projects:
                branch_name = (p.get("switch_branch") or fallback_branch).strip()
                if not branch_name:
                    results.append({
                        "name": p["name"],
                        "ok": False,
                        "error": "请选择要切换的分支",
                        "commands": [],
                    })
                    continue
                try:
                    ok, msg, commands, meta = gm.switch_local_branch(p, branch_name)
                    results.append({
                        "name": p["name"],
                        "ok": True,
                        "message": msg,
                        "commands": commands,
                        "branch_name": meta.get("branch_name", branch_name),
                    })
                except Exception as e:
                    results.append({
                        "name": p["name"],
                        "ok": False,
                        "error": str(e),
                        "commands": getattr(e, "commands", []),
                    })
            self._send_json({"ok": True, "action": "switch-local",
                             "results": results})
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
        elif parsed.path == "/api/gitlab/projects":
            url = (body.get("url") or "").strip()
            token = (body.get("token") or "").strip()
            include_branches = body.get("include_branches") is not False
            scope = (body.get("scope") or "membership").strip()
            if not url:
                self._send_json({"ok": False, "error": "请填写 GitLab 项目页地址"}, code=400)
                return
            try:
                projects, warnings = fetch_gitlab_projects(url, token, include_branches, scope)
                self._send_json({"ok": True, "url": url,
                                 "projects": projects, "warnings": warnings})
            except Exception as e:
                self._send_json({"ok": False, "error": f"获取 GitLab 项目失败: {e}"}, code=400)
        elif parsed.path == "/api/gitlab/diagnose":
            url = (body.get("url") or "").strip()
            token = (body.get("token") or "").strip()
            if not url:
                self._send_json({"ok": False, "error": "请填写 GitLab 项目页地址"}, code=400)
                return
            try:
                self._send_json({"ok": True, **diagnose_gitlab_projects(url, token)})
            except Exception as e:
                self._send_json({"ok": False, "error": f"GitLab 诊断失败: {e}"}, code=400)
        elif parsed.path == "/api/project/pull":
            if STATE["busy"]:
                self._send_json({"ok": False, "error": "任务运行中，暂不能拉取项目"}, code=409)
                return
            host = (body.get("ssh_host") or "").strip()
            local_dir = (body.get("local_dir") or "").strip()
            if not host:
                self._send_json({"ok": False, "error": "请先填写 SSH 地址"}, code=400)
                return
            if not local_dir:
                self._send_json({"ok": False, "error": "请填写本地目录"}, code=400)
                return
            try:
                conf = normalize_projects([{**body, "local_dir": local_dir}],
                                          global_cfg=request_global)[0]
                repo_dir = project_repo_dir(local_dir, conf)
                conf["local_dir"] = repo_dir
                if Path(repo_dir).exists():
                    self._send_json({
                        "ok": False,
                        "error": f"目标目录已存在相同工程，不能拉取：{repo_dir}",
                    }, code=409)
                    return
                pulled_dir = gm.ensure_repo(conf, check_branches=False)
                branches = fetch_branches(host, {**body, "local_dir": pulled_dir})
                self._send_json({"ok": True, "local_dir": pulled_dir,
                                 "branches": branches})
            except SystemExit as e:
                self._send_json({"ok": False, "error": str(e)}, code=400)
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, code=400)
        elif parsed.path == "/api/save":
            global_cfg = request_global
            projects = normalize_projects(body.get("projects", []),
                                          resolve_vars=False,
                                          global_cfg=global_cfg)
            save_projects(projects)
            if global_cfg is not None:
                save_global(global_cfg)
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
            global_cfg = request_global
            projects = normalize_projects(body.get("projects", []),
                                          resolve_vars=False,
                                          global_cfg=global_cfg)
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
            global_cfg = entry.get("global") if isinstance(entry.get("global"), dict) else None
            projects = normalize_projects(entry.get("projects", []),
                                          resolve_vars=False,
                                          global_cfg=global_cfg)
            save_projects(projects)
            if global_cfg is not None:
                save_global(global_cfg)
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
                conf = normalize_projects([body], global_cfg=request_global)[0]
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
        elif parsed.path == "/api/commit/report":
            report_date = (body.get("date") or "").strip()
            start_date = (body.get("start_date") or report_date).strip()
            end_date = (body.get("end_date") or report_date).strip()
            if (not re.match(r"^\d{4}-\d{2}-\d{2}$", start_date) or
                    not re.match(r"^\d{4}-\d{2}-\d{2}$", end_date)):
                self._send_json({"ok": False, "error": "请选择统计期间"}, code=400)
                return
            if start_date > end_date:
                start_date, end_date = end_date, start_date
            authors = body.get("authors") or []
            if isinstance(authors, str):
                authors = [a.strip() for a in authors.split(",") if a.strip()]
            projects = normalize_projects(body.get("projects", []), global_cfg=request_global)
            if not projects:
                self._send_json({"ok": False, "error": "请选择至少一个工程"}, code=400)
                return
            try:
                data = _commit_report(projects, start_date, end_date, authors)
                self._send_json({"ok": True, "date": start_date,
                                 "start_date": start_date,
                                 "end_date": end_date, **data})
            except Exception as e:
                self._send_json({"ok": False, "error": f"生成统计失败: {e}"}, code=400)
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
                conf = normalize_projects([body], global_cfg=request_global)[0]
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
            projects = normalize_projects(body.get("projects", []), global_cfg=request_global)
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
