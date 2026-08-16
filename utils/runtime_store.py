#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Runtime JSON stores for profiles, branch undo data, and audit logs."""

import json
import time

from utils.app_config import (
    AUDIT_LOG_FILE,
    BRANCH_OP_UNDO_FILE,
    PROFILES_FILE,
    auto_project_name,
)


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

    source = (g.get("source_branch") or "").strip()
    source_branches = []
    if source:
        source_branches = [source]
    else:
        for p in projects:
            sb = (p.get("source_branch") or "").strip()
            if sb and sb not in source_branches:
                source_branches.append(sb)

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
