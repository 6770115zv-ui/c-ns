# -*- coding: utf-8 -*-
"""Read-only source-code security research runner for a Kaggle GPU kernel."""
import json
import os
import re
import subprocess
from pathlib import Path

import runner_lib as base

JOB = globals().get("JOB", {})
SOURCE_ROOT = None
MAX_TOOL_OUTPUT = 12000
TEXT_SUFFIXES = {
    ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".S", ".s", ".rs", ".go",
    ".py", ".sh", ".y", ".l", ".java", ".md", ".rst", ".txt", ".yaml", ".yml",
    ".json", ".toml", ".xml", ".conf", ".config",
}

PROBES = {
    "usercopy": r"\b(copy_from_user|copy_to_user|get_user|put_user)\s*\(",
    "string-and-bounds": r"\b(strcpy|strcat|sprintf|vsprintf|memcpy|memmove|strncpy)\s*\(",
    "lifetime-and-refcount": r"\b(kfree|kvfree|vfree|list_del|list_del_rcu|refcount_dec|put_device|fput)\s*\(",
    "locking-and-rcu": r"\b(spin_lock|spin_unlock|mutex_lock|mutex_unlock|rcu_read_lock|rcu_read_unlock)\s*\(",
    "allocations": r"\b(kmalloc|kzalloc|kcalloc|krealloc|vmalloc|alloc_pages|kmem_cache_alloc)\s*\(",
    "privileged-interfaces": r"\b(unlocked_ioctl|compat_ioctl|CAP_SYS_ADMIN|capable)\b",
}

SYSTEM_PROMPT = """You are a defensive source-code security researcher performing an authorized, READ-ONLY audit of a public source repository.
Your mission is to identify plausible, previously unnoticed security defects in existing code, especially memory-safety, race/lifetime, integer/bounds, privilege-boundary, and input-validation bugs.
You may only inspect source and git metadata using the supplied read-only tools. Do not execute target code, build the target, modify source files, run payloads, or attempt exploitation.
Do not treat the mere presence of a dangerous API as a vulnerability. Trace relevant callers/callees, ownership, object lifetime, bounds, locks, error paths, and privilege context. Search for corroborating evidence before making a claim.
Classify each result as CANDIDATE, LIKELY, or CONFIRMED. Use CONFIRMED only when the source evidence proves the faulty path; otherwise say what runtime test or maintainer review is needed.
Prioritize depth over breadth. Avoid duplicate findings and generic advice. Do not invent line numbers, call paths, reachability, CVEs, or test outcomes.
Return a report in Markdown with: executive summary; scope and exact commit; findings sorted by severity; for each finding include title, status, severity, CWE if clear, exact file:line, concise code evidence, triggering conditions, root-cause reasoning, impact, confidence, and a safe remediation direction; then limitations and recommended validation. If no strong issue is found, say so plainly and list areas actually inspected.
Do not include exploit code, weaponization steps, or instructions for attacking deployed systems. The objective is careful source review and responsible disclosure.
"""

RESEARCH_TOOLS = [
    {"type": "function", "function": {
        "name": "list_source_files",
        "description": "List tracked source files under a repository-relative directory. Read-only; path defaults to '.'.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "limit": {"type": "integer"}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "read_source_file",
        "description": "Read a tracked text source file with line numbers. Use start_line/end_line to inspect a narrow range. Paths cannot escape the cloned repository.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "search_source_code",
        "description": "Search for a literal string in tracked text files; returns file names, line numbers and matching lines. Prefer specific symbols or API names.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}, "path": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "run_static_probe",
        "description": "Run one predefined, read-only source search for a class of security-sensitive APIs. This only finds leads; it does not prove a vulnerability.",
        "parameters": {"type": "object", "properties": {
            "probe": {"type": "string"}, "path": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["probe"]}}},
    {"type": "function", "function": {
        "name": "get_source_metadata",
        "description": "Return the cloned repository, exact commit, latest commit subject and tracked file count.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
]

def validate_target_repo(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
        raise ValueError("target_repo must be a GitHub owner/repository pair, e.g. torvalds/linux")
    owner, name = value.split("/", 1)
    if owner in {".", ".."} or name in {".", ".."} or owner.startswith("-") or name.startswith("-"):
        raise ValueError("Invalid GitHub repository name")
    return value

def validate_ref(value):
    if not isinstance(value, str) or not value or len(value) > 160:
        raise ValueError("target_ref must be a non-empty branch or tag name")
    if value.startswith("-") or ".." in value.split("/") or not re.fullmatch(r"[A-Za-z0-9._/-]+", value):
        raise ValueError("target_ref contains unsupported characters")
    return value

def safe_relative_path(value):
    if value in (None, "", "."):
        return "."
    if not isinstance(value, str) or len(value) > 500:
        raise ValueError("Invalid source path")
    p = Path(value)
    if p.is_absolute() or any(part in ("..", "") for part in p.parts):
        raise ValueError("Source path must stay inside the repository")
    return p.as_posix()

def run_git(args, timeout=60):
    if SOURCE_ROOT is None:
        return {"ok": False, "exit": 1, "output": "Source repository is not initialized"}
    try:
        result = subprocess.run(
            ["git", "-C", str(SOURCE_ROOT), *args],
            text=True, capture_output=True, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "exit": 124, "output": "git command timed out"}
    except OSError as exc:
        return {"ok": False, "exit": 127, "output": f"git unavailable: {type(exc).__name__}"}
    output = ((result.stdout or "") + (result.stderr or "")).strip()
    return {"ok": result.returncode == 0, "exit": result.returncode, "output": output}

def list_source_files(args):
    try:
        path = safe_relative_path(args.get("path", "."))
        limit = max(1, min(int(args.get("limit", 100)), 300))
    except (ValueError, TypeError) as exc:
        return {"ok": False, "output": str(exc)}
    git_args = ["ls-files"]
    if path != ".":
        git_args += ["--", path.rstrip("/") + ("/" if not Path(path).suffix else "")]
    result = run_git(git_args, timeout=90)
    if not result["ok"]:
        return result
    files = [line for line in result["output"].splitlines()
             if Path(line).suffix in TEXT_SUFFIXES or Path(line).name in {"Makefile", "Kconfig"}]
    shown = files[:limit]
    return {"ok": True, "output": f"Tracked text/source files: {len(files)}; showing {len(shown)} (limit {limit}).\n" + "\n".join(shown)}

def read_source_file(args):
    try:
        rel = safe_relative_path(args.get("path"))
        if rel == ".":
            raise ValueError("A file path is required")
        candidate = (SOURCE_ROOT / rel).resolve()
        candidate.relative_to(SOURCE_ROOT.resolve())
        if not candidate.is_file() or (candidate.suffix not in TEXT_SUFFIXES and candidate.name not in {"Makefile", "Kconfig"}):
            raise ValueError("Path is not a tracked text/source file")
        start = max(1, int(args.get("start_line", 1) or 1))
        end = max(start, int(args.get("end_line", start + 239) or (start + 239)))
        end = min(end, start + 319)
        lines = candidate.read_text(encoding="utf-8", errors="replace").splitlines()
    except (ValueError, OSError, TypeError) as exc:
        return {"ok": False, "output": f"Cannot read source file: {exc}"}
    if len(lines) > 500000:
        return {"ok": False, "output": "File too large for direct reading; use search_source_code first"}
    selected = lines[start - 1:end]
    body = "\n".join(f"{i}: {line}" for i, line in enumerate(selected, start))
    if len(body) > 20000:
        body = body[:20000] + "\n...[truncated; request a narrower line range]"
    return {"ok": True, "output": f"{rel}:{start}-{min(end, len(lines))}\n{body}"}

def search_source_code(args):
    query = args.get("query", "")
    if not isinstance(query, str) or len(query.strip()) < 2 or len(query) > 180 or "\n" in query:
        return {"ok": False, "output": "query must be a 2-180 character single-line literal"}
    try:
        path = safe_relative_path(args.get("path", "."))
        limit = max(1, min(int(args.get("limit", 60)), 120))
    except (ValueError, TypeError) as exc:
        return {"ok": False, "output": f"Invalid search arguments: {exc}"}
    args_git = ["grep", "-n", "-I", "-F", "--no-color", "-e", query, "--"]
    if path != ".":
        args_git.append(path)
    result = run_git(args_git, timeout=90)
    if result["exit"] == 1:
        return {"ok": True, "output": f"No literal matches for {query!r} under {path}"}
    if not result["ok"]:
        return result
    lines = result["output"].splitlines()
    shown = lines[:limit]
    out = "\n".join(shown)
    if len(lines) > limit:
        out += f"\n...[{len(lines) - limit} additional matches omitted; narrow the path or search term]"
    return {"ok": True, "output": out[:MAX_TOOL_OUTPUT]}

def run_static_probe(args):
    probe = args.get("probe", "")
    pattern = PROBES.get(probe)
    if not pattern:
        return {"ok": False, "output": "Unknown probe. Available: " + ", ".join(sorted(PROBES))}
    try:
        path = safe_relative_path(args.get("path", "."))
        limit = max(1, min(int(args.get("limit", 60)), 100))
    except (ValueError, TypeError) as exc:
        return {"ok": False, "output": f"Invalid probe arguments: {exc}"}
    git_args = ["grep", "-n", "-I", "-E", "--no-color", "-e", pattern, "--"]
    if path != ".":
        git_args.append(path)
    result = run_git(git_args, timeout=120)
    if result["exit"] == 1:
        return {"ok": True, "output": f"Probe {probe}: no matches under {path}"}
    if not result["ok"]:
        return result
    matches = result["output"].splitlines()
    out = "\n".join(matches[:limit])
    if len(matches) > limit:
        out += f"\n...[{len(matches) - limit} more matches omitted; this probe is only a lead]"
    return {"ok": True, "output": f"Probe: {probe} (leads only; not findings)\n{out}"[:MAX_TOOL_OUTPUT]}

def source_metadata(repo, ref, file_count):
    commit = run_git(["rev-parse", "HEAD"])
    subject = run_git(["log", "-1", "--format=%s"])
    return {
        "ok": True,
        "output": f"Repository: {repo}\nRequested ref: {ref}\nCommit: {commit['output']}\nLatest commit subject: {subject['output']}\nTracked files: {file_count}",
    }

def initialize_source(job):
    global SOURCE_ROOT
    repo = validate_target_repo(job.get("target_repo", "torvalds/linux"))
    ref = validate_ref(job.get("target_ref", "master"))
    parent = Path(base.pick_workdir(min_gb=8.0)) / "security-research"
    source = parent / "source"
    parent.mkdir(parents=True, exist_ok=True)
    if source.exists():
        import shutil
        shutil.rmtree(source)
    url = f"https://github.com/{repo}.git"
    print(f"[research] cloning {repo}@{ref}", flush=True)
    result = subprocess.run(
        ["git", "clone", "--depth", "1", "--single-branch", "--branch", ref, url, str(source)],
        text=True, capture_output=True, timeout=1800, check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git clone failed")[-3000:]
        raise RuntimeError(f"Could not clone {repo}@{ref}: {detail}")
    SOURCE_ROOT = source.resolve()
    files = run_git(["ls-files"])
    count = len(files["output"].splitlines()) if files["ok"] else 0
    return repo, ref, count

def dispatch_tool(name, args, meta):
    if name == "list_source_files":
        return list_source_files(args)
    if name == "read_source_file":
        return read_source_file(args)
    if name == "search_source_code":
        return search_source_code(args)
    if name == "run_static_probe":
        return run_static_probe(args)
    if name == "get_source_metadata":
        return {"ok": True, "output": meta}
    return {"ok": False, "output": f"Tool not available: {name}"}

def run_research_agent(job, repo, ref, file_count):
    prompt = (job.get("research_prompt") or "").strip()
    if not prompt:
        prompt = (
            "Conduct a focused but deep source audit of the repository. Begin by understanding the subsystem and identifying security-sensitive components. "
            "Choose a coherent subsystem, inspect its entry points and data structures, trace relevant paths, and report only evidence-backed candidates. "
            "Do not claim that the entire repository was audited."
        )
    scope = job.get("target_subdir", ".") or "."
    try:
        scope = safe_relative_path(scope)
    except ValueError as exc:
        raise ValueError(f"Invalid target_subdir: {exc}")
    meta = source_metadata(repo, ref, file_count)["output"]
    if scope != ".":
        candidate = (SOURCE_ROOT / scope).resolve()
        try:
            candidate.relative_to(SOURCE_ROOT.resolve())
        except ValueError:
            raise ValueError("target_subdir escapes repository")
        if not candidate.exists():
            raise ValueError(f"target_subdir does not exist: {scope}")
    context = (
        f"\n\nResearch target metadata:\n{meta}\n"
        f"Requested analysis scope: {scope}\n"
        "The source tree is read-only. Use the available tools to inspect it. "
        "Begin with repository mapping, then narrow to a tractable subsystem. "
        "A static probe is only a search aid; validate each lead manually in surrounding code. "
        "Record exact path and line numbers from tool output. Do not imply exhaustive coverage."
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT + context},
        {"role": "user", "content": prompt},
    ]
    max_steps = max(1, min(int(job.get("max_steps", 40)), 80))
    max_tokens = max(512, min(int(job.get("max_tokens", 3072)), 8192))
    thinking = bool(job.get("thinking", True))
    budget = base.context_budget({"ctx": job.get("ctx", 16384), "max_tokens": max_tokens})
    used_steps = 0
    total_tokens = 0
    final_text = ""
    for _ in range(max_steps):
        base.trim_agent_context(messages, budget)
        response = base.chat_full(base.LLM_URL, messages, max_tokens, thinking, RESEARCH_TOOLS, temperature=0.25)
        total_tokens += int((response.get("usage") or {}).get("completion_tokens", 0) or 0)
        calls = response.get("tool_calls") or []
        if not calls:
            final_text = response.get("content") or ""
            break
        messages.append({"role": "assistant", "content": response.get("content") or "", "tool_calls": calls})
        for call in calls:
            fn = call.get("function") or {}
            name = fn.get("name", "")
            raw = fn.get("arguments") or {}
            try:
                args = json.loads(raw) if isinstance(raw, str) else raw
            except ValueError:
                args = {}
            if not isinstance(args, dict):
                args = {}
            result = dispatch_tool(name, args, meta)
            messages.append({
                "role": "tool",
                "tool_call_id": call.get("id", ""),
                "content": base.model_view(result, name, limit=2500),
            })
            used_steps += 1
            print(f"[research] step {used_steps}/{max_steps}: {name} ({'ok' if result.get('ok') else 'error'})", flush=True)
        if used_steps >= max_steps:
            break
    if not final_text:
        base.trim_agent_context(messages, budget)
        messages.append({"role": "user", "content": "Stop using tools and produce the best evidence-based Markdown report possible now. Clearly list what remains unverified."})
        response = base.chat_full(base.LLM_URL, messages, max_tokens, thinking, None, temperature=0.2)
        total_tokens += int((response.get("usage") or {}).get("completion_tokens", 0) or 0)
        final_text = response.get("content") or "Research ended before a report could be generated."
    return final_text, used_steps, total_tokens

def main():
    os.makedirs(base.OUT, exist_ok=True)
    proc = None
    try:
        repo, ref, file_count = initialize_source(JOB)
        print(f"[research] cloned {repo}@{ref}; tracked files={file_count}", flush=True)
        proc = base.start_llama(JOB)
        report, steps, tokens = run_research_agent(JOB, repo, ref, file_count)
        commit = run_git(["rev-parse", "HEAD"])["output"]
        header = (
            f"# Defensive source audit\n\n"
            f"- Repository: {repo}\n- Requested ref: {ref}\n"
            f"- Resolved commit: {commit}\n- Tracked files: {file_count}\n"
            f"- Model: {JOB.get('model_repo')}\n- Tool calls: {steps}\n"
            f"- Completion tokens: {tokens}\n- Mode: read-only source inspection; no target code executed\n\n---\n\n"
        )
        full_report = header + report.strip() + "\n"
        report_path = Path(base.OUT) / "security-research-report.md"
        report_path.write_text(full_report, encoding="utf-8")
        (Path(base.OUT) / "result.txt").write_text(
            f"Research completed for {repo}@{ref}.\nTool calls: {steps}. Completion tokens: {tokens}.\n"
            "The detailed report is security-research-report.md. Review every candidate before disclosure.",
            encoding="utf-8",
        )
        (Path(base.OUT) / "research-metadata.json").write_text(json.dumps({
            "repository": repo, "requested_ref": ref, "commit": commit,
            "tracked_files": file_count, "tool_calls": steps, "completion_tokens": tokens,
            "model_repo": JOB.get("model_repo"), "read_only": True,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[research] report saved: {report_path}; findings are not printed to workflow logs", flush=True)
    except Exception as exc:
        message = f"Security research failed: {type(exc).__name__}: {exc}"
        Path(base.OUT).mkdir(parents=True, exist_ok=True)
        (Path(base.OUT) / "result.txt").write_text(message, encoding="utf-8")
        raise
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()

if __name__ == "__main__":
    main()
