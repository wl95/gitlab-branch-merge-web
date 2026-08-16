#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitLab 多项目分支批量合并脚本

功能：
  1. 从 config.ini 读取多个项目的配置（每个项目可独立指定 SSH 地址、项目路径、
     源分支与目标分支列表）
  2. 对每个项目 clone（或更新）本地仓库
  3. 将各项目的源分支(分支1) 依次 merge 到指定的目标分支(分支2、3、4...)
  4. 合并成功后自动推送到远程，冲突时按配置处理

用法：
  python3 gitlab_merge.py                 # 使用默认 config.ini
  python3 gitlab_merge.py myconf.ini      # 指定配置文件
  python3 gitlab_merge.py config.ini --dry-run   # 演练模式，不执行任何改动
"""

import argparse
import configparser
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------- 基础工具

# SSH 非交互加固：自动接受首次主机密钥、连接超时、禁止交互输入密码，
# 避免 git 通过 SSH 时卡在 "yes/no" 或密码提示上。
SSH_OPTS = [
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "ConnectTimeout=15",
    "-o", "BatchMode=yes",
    "-o", "LogLevel=ERROR",
]

_GIT_ENV = dict(os.environ)
_GIT_ENV["GIT_SSH_COMMAND"] = "ssh " + " ".join(SSH_OPTS)
_GIT_ENV["GIT_TERMINAL_PROMPT"] = "0"
# clone 后自动切换分支时直接跟随远程分支（避免 Git 2.36+ 的提示）
_GIT_ENV.setdefault("GIT_EDITOR", "true")


class BranchCommandError(RuntimeError):
    def __init__(self, message, commands=None):
        super().__init__(message)
        self.commands = commands or []


def format_git_command(args, cwd):
    return " ".join(["git", "-C", str(cwd)] + [str(a) for a in args])


def run_git(args, cwd, check=True, timeout=None):
    """执行一条 git 命令，返回 CompletedProcess。

    使用 `git -C <cwd>` 形式而非 subprocess.run(cwd=...)，
    避免 macOS TCC / sandbox 在切换 cwd 时拒绝跨目录访问。
    timeout: 超时秒数；超时后抛 RuntimeError（适合网络类命令，防挂起）。
    """
    cmd = ["git", "-C", str(cwd)] + args
    logging.info("执行命令: %s", " ".join(cmd))
    try:
        proc = subprocess.run(
            cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=_GIT_ENV,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"命令执行超时(>{timeout}s): {' '.join(cmd)}\n{e}"
        )
    if proc.returncode != 0 and check:
        raise RuntimeError(
            f"命令执行失败 [{proc.returncode}]: {' '.join(cmd)}\n{proc.stdout}"
        )
    return proc


def is_git_repo(path):
    """判断目录是否已是 git 仓库。"""
    return (Path(path) / ".git").exists() or (
        Path(path) / ".git").is_file()


# ---------------------------------------------------------------- 配置加载

def _b(config, section, key, default, converter=str):
    """安全读取配置项（section 不存在或 key 缺失时返回默认值）。"""
    if not config.has_section(section):
        return default
    try:
        if not config.get(section, key, fallback=""):
            return default
        if converter is bool:
            return config.getboolean(section, key)
        if converter is int:
            return config.getint(section, key)
        return converter(config.get(section, key).strip())
    except (configparser.Error, ValueError):
        logging.warning("配置 [%s] %s 格式错误，使用默认值 %s", section, key, default)
        return default


def load_config(config_path):
    """
    加载并校验配置文件。
    返回 {"default": {...}, "projects": [ {...}, ... ]}
    兼容旧格式：若存在 [gitlab] 且无 [project:xxx] 段，则视为单项目。
    """
    if not os.path.exists(config_path):
        logging.error("配置文件不存在: %s", config_path)
        sys.exit(1)

    cfg = configparser.ConfigParser()
    cfg.read(config_path, encoding="utf-8")

    default = {
        "ssh_port": _b(cfg, "default", "ssh_port", 22, int),
        "local_dir_base": _b(cfg, "default", "local_dir_base", "./repos", str),
        "remote": _b(cfg, "default", "remote", "origin", str),
        "no_ff": _b(cfg, "default", "no_ff", True, bool),
        "push_on_success": _b(cfg, "default", "push_on_success", True, bool),
        "stop_on_conflict": _b(cfg, "default", "stop_on_conflict", True, bool),
        "log_level": _b(cfg, "default", "log_level", "INFO", str).upper(),
    }

    projects = []
    for section in cfg.sections():
        if not section.lower().startswith("project"):
            continue

        proj = dict(default)
        proj["name"] = section.split(":", 1)[1].strip() if ":" in section else section
        proj["ssh_host"] = _b(cfg, section, "ssh_host", "", str)
        proj["project_path"] = _b(cfg, section, "project_path", "", str).strip("/")
        proj["source_branch"] = _b(cfg, section, "source_branch", "", str)
        proj["local_dir"] = _b(cfg, section, "local_dir", "", str)
        proj["target_branches"] = [
            b.strip()
            for b in cfg.get(section, "target_branches", fallback="").split(",")
            if b.strip()
        ]

        # 各项目内可覆盖默认开关
        proj["no_ff"] = _b(cfg, section, "no_ff", proj["no_ff"], bool)
        proj["push_on_success"] = _b(cfg, section, "push_on_success",
                                     proj["push_on_success"], bool)
        proj["stop_on_conflict"] = _b(cfg, section, "stop_on_conflict",
                                      proj["stop_on_conflict"], bool)
        proj["remote"] = _b(cfg, section, "remote", proj["remote"], str)
        proj["ssh_port"] = _b(cfg, section, "ssh_port", proj["ssh_port"], int)

        errors = []
        if not proj["ssh_host"]:
            errors.append("ssh_host")
        elif not _is_full_url(proj["ssh_host"]) and not proj["project_path"]:
            errors.append("project_path（ssh_host 未写完整地址时必须填写）")
        if not proj["source_branch"]:
            errors.append("source_branch")
        if not proj["target_branches"]:
            errors.append("target_branches")
        if errors:
            logging.error("项目 [%s] 缺少配置项: %s", proj["name"], ", ".join(errors))
            sys.exit(1)

        # 未指定 local_dir 时自动生成：local_dir_base/<路径部分斜杠替换为下划线>
        if not proj["local_dir"]:
            dir_part = (proj["project_path"]
                        or extract_path_from_url(proj["ssh_host"])
                        or proj["name"])
            proj["local_dir"] = os.path.join(
                proj["local_dir_base"], dir_part.replace("/", "__")
            )
        projects.append(proj)

    # 兼容旧单项目格式：[gitlab] + [merge]
    if not projects and cfg.has_section("gitlab"):
        logging.warning("检测到旧格式配置，按单项目模式处理")
        proj = dict(default)
        proj["name"] = cfg.get("gitlab", "project_path", fallback="default")
        proj["ssh_host"] = cfg.get("gitlab", "ssh_host", fallback="").strip()
        proj["project_path"] = cfg.get("gitlab", "project_path", fallback="").strip("/")
        proj["ssh_port"] = _b(cfg, "gitlab", "ssh_port", proj["ssh_port"], int)
        proj["source_branch"] = cfg.get("merge", "source_branch", fallback="").strip()
        proj["target_branches"] = [
            b.strip() for b in cfg.get("merge", "target_branches", fallback="").split(",")
            if b.strip()
        ]
        proj["no_ff"] = _b(cfg, "merge", "no_ff", proj["no_ff"], bool)
        proj["push_on_success"] = _b(cfg, "merge", "push_on_success",
                                     proj["push_on_success"], bool)
        proj["stop_on_conflict"] = _b(cfg, "merge", "stop_on_conflict",
                                      proj["stop_on_conflict"], bool)
        proj["local_dir"] = cfg.get("repository", "local_dir", fallback="").strip()
        proj["remote"] = _b(cfg, "repository", "remote", proj["remote"], str)
        if not proj["local_dir"]:
            dir_part = (proj["project_path"]
                        or extract_path_from_url(proj["ssh_host"])
                        or proj["name"])
            proj["local_dir"] = os.path.join(
                proj["local_dir_base"], dir_part.replace("/", "__")
            )
        proj["log_level"] = _b(cfg, "options", "log_level", proj["log_level"], str).upper()
        projects.append(proj)

    if not projects:
        logging.error("配置文件中没有找到任何 [project:xxx] 项目段")
        sys.exit(1)

    return default, projects


def _is_full_url(host):
    """判断 ssh_host 是否已是完整地址（含仓库路径）。"""
    if "://" in host:
        return True
    if ":" in host:
        rest = host.split(":", 1)[1]
        # scp 风格: user@host:group/project(.git)，冒号后含非纯数字即视为完整地址
        return bool(rest) and not rest.isdigit()
    return False


def extract_path_from_url(host):
    """从完整 SSH 地址中提取 组/项目 路径，用于生成本地目录名。"""
    if "://" in host:
        # ssh://git@host:port/group/project.git
        rest = host.split("://", 1)[1]
        rest = rest.split("/", 1)[1] if "/" in rest else ""
    elif ":" in host:
        rest = host.split(":", 1)[1]  # scp 风格
    else:
        rest = ""
    return rest.replace(".git", "").strip("/")


def build_remote_url(conf):
    """
    构造 Git SSH 地址。
    若 ssh_host 已是完整地址（如 git@host:group/project.git 或 ssh://...），
    直接使用，此时可省略 project_path；
    否则按 ssh_host + project_path 拼接。
    """
    host = conf["ssh_host"]
    if _is_full_url(host):
        return host if host.endswith(".git") else host + ".git"
    path = conf["project_path"].strip("/") + ".git"
    if conf["ssh_port"] and int(conf["ssh_port"]) != 22:
        return f"ssh://{host}:{conf['ssh_port']}/{path}"
    return f"{host}:{path}"


def repo_dir_name(conf):
    """根据项目配置推导本地仓库目录名。"""
    path_part = (
        (conf.get("project_path") or "").strip("/")
        or extract_path_from_url(conf.get("ssh_host") or "")
        or (conf.get("name") or "").strip()
        or "repo"
    )
    return (path_part.rstrip("/").split("/")[-1] or "repo").replace(".git", "")


# ---------------------------------------------------------------- 仓库操作

def ensure_repo(conf, check_branches=True):
    """确保本地仓库存在且处于最新状态，返回本地目录路径。"""
    local_dir = Path(conf["local_dir"]).expanduser().resolve()
    remote_url = build_remote_url(conf)

    if is_git_repo(local_dir):
        logging.info("本地仓库已存在，拉取远程更新: %s", local_dir)
        run_git(["remote", "set-url", conf["remote"], remote_url], str(local_dir))
        run_git(["fetch", "--prune", "--tags", conf["remote"]], str(local_dir))
    else:
        if local_dir.is_dir() and any(local_dir.iterdir()):
            parent_dir = local_dir
            local_dir = parent_dir / repo_dir_name(conf)
            conf["local_dir"] = str(local_dir)
            logging.info("拉取目录非空，按父目录处理: %s -> %s", parent_dir, local_dir)

        if is_git_repo(local_dir):
            logging.info("本地仓库已存在，拉取远程更新: %s", local_dir)
            run_git(["remote", "set-url", conf["remote"], remote_url], str(local_dir))
            run_git(["fetch", "--prune", "--tags", conf["remote"]], str(local_dir))
        else:
            logging.info("本地仓库不存在，开始 clone: %s", remote_url)
            local_dir.parent.mkdir(parents=True, exist_ok=True)
            # 网络抖动时重试一次，失败则清理残留目录并保留错误信息
            last_err = None
            for attempt in (1, 2):
                try:
                    run_git(["clone", "--no-single-branch", remote_url, str(local_dir)],
                            str(local_dir.parent))
                    last_err = None
                    break
                except SystemExit as e:
                    last_err = e
                    logging.warning("clone 第 %d 次失败（%s），稍后重试...", attempt, e)
                    if local_dir.exists():
                        import shutil
                        shutil.rmtree(local_dir, ignore_errors=True)
            if last_err is not None:
                raise SystemExit(f"clone 失败: {last_err}\n"
                                 f"请检查网络/SSH 密钥，或确认目录已存在本地仓库可直接复用")
            run_git(["fetch", "--prune", "--tags", conf["remote"]], str(local_dir))

    # 仅用于查看 commit / cherry-pick 时跳过分支校验
    if not check_branches:
        return str(local_dir)

    # 校验源分支存在于远程
    proc = run_git(
        ["ls-remote", "--heads", conf["remote"],
         f"refs/heads/{conf['source_branch']}"],
        str(local_dir),
    )
    if conf["source_branch"] not in proc.stdout:
        logging.error("[%s] 远程不存在源分支: %s", conf["name"], conf["source_branch"])
        sys.exit(1)

    # 校验所有目标分支存在于远程
    remote_heads = run_git(
        ["ls-remote", "--heads", conf["remote"]], str(local_dir)
    ).stdout
    missing = [b for b in conf["target_branches"]
               if f"refs/heads/{b}" not in remote_heads]
    if missing:
        logging.error("[%s] 远程不存在目标分支: %s", conf["name"], ", ".join(missing))
        sys.exit(1)

    return str(local_dir)


def checkout_target(remote, branch, local_dir):
    """切换到目标分支并与远程保持同步（本地有改动则拒绝继续）。"""
    status = run_git(["status", "--porcelain"], local_dir).stdout.strip()
    if status:
        logging.warning("工作区有未提交改动，先清理后再继续:\n%s", status)
        return False

    has_local = run_git(
        ["show-ref", "--verify", "--quiet",
         f"refs/heads/{branch}"], local_dir, check=False
    ).returncode == 0

    if has_local:
        run_git(["checkout", branch], local_dir)
    else:
        run_git(["checkout", "-b", branch, f"{remote}/{branch}"], local_dir)

    # 与远程目标分支强制对齐，保证合并基础干净
    run_git(["reset", "--hard", f"{remote}/{branch}"], local_dir)
    return True


def merge_branch(remote, source, target, conf, local_dir, dry_run):
    """把源分支合并到单个目标分支。

    返回 (ok, before_sha, after_sha)：
      - ok: 是否成功
      - before_sha: 合并前 HEAD（即 origin/<target> 的 SHA，用于撤回）
      - after_sha: 合并提交后 HEAD（未实际合并时为 None）
    """
    logging.info("=" * 60)
    logging.info("[%s] 合并: %s  ->  %s", conf["name"], source, target)
    logging.info("=" * 60)

    if not checkout_target(remote, target, local_dir):
        logging.error("[%s] 目标分支 %s 工作区不干净，跳过", conf["name"], target)
        return False, None, None

    # 合并前快照：checkout_target 已 reset --hard 到 origin/<target>
    before_sha = run_git(["rev-parse", "HEAD"], local_dir).stdout.strip()

    # 合并源分支（使用远程引用，保证最新）
    src_ref = f"{remote}/{source}"
    merge_args = ["merge"]
    if conf["no_ff"]:
        merge_args.append("--no-ff")
    merge_args += [
        src_ref,
        "-m", f"Merge branch '{source}' into {target}",
    ]

    if dry_run:
        logging.info("[演练] 将执行: git %s", " ".join(merge_args))
        return True, None, None

    logging.info("执行命令: %s", format_git_command(merge_args, local_dir))
    proc = run_git(merge_args, local_dir, check=False)
    if proc.returncode != 0:
        if "CONFLICT" in proc.stdout:
            logging.error("[%s] 合并冲突:\n%s", conf["name"], proc.stdout)
            logging.info("执行命令: %s", format_git_command(["merge", "--abort"], local_dir))
            run_git(["merge", "--abort"], local_dir, check=False)
            logging.info("已执行 git merge --abort 回滚")
        else:
            logging.error("[%s] 合并失败:\n%s", conf["name"], proc.stdout)
            logging.info("执行命令: %s", format_git_command(["merge", "--abort"], local_dir))
            run_git(["merge", "--abort"], local_dir, check=False)
        return False, before_sha, None

    after_sha = run_git(["rev-parse", "HEAD"], local_dir).stdout.strip()
    logging.info("[%s] 合并成功: %s", conf["name"], target)

    if conf["push_on_success"]:
        if dry_run:
            logging.info("[演练] 将执行: git push %s %s", remote, target)
            return True, before_sha, after_sha
        logging.info("执行命令: %s", format_git_command(["push", remote, target], local_dir))
        push = run_git(["push", remote, target], local_dir, check=False)
        if push.returncode != 0:
            logging.error("[%s] 推送失败:\n%s", conf["name"], push.stdout)
            return False, before_sha, after_sha
        logging.info("[%s] 已推送: %s -> %s/%s", conf["name"], target, remote, target)

    return True, before_sha, after_sha


def process_project(conf, dry_run):
    """处理单个项目，返回 (是否全部成功, 可撤回记录列表)。"""
    logging.info("### 开始处理项目 [%s]  %s", conf["name"], build_remote_url(conf))
    logging.info("    源分支: %s", conf["source_branch"])
    logging.info("    目标分支: %s", ", ".join(conf["target_branches"]))

    local_dir = ensure_repo(conf)
    undo_items = []
    ok_all = True

    for target in conf["target_branches"]:
        ok, before, after = merge_branch(conf["remote"], conf["source_branch"],
                                         target, conf, local_dir, dry_run)
        if not ok:
            ok_all = False
            logging.error("[%s] 在目标分支 %s 处失败", conf["name"], target)
            if conf["stop_on_conflict"]:
                logging.error("[%s] stop_on_conflict=true，停止该项目的后续合并（继续下一个项目）",
                              conf["name"])
                return False, undo_items
            logging.warning("[%s] stop_on_conflict=false，跳过 %s 继续", conf["name"], target)
            continue
        # 合并成功且产生了新提交：记录快照，供「撤回合并」使用
        if after and after != before:
            undo_items.append({
                "name": conf["name"],
                "local_dir": local_dir,
                "remote": conf["remote"],
                "branch": target,
                "before_sha": before,
                "after_sha": after,
                "source_branch": conf["source_branch"],
            })
    return ok_all, undo_items


def list_merged_commits(item):
    """解析一个 undo item 在 (before, after) 之间产生的 commit 列表。

    返回 [{sha, short, author, date, subject}, ...]，按 git 默认从新到旧排列。
    若因工作区状态（如正在另一个仓库上、或 detached HEAD）等无法解析，
    回退为通过 fetch 拿取或直接返回空列表（绝不抛错）。
    """
    before = item.get("before_sha") or ""
    after = item.get("after_sha") or ""
    local_dir = item.get("local_dir") or ""
    branch = item.get("branch") or ""

    def _parse_log(out):
        commits = []
        for line in out.splitlines():
            parts = line.split("\t", 3)
            if len(parts) != 4:
                continue
            sha, author, date, subject = parts
            commits.append({
                "sha": sha,
                "short": sha[:8],
                "author": author,
                "date": date,
                "subject": subject,
            })
        return commits

    if not (before and after and local_dir and Path(local_dir).exists() and is_git_repo(local_dir)):
        return []

    fmt = "%H%x09%an%x09%ad%x09%s"
    # 1）直接查 before..after（要求仓库 HEAD 看到 after 这两个 SHA）
    proc = run_git(
        ["log", f"{before}..{after}", f"--pretty=format:{fmt}", "--date=short"],
        local_dir, check=False,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return _parse_log(proc.stdout)

    # 2）回退：拿远端更新后再查
    if branch:
        try:
            run_git(["fetch", "--all", "--prune"], local_dir, check=False)
        except Exception:
            pass
        proc = run_git(
            ["log", f"{before}..{after}", f"--pretty=format:{fmt}", "--date=short"],
            local_dir, check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return _parse_log(proc.stdout)

    return []


# ---------------------------------------------------------------- 批量分支管理

# 受保护分支：禁止删除 / 重命名，防止误操作主干分支
PROTECTED_BRANCHES = {
    "master", "main", "develop", "dev",
    "release", "production", "prod", "test",
}


def _validate_branch_name(name):
    """校验分支名是否合法（git check-ref-format --branch）。非法则抛错。"""
    name = (name or "").strip()
    if not name:
        raise RuntimeError("分支名不能为空")
    proc = run_git(["check-ref-format", "--branch", name],
                   os.getcwd(), check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"分支名不合法: {name}")
    return name


def _remote_heads(local_dir, remote):
    """返回远端全部分支名集合（一次网络请求）。失败抛错。"""
    proc = run_git(["ls-remote", "--heads", remote], local_dir, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"ls-remote 失败: {proc.stdout.strip()}")
    heads = set()
    for line in proc.stdout.splitlines():
        line = line.strip()
        if "\t" not in line:
            continue
        _, ref = line.split("\t", 1)
        if ref.startswith("refs/heads/"):
            heads.add(ref[len("refs/heads/"):])
    return heads


def create_branch(conf, branch_name, from_branch=None, remote=None):
    """在指定工程上基于 from_branch 创建新分支并推送到远程。

    - 不修改本地工作区（不 checkout），仅创建 ref 并推送；
    - 本地同步建一个同名分支引用，便于后续操作；
    - 返回 (ok, message)。
    """
    name = _validate_branch_name(branch_name)
    if not from_branch or not (from_branch or "").strip():
        from_branch = conf.get("source_branch") or ""
    from_branch = (from_branch or "").strip()
    if not from_branch:
        raise RuntimeError("请指定基于哪个分支创建（from_branch）")
    remote = remote or conf.get("remote") or "origin"
    local_dir = ensure_repo(conf, check_branches=False)

    heads = _remote_heads(local_dir, remote)
    if name in heads:
        raise RuntimeError(f"远程分支已存在: {name}")
    if from_branch not in heads:
        raise RuntimeError(f"源分支不存在: {from_branch}")
    src_sha = _resolve_branch_ref(local_dir, from_branch, remote)
    if not src_sha:
        raise RuntimeError(f"无法解析源分支 SHA: {from_branch}")

    commands = [
        format_git_command(["push", remote, f"{src_sha}:refs/heads/{name}"], local_dir),
        format_git_command(["branch", name, src_sha], local_dir),
    ]
    logging.info("执行命令: %s", commands[0])
    push = run_git(["push", remote, f"{src_sha}:refs/heads/{name}"],
                   local_dir, check=False)
    if push.returncode != 0:
        raise BranchCommandError(f"创建分支失败: {push.stdout.strip()}", commands[:1])
    # 本地同步建引用（失败不影响结果，仅用于本地后续操作方便）
    logging.info("执行命令: %s", commands[1])
    run_git(["branch", name, src_sha], local_dir, check=False)
    return True, f"已创建并推送分支 {name}（基于 {from_branch}）", commands, {
        "branch_name": name,
        "from_branch": from_branch,
        "sha": src_sha,
    }


def create_branch_at_sha(conf, branch_name, sha, remote=None):
    """按指定 SHA 恢复/创建远程分支，用于撤回删除分支。"""
    name = _validate_branch_name(branch_name)
    sha = (sha or "").strip()
    if not sha:
        raise RuntimeError("缺少用于恢复分支的 SHA")
    remote = remote or conf.get("remote") or "origin"
    local_dir = ensure_repo(conf, check_branches=False)

    heads = _remote_heads(local_dir, remote)
    if name in heads:
        raise RuntimeError(f"远程分支已存在: {name}")

    commands = [
        format_git_command(["push", remote, f"{sha}:refs/heads/{name}"], local_dir),
        format_git_command(["branch", name, sha], local_dir),
    ]
    logging.info("执行命令: %s", commands[0])
    push = run_git(["push", remote, f"{sha}:refs/heads/{name}"],
                   local_dir, check=False)
    if push.returncode != 0:
        raise BranchCommandError(f"恢复分支失败: {push.stdout.strip()}", commands[:1])
    logging.info("执行命令: %s", commands[1])
    run_git(["branch", name, sha], local_dir, check=False)
    return True, f"已恢复远程分支 {name}", commands, {
        "branch_name": name,
        "sha": sha,
    }


def delete_branch(conf, branch_name, remote=None, allow_protected=False):
    """删除指定工程的远程分支；本地若存在同名分支且非当前检出分支则一并删除。

    返回 (ok, message)。
    """
    name = (branch_name or "").strip()
    if not name:
        raise RuntimeError("请指定要删除的分支")
    if name in PROTECTED_BRANCHES and not allow_protected:
        raise RuntimeError(f"受保护分支，禁止删除: {name}")
    remote = remote or conf.get("remote") or "origin"
    local_dir = ensure_repo(conf, check_branches=False)

    heads = _remote_heads(local_dir, remote)
    if name not in heads:
        raise RuntimeError(f"远程分支不存在: {name}")
    old_sha = _resolve_branch_ref(local_dir, name, remote)
    if not old_sha:
        raise RuntimeError(f"无法解析待删除分支 SHA: {name}")

    commands = [
        format_git_command(["push", remote, "--delete", name], local_dir),
        format_git_command(["branch", "-D", name], local_dir),
    ]
    logging.info("执行命令: %s", commands[0])
    push = run_git(["push", remote, "--delete", name], local_dir, check=False)
    if push.returncode != 0:
        raise BranchCommandError(f"删除远程分支失败: {push.stdout.strip()}", commands[:1])

    msgs = []
    cur = run_git(["rev-parse", "--abbrev-ref", "HEAD"],
                  local_dir, check=False).stdout.strip()
    logging.info("执行命令: %s", commands[1])
    delp = run_git(["branch", "-D", name], local_dir, check=False)
    if delp.returncode == 0:
        msgs.append("本地同名分支已删除")
    elif cur == name:
        msgs.append("本地正检出该分支，未自动删除")
    return True, f"已删除远程分支 {name}" + (f"（{'；'.join(msgs)}）" if msgs else ""), commands, {
        "branch_name": name,
        "sha": old_sha,
    }


def rename_branch(conf, old_name, new_name, remote=None, allow_protected_old=False):
    """重命名远程分支：新名指向旧名 commit，再删除旧名，本地同名分支同步重命名。

    返回 (ok, message)。
    """
    old = (old_name or "").strip()
    new = _validate_branch_name(new_name)
    if not old:
        raise RuntimeError("请指定要重命名的原分支")
    if old == new:
        raise RuntimeError("新分支名不能与原分支相同")
    if old in PROTECTED_BRANCHES and not allow_protected_old:
        raise RuntimeError(f"受保护分支，禁止重命名: {old}")
    remote = remote or conf.get("remote") or "origin"
    local_dir = ensure_repo(conf, check_branches=False)

    heads = _remote_heads(local_dir, remote)
    if old not in heads:
        raise RuntimeError(f"远程分支不存在: {old}")
    if new in heads:
        raise RuntimeError(f"目标分支已存在: {new}")

    old_sha = _resolve_branch_ref(local_dir, old, remote)
    if not old_sha:
        raise RuntimeError(f"无法解析原分支 SHA: {old}")

    commands = [
        format_git_command(["push", remote, f"{old_sha}:refs/heads/{new}"], local_dir),
        format_git_command(["push", remote, "--delete", old], local_dir),
        format_git_command(["branch", "-m", old, new], local_dir),
    ]
    logging.info("执行命令: %s", commands[0])
    push = run_git(["push", remote, f"{old_sha}:refs/heads/{new}"],
                   local_dir, check=False)
    if push.returncode != 0:
        raise BranchCommandError(f"创建新分支失败: {push.stdout.strip()}", commands[:1])
    logging.info("执行命令: %s", commands[1])
    delp = run_git(["push", remote, "--delete", old], local_dir, check=False)
    if delp.returncode != 0:
        raise BranchCommandError(f"新分支 {new} 已创建，但删除旧分支 {old} 失败: "
                                 f"{delp.stdout.strip()}", commands[:2])
    logging.info("执行命令: %s", commands[2])
    run_git(["branch", "-m", old, new], local_dir, check=False)
    return True, f"已将远程分支 {old} 重命名为 {new}", commands, {
        "old_name": old,
        "new_name": new,
        "sha": old_sha,
    }


def switch_local_branch(conf, branch_name, remote=None):
    """切换本地工作区到指定分支；不 reset、不 push，工作区不干净时拒绝。"""
    name = _validate_branch_name(branch_name)
    remote = remote or conf.get("remote") or "origin"
    local_dir = (conf.get("local_dir") or "").strip()
    if not (local_dir and Path(local_dir).exists() and is_git_repo(local_dir)):
        raise RuntimeError("本地仓库不存在，请先拉取项目到本地")

    status = run_git(["status", "--porcelain"], local_dir, check=False).stdout.strip()
    if status:
        raise RuntimeError(f"工作区有未提交改动，拒绝切换分支:\n{status}")

    commands = [format_git_command(["fetch", "--prune", remote], local_dir)]
    run_git(["fetch", "--prune", remote], local_dir)

    has_local = run_git(
        ["show-ref", "--verify", "--quiet", f"refs/heads/{name}"],
        local_dir,
        check=False,
    ).returncode == 0
    if has_local:
        commands.append(format_git_command(["checkout", name], local_dir))
        run_git(["checkout", name], local_dir)
    else:
        remote_ref = f"{remote}/{name}"
        has_remote = run_git(
            ["rev-parse", "--verify", "--quiet", remote_ref],
            local_dir,
            check=False,
        ).returncode == 0
        if not has_remote:
            raise RuntimeError(f"本地和远端均不存在分支: {name}")
        commands.append(format_git_command(["checkout", "-b", name, remote_ref], local_dir))
        run_git(["checkout", "-b", name, remote_ref], local_dir)

    current = run_git(["rev-parse", "--abbrev-ref", "HEAD"], local_dir).stdout.strip()
    return True, f"已切换到本地分支 {current}", commands, {
        "branch_name": current,
    }


# ---------------------------------------------------------------- 撤回合并（undo）

# 撤回记录文件路径，由 webapp 启动时设置（gm.UNDO_FILE = ...）
UNDO_FILE = None


def save_undo(items, merged_at=None):
    """保存最近一次合并的可撤回记录（覆盖写入）。"""
    if UNDO_FILE is None or not items:
        return
    import time as _time
    payload = {
        "merged_at": merged_at or _time.strftime("%Y-%m-%d %H:%M:%S"),
        "items": items,
    }
    with open(UNDO_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def load_undo():
    if UNDO_FILE is None or not Path(UNDO_FILE).exists():
        return None
    try:
        with open(UNDO_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def clear_undo():
    if UNDO_FILE is not None and Path(UNDO_FILE).exists():
        try:
            Path(UNDO_FILE).unlink()
        except OSError:
            pass


def undo_merge_item(item):
    """撤回单个工程目标分支的合并：本地 reset --hard + 远程强制还原。

    返回描述文本；失败抛 SystemExit。
    """
    local_dir = item["local_dir"]
    branch = item["branch"]
    before = item["before_sha"]
    after = item.get("after_sha")
    remote = item.get("remote", "origin")
    name = item.get("name", branch)

    # 安全校验：工作区必须干净，避免覆盖用户未提交改动
    status = run_git(["status", "--porcelain"], local_dir, check=False).stdout.strip()
    if status:
        raise SystemExit(
            f"[{name}] {branch} 工作区有未提交改动，拒绝撤回，请先处理:\n{status[:300]}")

    # 本地还原到合并前
    run_git(["checkout", branch], local_dir)
    run_git(["reset", "--hard", before], local_dir)

    # 远程还原：只有远程仍是合并后的 SHA 才强制推送；
    # 若远程已等于 before 则无需推送；若被他人推进则跳过并提示。
    proc = run_git(
        ["ls-remote", remote, f"refs/heads/{branch}"],
        local_dir, check=False)
    remote_sha = (proc.stdout.split("\t")[0].strip()
                  if proc.stdout and proc.returncode == 0 else None)

    pushed = False
    if remote_sha:
        if after and remote_sha == after:
            push = run_git(
                ["push", "--force", remote, f"{before}:refs/heads/{branch}"],
                local_dir, check=False)
            if push.returncode != 0:
                raise SystemExit(f"[{name}] 强制推送失败: {push.stdout.strip()}")
            pushed = True
        elif remote_sha == before:
            logging.info("[%s] 远程 %s 本就未合并，无需推送", name, branch)
        else:
            logging.warning(
                "[%s] 远程 %s 已被其他提交推进（%s），跳过推送，仅还原本地",
                name, branch, remote_sha[:8])

    return (f"[{name}] {branch} 已还原到 {before[:8]}"
            + ("，远程已强制还原" if pushed else ""))


# ----------------------------------------------- 范围 commits & 单 commit diff


def _resolve_branch_ref(local_dir, branch, remote="origin"):
    """把分支名解析为完整 SHA；优先 remote/branch（远端最新），其次 branch。
    失败返回空串。

    注意：必须先优先 `remote/branch`。因为本机可能 checkout 过同名本地分支，
    它往往停留在旧 commit（git fetch 只更新 origin/*，不更新本地分支），
    如果优先本地分支就会漏掉最近 push 的 commit，造成「GitLab 有 154 个
    而这里只有 130 个」这类数量对不上的问题。
    """
    if not (branch and local_dir and Path(local_dir).exists() and is_git_repo(local_dir)):
        return ""
    for ref in (f"{remote}/{branch}", branch):
        proc = run_git(["rev-parse", "--verify", "--quiet", ref], str(local_dir), check=False)
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    return ""


def range_commits(local_dir, source, target, limit=500, remote="origin"):
    """返回 source..target 之间（即本次将合并进 target 的 commits）的列表。

    source/target 可能是远程 ref 也可能是本地分支名；自动通过 _resolve_branch_ref
    解析为 SHA。

    实现要点：
    0. 先做一次轻量 `git fetch --prune`，把远端最新 refs 拉到本地，避免本地
       仓库因长时间未拉取而漏掉近期的 commit（这正是这次出现的"GitLab 显示
       154 个，本工具只展示 130 个"的根因）。
    1. 使用 `git rev-list target..source` 按 GitLab 比较页的提交集合口径展示。
       注意不要用 `git cherry` 做 patch-id 过滤，否则 GitLab 仍展示的等价提交
       会被本工具误隐藏，出现 25 被算成 22 这类数量差异。
    2. 兜底：如果上面为空，说明 target 已经包含了 source 的所有内容；
       此时再用 `git rev-list --merges target..source` 单独拉 source 上独有
       的 merge commit（合并提交可能因内容已并入 target 而不计入差异，但
       仍是「合并动作」语义上的待合并项）。
    3. 用 `git show -s --no-walk` 一次性取所有 SHA 的 subject/author/date。
    """
    if not (local_dir and Path(local_dir).exists() and is_git_repo(str(local_dir))):
        return [], 0

    # 0. 先 fetch 远端，让本地 refs 与 GitLab 保持一致；fetch 失败/超时沿用旧 refs
    try:
        logging.info("同步远端 refs (fetch --prune %s): %s", remote, local_dir)
        run_git(["fetch", "--prune", remote], str(local_dir),
                check=False, timeout=90)
    except Exception as e:
        logging.warning("fetch %s 失败，沿用本地 refs (%s)", remote, e)

    s_sha = _resolve_branch_ref(str(local_dir), source, remote)
    t_sha = _resolve_branch_ref(str(local_dir), target, remote)
    if not s_sha or not t_sha:
        return [], 0

    # 1. 默认查询：source 上有而 target 上没有的所有 commits（GitLab 口径）
    count_proc = run_git(
        ["rev-list", "--count", f"{t_sha}..{s_sha}"],
        str(local_dir), check=False,
    )
    shas_proc = run_git(
        ["rev-list", f"{t_sha}..{s_sha}", f"-n{limit}"],
        str(local_dir), check=False,
    )
    if count_proc.returncode != 0 or shas_proc.returncode != 0:
        return [], 0
    try:
        total = int((count_proc.stdout or "0").strip())
    except (TypeError, ValueError):
        total = 0
    shas = [s for s in (shas_proc.stdout or "").splitlines() if s.strip()]

    # 2. 兜底：默认为空时单独查 merge-only（合并提交可能被 rev-list 默认行为
    #    因 parent 路径覆盖而漏掉，确保合并动作不会从「待合并」列表里消失）
    merge_only = False
    if not shas:
        merges_proc = run_git(
            ["rev-list", "--merges", f"{t_sha}..{s_sha}", f"-n{limit}"],
            str(local_dir), check=False,
        )
        if merges_proc.returncode == 0:
            shas = [s for s in (merges_proc.stdout or "").splitlines() if s.strip()]
            merge_only = bool(shas)

    if not shas:
        return [], 0

    # 3. 一次性取所有 SHA 的 metadata
    fmt = "%H%x09%an%x09%ad%x09%s"
    show_proc = run_git(
        ["show", "-s", "--no-walk", "--date=short", f"--pretty=format:{fmt}"] + shas,
        str(local_dir), check=False,
    )
    if show_proc.returncode != 0:
        return [], 0

    items = []
    for line in (show_proc.stdout or "").splitlines():
        parts = line.split("\t", 3)
        if len(parts) != 4:
            continue
        sha, author, date, subject = parts
        items.append({
            "sha": sha,
            "short": sha[:8],
            "author": author,
            "date": date,
            "subject": subject,
            "merge_only": merge_only,  # 标识这是兜底展示的合并提交
        })
    return items, total or len(items)


def commit_diff(local_dir, sha, max_lines=2000):
    """取单个 commit 的文件改动列表 + patch 文本。

    返回 dict: {sha, short, header, files:[{path,additions,deletions}],
                files_count, stat, patch, truncated}
    """
    if not (sha and local_dir and Path(local_dir).exists() and is_git_repo(str(local_dir))):
        return None

    full_sha = run_git(["rev-parse", "--verify", "--quiet", sha], str(local_dir), check=False).stdout.strip()
    if not full_sha:
        return None
    short = full_sha[:8]

    # header（作者/日期/subject/消息体）
    header = run_git(
        ["show", "-s", "--no-patch", "--pretty=format:%H%n%an%n%ad%n%s%n%n%b",
         "--date=short", full_sha],
        str(local_dir), check=False,
    ).stdout or ""

    # numstat
    files = []
    numstat = run_git(
        ["show", full_sha, "--pretty=format:", "--no-renames", "--numstat"],
        str(local_dir), check=False,
    )
    for line in (numstat.stdout or "").splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        a, d, path = parts
        if a == "-" and d == "-":
            a, d = "0", "0"  # 二进制文件
        try:
            files.append({"path": path, "additions": int(a), "deletions": int(d)})
        except Exception:
            files.append({"path": path, "additions": 0, "deletions": 0})

    # 完整 patch
    proc = run_git(
        ["show", "--no-renames", "--stat", "--patch", full_sha],
        str(local_dir), check=False,
    )
    raw = proc.stdout or ""
    truncated = False
    if raw.count("\n") > max_lines:
        raw = "\n".join(raw.split("\n")[:max_lines]) + f"\n… (已截断，超出 {max_lines} 行)"
        truncated = True

    # stat 段（commit hash 之后到首个空行 + files）
    stat = ""
    if raw:
        first_blank = raw.find("\n\n")
        stat = raw[: first_blank if first_blank > 0 else 0]

    return {
        "sha": full_sha,
        "short": short,
        "header": header,
        "files": files,
        "files_count": len(files),
        "stat": stat,
        "patch": raw,
        "truncated": truncated,
        "ok": proc.returncode == 0,
    }


def list_commits(conf, branch, count=50, offset=0):
    """列出远程分支的最近 commit 列表（分页），返回 [{sha, short, author, date, subject}]。"""
    local_dir = ensure_repo(conf, check_branches=False)
    proc = run_git(
        ["log", f"{conf['remote']}/{branch}", "-n", str(count),
         "--skip", str(offset),
         "--pretty=format:%H\t%an\t%ad\t%s", "--date=short"],
        str(local_dir), check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stdout.strip() or f"git log 失败（分支 {branch} 不存在?）")
    commits = []
    for line in proc.stdout.splitlines():
        parts = line.split("\t", 3)
        if len(parts) == 4:
            commits.append({
                "sha": parts[0],
                "short": parts[0][:8],
                "author": parts[1],
                "date": parts[2],
                "subject": parts[3],
            })
    return commits


def list_commits_by_period(conf, branch, start_date, end_date):
    """列出远程分支在指定日期范围内的 commit，返回 [{sha, short, author, date, subject}]。"""
    local_dir = (conf.get("local_dir") or "").strip()
    if local_dir and Path(local_dir).exists() and is_git_repo(local_dir):
        local_dir = str(Path(local_dir).expanduser().resolve())
    else:
        local_dir = ensure_repo(conf, check_branches=False)

    remote = conf.get("remote") or "origin"
    candidates = [f"{remote}/{branch}", branch]
    ref = ""
    for item in candidates:
        proc = run_git(["rev-parse", "--verify", "--quiet", item],
                       str(local_dir), check=False)
        if proc.returncode == 0 and proc.stdout.strip():
            ref = item
            break
    if not ref:
        raise SystemExit(f"分支 {branch} 不存在，请先加载或选择正确源分支")

    proc = run_git(
        ["log", ref,
         "--since", f"{start_date} 00:00:00",
         "--until", f"{end_date} 23:59:59",
         "--pretty=format:%H\t%an\t%ad\t%s", "--date=short"],
        str(local_dir), check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stdout.strip() or f"git log 失败（分支 {branch} 不存在?）")
    commits = []
    for line in proc.stdout.splitlines():
        parts = line.split("\t", 3)
        if len(parts) == 4:
            commits.append({
                "sha": parts[0],
                "short": parts[0][:8],
                "author": parts[1],
                "date": parts[2],
                "subject": parts[3],
            })
    return commits


def list_commits_by_date(conf, branch, date):
    """列出远程分支在指定日期的 commit，返回 [{sha, short, author, date, subject}]。"""
    return list_commits_by_period(conf, branch, date, date)


def count_commits(conf, branch):
    """返回远程分支的 commit 总数（分支不存在或为空时返回 0）。"""
    local_dir = ensure_repo(conf, check_branches=False)
    proc = run_git(
        ["rev-list", "--count", f"{conf['remote']}/{branch}"],
        str(local_dir), check=False,
    )
    if proc.returncode != 0:
        return 0
    try:
        return int(proc.stdout.strip())
    except (ValueError, TypeError):
        return 0


def cherry_pick_commits(conf, commits, target_branch, dry_run=False):
    """把选中的 commit 依次 cherry-pick 到指定目标分支，成功则推送。返回提示文案。"""
    local_dir = ensure_repo(conf, check_branches=False)
    remote = conf["remote"]

    if not checkout_target(remote, target_branch, str(local_dir)):
        raise SystemExit(f"目标分支 {target_branch} 工作区不干净，请先清理")

    if dry_run:
        logging.info("[演练] 将执行: git cherry-pick %s", " ".join(commits))
        return "演练模式，未实际执行"

    picked = []
    for sha in commits:
        logging.info("执行命令: %s", format_git_command(["cherry-pick", sha], local_dir))
        proc = run_git(["cherry-pick", sha], str(local_dir), check=False)
        if proc.returncode != 0:
            logging.info("执行命令: %s", format_git_command(["cherry-pick", "--abort"], local_dir))
            run_git(["cherry-pick", "--abort"], str(local_dir), check=False)
            raise SystemExit(f"cherry-pick {sha[:8]} 失败/冲突: {proc.stdout.strip()}")
        picked.append(sha)

    if conf["push_on_success"]:
        logging.info("执行命令: %s", format_git_command(["push", remote, target_branch], local_dir))
        push = run_git(["push", remote, target_branch], str(local_dir), check=False)
        if push.returncode != 0:
            raise SystemExit(f"推送失败: {push.stdout.strip()}")
    return f"已成功 pick {len(picked)} 个 commit 到 {target_branch}"


# ---------------------------------------------------------------- 主流程

def main():
    parser = argparse.ArgumentParser(
        description="GitLab 多项目分支批量合并工具：将各项目源分支合并到多个目标分支")
    parser.add_argument("config", nargs="?", default="config.ini",
                        help="配置文件路径（默认 config.ini）")
    parser.add_argument("--dry-run", action="store_true",
                        help="演练模式：只打印将要执行的 git 命令，不实际执行")
    parser.add_argument("--project", action="append", metavar="NAME",
                        help="只处理指定名称的项目（可多次指定，如 --project demo1 --project demo2）")
    args = parser.parse_args()

    default_conf, projects = load_config(args.config)
    logging.basicConfig(
        level=getattr(logging, default_conf["log_level"], logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if args.project:
        selected = [p for p in projects if p["name"] in args.project]
        if not selected:
            logging.error("未找到指定的项目: %s（可用项目: %s）",
                          ", ".join(args.project),
                          ", ".join(p["name"] for p in projects))
            sys.exit(1)
        projects = selected

    logging.info("共 %d 个项目待处理", len(projects))
    for p in projects:
        logging.info("  - [%s] %s -> %s (%s)",
                     p["name"], p["source_branch"],
                     ", ".join(p["target_branches"]), build_remote_url(p))
    if args.dry_run:
        logging.warning("当前为演练模式(dry-run)，不会执行任何实际改动")

    if shutil.which("git") is None:
        logging.error("未找到 git 命令，请先安装 git")
        sys.exit(1)

    all_ok = True
    for proj in projects:
        if not process_project(proj, args.dry_run):
            all_ok = False

    if all_ok:
        logging.info("全部项目处理完成 ✔")
        sys.exit(0)
    else:
        logging.warning("存在失败的项目，请人工检查")
        sys.exit(1)


if __name__ == "__main__":
    main()
