#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared config and project normalization helpers for the web app."""

import configparser
import json
import os
from pathlib import Path

import gitlab_merge as gm

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "config.ini"
PROFILES_FILE = BASE_DIR / "profiles.json"
UNDO_FILE = BASE_DIR / "merge_undo.json"
BRANCH_OP_UNDO_FILE = BASE_DIR / "branch_op_undo.json"
AUDIT_LOG_FILE = BASE_DIR / "danger_audit_log.json"


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
    """读取 [global] 段下的全局分支设置。"""
    cfg = _read_cfg()
    if not cfg.has_section("global"):
        return {
            "ssh_host": "",
            "ssh_ip": "38.76.216.46",
            "ssh_port": "42221",
            "ssh_origin": "ssh://git@38.76.216.46:42221",
            "ssh_vars": {},
            "source_branch": "",
            "target_branches": [],
        }
    targets_str = cfg.get("global", "target_branches", fallback="")
    ssh_ip = cfg.get("global", "ssh_ip", fallback="38.76.216.46") or "38.76.216.46"
    ssh_port = cfg.get("global", "ssh_port", fallback="42221") or "42221"
    try:
        ssh_vars = json.loads(cfg.get("global", "ssh_vars", fallback="{}") or "{}")
        if not isinstance(ssh_vars, dict):
            ssh_vars = {}
    except json.JSONDecodeError:
        ssh_vars = {}
    return {
        "ssh_host": cfg.get("global", "ssh_host", fallback=""),
        "ssh_ip": ssh_ip,
        "ssh_port": ssh_port,
        "ssh_origin": cfg.get("global", "ssh_origin", fallback=f"ssh://git@{ssh_ip}:{ssh_port}") or f"ssh://git@{ssh_ip}:{ssh_port}",
        "ssh_vars": ssh_vars,
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
    cfg.set("global", "ssh_ip", (g.get("ssh_ip") or "").strip())
    cfg.set("global", "ssh_port", (g.get("ssh_port") or "").strip())
    cfg.set("global", "ssh_origin", (g.get("ssh_origin") or "").strip())
    ssh_vars = g.get("ssh_vars") or {}
    if not isinstance(ssh_vars, dict):
        ssh_vars = {}
    cfg.set("global", "ssh_vars", json.dumps({
        str(k).strip(): str(v).strip().rstrip("/")
        for k, v in ssh_vars.items()
        if str(k).strip() and str(v).strip()
    }, ensure_ascii=False))
    cfg.set("global", "source_branch", (g.get("source_branch") or "").strip())
    tgts = g.get("target_branches") or []
    if isinstance(tgts, str):
        tgts = [t.strip() for t in tgts.split(",") if t.strip()]
    if not isinstance(tgts, list):
        tgts = []
    cfg.set("global", "target_branches", ",".join(t.strip() for t in tgts if t.strip()))
    with open(str(CONFIG_FILE), "w", encoding="utf-8") as f:
        cfg.write(f)


def _global_vars(g=None):
    g = g if isinstance(g, dict) else load_global()
    ssh_ip = (g.get("ssh_ip") or "").strip()
    ssh_port = (g.get("ssh_port") or "").strip()
    ssh_origin = (g.get("ssh_origin") or "").strip()
    if not ssh_origin and ssh_ip and ssh_port:
        ssh_origin = f"ssh://git@{ssh_ip}:{ssh_port}"
    values = {
        "ssh_ip": ssh_ip,
        "git_ip": ssh_ip,
        "ssh_port": ssh_port,
        "git_port": ssh_port,
        "ssh_origin": ssh_origin.rstrip("/"),
        "git_origin": ssh_origin.rstrip("/"),
    }
    ssh_vars = g.get("ssh_vars") or {}
    if isinstance(ssh_vars, dict):
        for key, val in ssh_vars.items():
            key = str(key).strip().strip("{}").strip()
            val = str(val).strip().rstrip("/")
            if key and val:
                values[key] = val
    return values


def resolve_config_vars(text, global_cfg=None):
    """解析工程配置中的变量，如 {{ssh_origin}} / {{custom_origin}}。"""
    text = (text or "").strip()
    if not text:
        return ""
    values = _global_vars(global_cfg)
    out = text
    for key, val in values.items():
        used = ("{{" + key + "}}" in out) or ("${" + key + "}" in out)
        if used and not val:
            label = "SSH IP / 域名" if key.endswith("_ip") else "SSH 端口"
            raise ValueError(f"SSH 地址使用了变量 {key}，请先配置全局{label}")
        if val:
            out = out.replace("{{" + key + "}}", val)
            out = out.replace("${" + key + "}", val)
    return out


def project_repo_dir(base_dir, conf):
    """把用户输入的拉取根目录解析成具体仓库目录；已是 Git 仓库时直接复用。"""
    base = Path(base_dir).expanduser()
    if gm.is_git_repo(str(base)):
        return str(base.resolve())
    return str((base / gm.repo_dir_name(conf)).resolve())


def auto_project_name(s, i):
    """工程名称自动生成：优先用项目路径最后一段，其次 SSH 地址中的路径。"""
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


def normalize_projects(submitted, resolve_vars=True, global_cfg=None):
    """把前端提交的简化配置补全为 process_project 所需的完整结构。"""
    try:
        _default, existing = gm.load_config(str(CONFIG_FILE))
    except SystemExit:
        _default, existing = {
            "ssh_port": 22,
            "local_dir_base": "./repos",
            "remote": "origin",
            "no_ff": True,
            "push_on_success": True,
            "stop_on_conflict": True,
            "log_level": "INFO",
        }, []
    projects = []
    for i, s in enumerate(submitted, 1):
        name = auto_project_name(s, i)
        base = next((e for e in existing if e["name"] == name), None)
        p = dict(base) if base else dict(_default)
        p["name"] = name
        ssh_host = (s.get("ssh_host") or "").strip()
        p["ssh_host"] = resolve_config_vars(ssh_host, global_cfg) if resolve_vars else ssh_host
        p["project_path"] = (s.get("project_path") or "").strip("/")
        p["source_branch"] = (s.get("source_branch") or "").strip()
        targets = s.get("target_branches") or []
        if isinstance(targets, str):
            targets = targets.split(",")
        p["target_branches"] = [t.strip() for t in targets if t.strip()]
        submitted_local = (s.get("local_dir") or "").strip()
        if submitted_local:
            p["local_dir"] = submitted_local
        if not p.get("local_dir"):
            dir_part = (p.get("project_path")
                        or gm.extract_path_from_url(p["ssh_host"])
                        or name)
            p["local_dir"] = os.path.join(
                p.get("local_dir_base", "./repos"), dir_part.replace("/", "__"))
        if s.get("switch_branch") is not None:
            p["switch_branch"] = (s.get("switch_branch") or "").strip()
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
