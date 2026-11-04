#!/usr/bin/env python3
"""Executor: סביבת עבודה (bash / python / java ...) על runner של GitHub Actions.

המודל ב-Kaggle (ה-"מוח") מבקש להריץ פעולות בכך שהוא כותב תגובות עם הסמן <!--tool-call:ID--> ב-Issue של השיחה.
ה-executor מריץ אותן ומחזיר תגובה עם <!--tool-result:ID-->.

אבטחה:
  * מקבל פקודות רק מתגובות של github-actions[bot] בתוך Issues שנפתחו על ידי בעל הריפו.
  * כל פקודות ה-Workspace רצות כ-root דרך sudo.
  * סביבת התהליך מועברת לפקודות, ולכן משתני הסביבה הזמינים ל-executor (כולל GH_TOKEN) נגישים גם לפקודות ה-Workspace.
  * יש להתייחס לכל בקשת Workspace כקוד בעל הרשאות מלאות על ה-runner.
  * הקבצים מסונכרנים לענף workspace בריפו.

הרצה:  python scripts/executor.py              (לולאה ראשית)
        python scripts/executor.py --sync-only  (סנכרון אחרון, גם אחרי ביטול)
"""
import argparse
import base64
import json
import os
import platform
import re
import shutil
import shlex
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

import requests

BOT_LOGIN = "github-actions[bot]"
STATUS_TITLE = "[executor-status]"
BRANCH = "workspace"
SANDBOX = "sandbox"
LOCAL = os.environ.get("LOCAL_TEST") == "1"          # לבדיקות מקומיות בלבד: בלי sudo ובלי משתמש נפרד

CALL_RE = re.compile(r"^<!--tool-call:([0-9a-f]{6,16})-->\n(.*)$", re.S)
RESULT_RE = re.compile(r"^<!--tool-result:([0-9a-f]{6,16})-->")
MAX_CALL_AGE = 600           # שניות: לא מריצים פקודות ישנות
OUT_LIMIT = 20000
RSYNC_EXCLUDES = [".git", "node_modules", "__pycache__", ".venv", "venv", "target", "*.class", ".cache", ".gradle", ".m2", ".npm"]

stop_flag = False


def paths():
    if LOCAL:
        base = os.environ["LOCAL_BASE"]
        return {"work": f"{base}/work", "out": f"{base}/out", "repo": f"{base}/repo", "home": f"{base}/home"}
    return {"work": f"/home/{SANDBOX}/work", "out": f"/home/{SANDBOX}/.out", "repo": "/home/runner/ws-repo",
            "home": f"/home/{SANDBOX}"}


P = paths()
SUDO = [] if LOCAL else ["sudo", "-n"]


def log(*a):
    print("[executor]", *a, flush=True)


# ---------------------------------------------------------------------------- GitHub API
class GH:
    def __init__(self, repo, token, api="https://api.github.com"):
        self.repo, self.api = repo, api.rstrip("/")
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                               "X-GitHub-Api-Version": "2022-11-28"})

    def call(self, method, path, json_body=None, etag=None, params=None):
        headers = {"If-None-Match": etag} if etag else {}
        r = self.s.request(method, f"{self.api}/repos/{self.repo}{path}", json=json_body, params=params,
                           headers=headers, timeout=30)
        if r.status_code == 304:
            return 304, None, etag
        try:
            data = r.json() if r.content else None
        except ValueError:
            data = None
        return r.status_code, data, r.headers.get("ETag")


def find_status(gh):
    st, data, _ = gh.call("GET", "/issues", params={"state": "open", "per_page": 100, "sort": "created", "direction": "asc"})
    for i in data or []:
        if i.get("title") == STATUS_TITLE and "pull_request" not in i:
            return i["number"]
    return None


def ensure_status(gh):
    n = find_status(gh)
    if n:
        return n
    st, data, _ = gh.call("POST", "/issues", {"title": STATUS_TITLE, "body": "starting"})
    if st != 201:
        raise RuntimeError(f"cannot create status issue: HTTP {st}: {data}")
    return data["number"]


def heartbeat(gh, number, state):
    payload = {"state": state, "ts": int(time.time())}
    gh.call("PATCH", f"/issues/{number}", {"body": "Executor status (updated automatically)\n\n```json\n" + json.dumps(payload) + "\n```"})


def read_state(gh, number):
    st, data, _ = gh.call("GET", f"/issues/{number}")
    if st != 200 or not data:
        return ""
    m = re.search(r"\{[^{}]*\}", data.get("body") or "")
    try:
        return json.loads(m.group(0)).get("state", "") if m else ""
    except ValueError:
        return ""


def all_comments(gh, number, since=None):
    res, page = [], 1
    while True:
        params = {"per_page": 100, "page": page}
        if since:
            params["since"] = since
        st, data, _ = gh.call("GET", f"/issues/{number}/comments", params=params)
        if st != 200:
            raise RuntimeError(f"comments HTTP {st}: {data}")
        res += data or []
        if not data or len(data) < 100:
            return res
        page += 1


# ---------------------------------------------------------------------------- sandbox
def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def setup_sandbox():
    if LOCAL:
        os.makedirs(P["work"], exist_ok=True)
        os.makedirs(P["out"], exist_ok=True)
        return
    # Create the sandbox account first; useradd -m creates /home/sandbox.
    # The runner user cannot create that home directory directly.
    steps = [
        ["sudo", "-n", "useradd", "-m", "-s", "/bin/bash", SANDBOX],
        ["sudo", "-n", "chmod", "755", f"/home/{SANDBOX}"],
        ["sudo", "-n", "install", "-d", "-o", SANDBOX, "-g", SANDBOX, "-m", "755", P["work"], P["out"]],
        # המשתמש המבודד לא יכול לגשת לתיקיית הבית של ה-runner (קבצי ה-runner, אישורים)
        ["sudo", "-n", "chmod", "700", "/home/runner"],
        # חסימת שירות המטא-דאטה של הענן עבור המשתמש המבודד
        ["sudo", "-n", "iptables", "-A", "OUTPUT", "-m", "owner", "--uid-owner", SANDBOX, "-d", "169.254.169.254", "-j", "REJECT"],
    ]
    for c in steps:
        r = sh(c)
        if r.returncode != 0 and "already exists" not in (r.stderr or ""):
            log("setup warning:", " ".join(c), "->", (r.stderr or "").strip()[:200])


def safe_path(rel):
    """Resolve a workspace path and reject traversal, including symlink escapes."""
    if not isinstance(rel, str) or not rel.strip():
        return None
    rel = rel.strip()
    if rel == ".":
        return P["work"]
    if rel.startswith(P["work"] + "/"):
        rel = rel[len(P["work"]) + 1:]
    rel = rel.lstrip("/")
    parts = [x for x in rel.split("/") if x not in ("", ".")]
    if not parts or ".." in parts or "\x00" in rel:
        return None
    candidate = os.path.abspath(os.path.join(P["work"], *parts))
    base = os.path.realpath(P["work"])
    resolved = os.path.realpath(candidate)
    try:
        if os.path.commonpath((base, resolved)) != base:
            return None
    except ValueError:
        return None
    return candidate


def list_files(path=".", limit=200):
    ap = safe_path(path or ".")
    if ap is None:
        return {"ok": False, "exit": 1, "output": "נתיב לא חוקי"}
    if not os.path.isdir(ap):
        return {"ok": False, "exit": 1, "output": f"לא תיקייה: {path}"}
    try:
        limit = max(1, min(int(limit or 200), 500))
        names = sorted(os.listdir(ap), key=str.casefold)
    except (OSError, TypeError, ValueError) as e:
        return {"ok": False, "exit": 1, "output": str(e)[:500]}
    rows = []
    for name in names[:limit]:
        full = os.path.join(ap, name)
        try:
            if os.path.islink(full):
                kind, size = "LINK", ""
            elif os.path.isdir(full):
                kind, size = "DIR ", ""
            else:
                kind, size = "FILE", f" ({os.path.getsize(full)} B)"
            rows.append(f"[{kind}] {name}{size}")
        except OSError:
            rows.append(f"[????] {name}")
    suffix = f"\n... ועוד {len(names) - limit} פריטים" if len(names) > limit else ""
    return {"ok": True, "exit": 0, "output": "\n".join(rows) + suffix or "(תיקייה ריקה)"}


def search_files(query, path=".", limit=50):
    if not isinstance(query, str) or not query.strip():
        return {"ok": False, "exit": 1, "output": "חסר query"}
    root = safe_path(path or ".")
    if root is None or not os.path.isdir(root):
        return {"ok": False, "exit": 1, "output": "נתיב חיפוש לא חוקי או לא קיים"}
    try:
        limit = max(1, min(int(limit or 50), 200))
    except (TypeError, ValueError):
        limit = 50
    ignored = {".git", "node_modules", "__pycache__", ".venv", "venv", "build", "dist", ".gradle", ".cache"}
    needle = query.casefold()
    matches = []
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if d not in ignored and not os.path.islink(os.path.join(current, d))]
        for name in sorted(files, key=str.casefold):
            full = os.path.join(current, name)
            if os.path.islink(full):
                continue
            try:
                if os.path.getsize(full) > 1_000_000:
                    continue
                with open(full, "rb") as fh:
                    raw = fh.read(1_000_001)
                if b"\x00" in raw[:4096]:
                    continue
                decoded = raw.decode("utf-8", errors="replace")
            except OSError:
                continue
            for line_no, line in enumerate(decoded.splitlines(), 1):
                if needle in line.casefold():
                    rel = os.path.relpath(full, P["work"])
                    snippet = line.strip()
                    if len(snippet) > 300:
                        snippet = snippet[:297] + "..."
                    matches.append(f"{rel}:{line_no}: {snippet}")
                    if len(matches) >= limit:
                        return {"ok": True, "exit": 0, "output": "\n".join(matches) + "\n... הגעה למגבלת התוצאות"}
    return {"ok": True, "exit": 0, "output": "\n".join(matches) if matches else "לא נמצאו התאמות"}


def get_environment():
    facts = [
        f"OS: {platform.system()} {platform.release()}",
        f"Architecture: {platform.machine()}",
        f"Python: {platform.python_version()}",
        f"CPU count: {os.cpu_count()}",
    ]
    try:
        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.lower().startswith(("model name", "hardware", "cpu model")) and ":" in line:
                    facts.append("CPU model: " + line.split(":", 1)[1].strip())
                    break
    except OSError:
        pass
    try:
        with open("/proc/meminfo", encoding="ascii", errors="replace") as fh:
            mem = next((line for line in fh if line.startswith("MemTotal:")), "")
        if mem:
            facts.append("RAM: " + mem.split(":", 1)[1].strip())
    except OSError:
        pass
    try:
        usage = shutil.disk_usage(P["work"])
        facts.append(f"Workspace disk: total {usage.total // (1024**3)} GiB, free {usage.free // (1024**3)} GiB")
    except OSError:
        pass
    for program, flag in (("java", "-version"), ("node", "--version"), ("gcc", "--version"), ("git", "--version")):
        binary = shutil.which(program)
        if not binary:
            facts.append(f"{program}: not installed")
            continue
        try:
            r = subprocess.run([binary, flag], capture_output=True, text=True, timeout=5)
            value = (r.stdout or r.stderr).strip().splitlines()
            facts.append(f"{program}: {value[0][:180] if value else 'available'}")
        except (OSError, subprocess.TimeoutExpired):
            facts.append(f"{program}: version check failed")
    return {"ok": True, "exit": 0, "output": "\n".join(facts)}


def trunc(text, limit=OUT_LIMIT):
    if len(text) <= limit:
        return text
    h = limit // 2
    return text[:h] + f"\n...[נחתכו {len(text) - limit} תווים]...\n" + text[-h:]


def tool_env():
    keep = {"HOME": P["home"], "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8", "CI": "true"}
    if os.environ.get("JAVA_HOME"):
        keep["JAVA_HOME"] = os.environ["JAVA_HOME"]
    return [f"{k}={v}" for k, v in keep.items()]


def run_bash(cid, command, timeout):
    script = os.path.join(P["out"], f"{cid}.sh")
    out = os.path.join(P["out"], f"{cid}.txt")
    w = sh(SUDO + ["tee", script], input=command + "\n", timeout=30)
    if w.returncode != 0:
        return {"ok": False, "exit": -1, "output": "cannot write script: " + (w.stderr or "")[:300]}
    inner = (f"ulimit -u 4096 2>/dev/null; cd {shlex.quote(P['work'])} && "
             f"timeout -k 5 {int(timeout)} bash {shlex.quote(script)} > {shlex.quote(out)} 2>&1")
    t0 = time.time()
    try:
        # Run as root and preserve the executor environment (including GH_TOKEN).
        # This intentionally gives Workspace commands full runner-level privileges.
        r = subprocess.run(SUDO + (["-E"] if not LOCAL else []) + ["bash", "-c", inner],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                           text=True, timeout=timeout + 20)
        code = r.returncode
    except subprocess.TimeoutExpired:
        code = 124
    ms = int((time.time() - t0) * 1000)
    try:
        with open(out, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        text = ""
    if code == 124:
        text += f"\n[הפקודה הופסקה אחרי {timeout} שניות]"
    return {"ok": code == 0, "exit": code, "output": trunc(text), "ms": ms}


def write_file(path, content):
    ap = safe_path(path)
    if ap is None:
        return {"ok": False, "exit": 1, "output": f"נתיב לא חוקי: {path!r} (השתמש בנתיב יחסי בתוך סביבת העבודה)"}
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False, indent=2)
    r = sh(SUDO + ["bash", "-c", 'mkdir -p -- "$(dirname -- "$1")" && cat > "$1"', "_", ap],
           input=content, timeout=30)
    if r.returncode != 0:
        return {"ok": False, "exit": r.returncode, "output": (r.stderr or "write failed")[:500]}
    return {"ok": True, "exit": 0, "output": f"נכתב {os.path.relpath(ap, P['work'])} ({len(content.encode('utf-8'))} בתים)"}


def read_file(path):
    ap = safe_path(path)
    if ap is None:
        return {"ok": False, "exit": 1, "output": f"נתיב לא חוקי: {path!r}"}
    r = sh(SUDO + ["head", "-c", str(OUT_LIMIT + 1), "--", ap], timeout=30)
    if r.returncode != 0:
        return {"ok": False, "exit": r.returncode, "output": (r.stderr or "read failed").strip()[:500]}
    return {"ok": True, "exit": 0, "output": trunc(r.stdout)}


def run_tool(cid, payload):
    tool = payload.get("tool")
    a = payload.get("args") or {}
    if not isinstance(a, dict):
        a = {}
    if tool == "bash":
        try:
            t = max(1, min(int(a.get("timeout") or 120), 600))
        except (TypeError, ValueError):
            t = 120
        cmd = a.get("command")
        if not isinstance(cmd, str) or not cmd.strip():
            return {"ok": False, "exit": 1, "output": "חסר command"}
        return run_bash(cid, cmd, t)
    if tool == "write_file":
        return write_file(a.get("path"), a.get("content", ""))
    if tool == "read_file":
        return read_file(a.get("path"))
    if tool == "list_files":
        return list_files(a.get("path", "."), a.get("limit", 200))
    if tool == "search_files":
        return search_files(a.get("query"), a.get("path", "."), a.get("limit", 50))
    if tool == "get_environment":
        return get_environment()
    return {"ok": False, "exit": 1, "output": f"כלי לא מוכר: {tool}"}


# ---------------------------------------------------------------------------- sync with branch
def git_env(token):
    b = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    env = dict(os.environ)
    env.update({"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
                "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {b}", "GIT_TERMINAL_PROMPT": "0"})
    return env


def git(args, cfg, check=False):
    r = sh(["git", "-C", P["repo"]] + args, env=git_env(cfg["token"]) if cfg.get("token") else None)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {(r.stderr or r.stdout).strip()[:300]}")
    return r


def prepare_repo(cfg):
    """משכפל את ענף workspace (או יוצר ענף ריק) לתיקיית הסנכרון."""
    if os.path.isdir(os.path.join(P["repo"], ".git")):
        return True
    url = cfg["remote"]
    r = sh(["git", "clone", "--depth", "1", "--branch", BRANCH, url, P["repo"]], env=git_env(cfg["token"]))
    existed = r.returncode == 0
    if not existed:
        sh(["rm", "-rf", P["repo"]])
        os.makedirs(P["repo"], exist_ok=True)
        sh(["git", "-C", P["repo"], "init", "-q", "-b", BRANCH])
        sh(["git", "-C", P["repo"], "remote", "add", "origin", url])
    sh(["git", "-C", P["repo"], "config", "user.name", "workspace-bot"])
    sh(["git", "-C", P["repo"], "config", "user.email", "workspace-bot@users.noreply.github.com"])
    return existed


def rsync(src, dst, chown=None, delete=False):
    cmd = ["rsync", "-a", "--max-size=5m"]
    if delete:
        cmd.append("--delete")
    for e in RSYNC_EXCLUDES:
        cmd += ["--exclude", e]
    if chown:
        cmd.append(f"--chown={chown}")
    cmd += [src.rstrip("/") + "/", dst.rstrip("/") + "/"]
    if not LOCAL:
        cmd = ["sudo", "-n"] + cmd
    return sh(cmd)


def restore(cfg):
    existed = prepare_repo(cfg)
    if existed:
        r = rsync(P["repo"], P["work"], chown=None if LOCAL else f"{SANDBOX}:{SANDBOX}")
        log("workspace restored from branch" if r.returncode == 0 else f"restore warning: {r.stderr[:200]}")
    else:
        log("no workspace branch yet, starting empty")


def sync(cfg, message="workspace sync"):
    if not os.path.isdir(os.path.join(P["repo"], ".git")):
        return False
    r = rsync(P["work"], P["repo"], chown=None if LOCAL else f"{os.environ.get('USER', 'runner')}:{os.environ.get('USER', 'runner')}", delete=True)
    if r.returncode not in (0, 23, 24):
        log("rsync warning:", (r.stderr or "")[:200])
    git(["add", "-A"], cfg)
    if not git(["status", "--porcelain"], cfg).stdout.strip():
        return False
    c = git(["commit", "-q", "-m", message], cfg)
    if c.returncode != 0:
        log("commit failed:", (c.stderr or c.stdout)[:200])
        return False
    p = git(["push", "-q", "origin", f"HEAD:refs/heads/{BRANCH}"], cfg)
    if p.returncode != 0:
        log("push failed:", (p.stderr or p.stdout)[:300])
        return False
    log("workspace synced to branch", BRANCH)
    return True


# ---------------------------------------------------------------------------- main loop
def parse_ts(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


def classify(comments, done, owner_ok):
    """מחזיר רשימת (id, payload, comment) של בקשות שממתינות לביצוע, ומעדכן done לפי תוצאות שכבר קיימות."""
    # קודם אוספים את כל התוצאות הקיימות, כדי שבקשה שכבר נענתה לא תורץ שוב
    for c in comments:
        if (c.get("user") or {}).get("login") == BOT_LOGIN:
            m = RESULT_RE.match(c.get("body") or "")
            if m:
                done.add(m.group(1))
    pending = []
    for c in comments:
        if (c.get("user") or {}).get("login") != BOT_LOGIN:
            continue
        m = CALL_RE.match(c.get("body") or "")
        if not m or not owner_ok:
            continue
        cid = m.group(1)
        if cid in done:
            continue
        try:
            age = time.time() - parse_ts(c["created_at"])
        except (KeyError, ValueError):
            age = 0
        if age > MAX_CALL_AGE:
            done.add(cid)
            continue
        try:
            payload = json.loads(m.group(2))
        except ValueError:
            payload = {"tool": "invalid"}
        # Windows requests are handled only by executor_windows.py.
        if str(payload.get("tool", "")).startswith("win_"):
            continue
        pending.append((cid, payload, c))
    return pending


def main_loop(gh, cfg):
    global stop_flag
    owner = cfg["owner"].lower()
    idle_s = float(cfg.get("idle_minutes", 45)) * 60
    max_s = float(cfg.get("max_hours", 5.5)) * 3600
    poll_active = float(cfg.get("poll_active", 2))
    poll_idle = float(cfg.get("poll_idle", 6))
    hb_every = float(cfg.get("heartbeat_seconds", 60))
    sync_every = float(cfg.get("sync_seconds", 120))

    status_no = ensure_status(gh)
    heartbeat(gh, status_no, "online")
    log(f"online, status issue #{status_no}, owner={owner}")

    t0 = last_act = last_hb = last_sync = time.time()
    etag, seen, since, done = None, {}, {}, set()
    dirty, reason = False, "unknown"
    while True:
        now = time.time()
        if stop_flag:
            reason = "signal"; break
        if now - t0 > max_s:
            reason = "max-time"; break
        if now - last_act > idle_s:
            reason = "idle"; break
        if now - last_hb > hb_every:
            last_hb = now
            try:
                if read_state(gh, status_no) == "stop":
                    reason = "stop-requested"; break
                heartbeat(gh, status_no, "online")
            except Exception as e:  # noqa: BLE001
                log("heartbeat error:", e)
        if dirty and now - last_sync > sync_every:
            last_sync = now
            try:
                sync(cfg); dirty = False
            except Exception as e:  # noqa: BLE001
                log("sync error:", e)
        try:
            st, issues, new_etag = gh.call("GET", "/issues", etag=etag, params={
                "labels": "chat", "state": "open", "per_page": 50, "sort": "updated"})
            if st in (401, 403):
                reason = f"auth-error-{st}"; break
            if st == 200:
                for issue in issues or []:
                    if "pull_request" in issue:
                        continue
                    n = issue["number"]
                    if seen.get(n) == issue["updated_at"]:
                        continue
                    owner_ok = (issue.get("user") or {}).get("login", "").lower() == owner
                    comments = all_comments(gh, n, since.get(n))
                    for c in comments:
                        since[n] = max(since.get(n, ""), c.get("updated_at", ""))
                    for cid, payload, c in classify(comments, done, owner_ok):
                        done.add(cid)
                        log(f"#{n} run {payload.get('tool')} [{cid}]")
                        try:
                            res = run_tool(cid, payload)
                        except Exception as e:  # noqa: BLE001
                            res = {"ok": False, "exit": -1, "output": f"שגיאה פנימית: {e}"}
                        body = f"<!--tool-result:{cid}-->\n" + json.dumps(res, ensure_ascii=False)
                        st2, d2, _ = gh.call("POST", f"/issues/{n}/comments", {"body": body[:60000]})
                        if st2 != 201:
                            raise RuntimeError(f"post result HTTP {st2}: {d2}")
                        last_act = time.time(); dirty = True
                    seen[n] = issue["updated_at"]
                etag = new_etag
            elif st != 304:
                raise RuntimeError(f"GitHub API HTTP {st}: {issues}")
        except Exception as e:  # noqa: BLE001
            log("error:", e)
            etag = None
            time.sleep(8)
        time.sleep(poll_active if time.time() - last_act < 300 else poll_idle)

    try:
        sync(cfg, "workspace final sync")
    except Exception as e:  # noqa: BLE001
        log("final sync error:", e)
    try:
        heartbeat(gh, status_no, "offline")
    except Exception:  # noqa: BLE001
        pass
    log(f"stopped: {reason}")
    return reason


def config():
    repo = os.environ["REPO"]
    return {
        "repo": repo,
        "token": os.environ["GH_TOKEN"],
        "owner": os.environ["OWNER"],
        "remote": os.environ.get("REMOTE_URL", f"https://github.com/{repo}.git"),
        "idle_minutes": float(os.environ.get("IDLE_MINUTES") or 45),
        "max_hours": float(os.environ.get("MAX_HOURS") or 5.5),
    }


def main():
    global stop_flag
    ap = argparse.ArgumentParser()
    ap.add_argument("--sync-only", action="store_true")
    args = ap.parse_args()
    cfg = config()

    def handler(signum, frame):
        global stop_flag
        stop_flag = True
    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)

    if args.sync_only:
        if os.path.isdir(os.path.join(P["repo"], ".git")) and os.path.isdir(P["work"]):
            sync(cfg, "workspace final sync")
        else:
            log("nothing to sync")
        return

    setup_sandbox()
    restore(cfg)
    gh = GH(cfg["repo"], cfg["token"], os.environ.get("API_URL", "https://api.github.com"))
    main_loop(gh, cfg)


if __name__ == "__main__":
    main()
