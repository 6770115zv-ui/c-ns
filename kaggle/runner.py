# -*- coding: utf-8 -*-
# רץ בתוך Kaggle. המשתנה JOB מוזרק בראש הקובץ על ידי scripts/push_to_kaggle.py
#
# שני מצבים:
#   mode == "task"   : משימה אחת, תשובה נשמרת ל-result.txt וקבצי קוד ל-files/
#   mode == "worker" : שרת צ'אט קבוע, קורא הודעות מ-Issues בריפו ועונה בתגובות
import glob
import json
import os
import re
import shutil
import subprocess
import tarfile
import time
import urllib.request
import uuid

import requests

JOB = globals().get("JOB", {})

OUT = os.environ.get("OUT_DIR", "/kaggle/working")
RELEASE_URL = "https://github.com/{repo}/releases/download/llama-cuda12-sm75/llama-bin.tar.gz"
LLM_URL = "http://127.0.0.1:8080"

MARKER = "<!--llm-reply-->"
STREAM_MARKER = "<!--llm-streaming-->"
STOP_MARKER = "<!--llm-stop:"
STATUS_TITLE = "[worker-status]"
EXECUTOR_TITLE = "[executor-status]"
WINDOWS_EXECUTOR_TITLE = "[windows-executor-status]"
BOT_LOGIN = "github-actions[bot]"
FOOTER_RE = re.compile(r"\n\n<sub>.*?</sub>\s*$", re.S)
DETAILS_RE = re.compile(r"<details>.*?</details>", re.S)


# ----------------------------------------------------------------------------
# כלים כלליים
# ----------------------------------------------------------------------------
def sh(cmd: str) -> str:
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return (r.stdout + r.stderr).strip()


def free_gb(path: str) -> float:
    os.makedirs(path, exist_ok=True)
    return shutil.disk_usage(path).free / 1e9


def pick_workdir(min_gb: float = 40.0) -> str:
    for cand in ("/kaggle/temp", "/tmp"):
        g = free_gb(cand)
        print(f"[disk] {cand}: {g:.0f} GB free", flush=True)
        if g >= min_gb:
            return cand
    raise SystemExit("No directory with enough free disk space for the model")


# ----------------------------------------------------------------------------
# חילוץ קוד מתשובה
# ----------------------------------------------------------------------------
EXT = {
    "html": "html", "htm": "html", "css": "css", "js": "js", "javascript": "js", "jsx": "jsx",
    "ts": "ts", "typescript": "ts", "tsx": "tsx", "python": "py", "py": "py", "java": "java",
    "kotlin": "kt", "bash": "sh", "sh": "sh", "shell": "sh", "zsh": "sh", "json": "json",
    "yaml": "yml", "yml": "yml", "xml": "xml", "sql": "sql", "c": "c", "cpp": "cpp", "c++": "cpp",
    "csharp": "cs", "c#": "cs", "go": "go", "rust": "rs", "php": "php", "md": "md",
    "markdown": "md", "text": "txt", "txt": "txt", "": "txt",
}
FENCE_RE = re.compile(r"```([\w+#.-]*)[^\n]*\n(.*?)(```|\Z)", re.S)
NAME_RE = re.compile(r"^\s*(?://|#|<!--|/\*|--)\s*(?:file(?:name)?|path)\s*:\s*([\w./-]+)", re.I)


def extract_code(text: str):
    """מחזיר רשימת {name, content, complete} לכל בלוק קוד בתשובה."""
    out, used = [], set()

    def unique(name: str) -> str:
        base, dot, ext = name.rpartition(".")
        if not dot:
            base, ext = name, ""
        cand, i = name, 2
        while cand in used:
            cand = f"{base}_{i}.{ext}" if ext else f"{base}_{i}"
            i += 1
        used.add(cand)
        return cand

    n = 0
    for m in FENCE_RE.finditer(text):
        lang = m.group(1).lower()
        body = m.group(2).rstrip("\n") + "\n"
        complete = m.group(3) == "```"
        if not body.strip():
            continue
        n += 1
        ext = EXT.get(lang, "txt")
        name = None
        mm = NAME_RE.match(body.splitlines()[0])
        if mm:
            cand = os.path.basename(mm.group(1))
            if cand and not cand.startswith("."):
                name = cand
        if name is None:
            if ext == "html" and not any(f["name"].startswith("index") for f in out):
                name = "index.html"
            else:
                name = f"code_{n}.{ext}"
        out.append({"name": unique(name), "content": body, "complete": complete})

    # תשובה שהיא HTML גולמי בלי גדרות ```
    if not out and text.lstrip().lower().startswith(("<!doctype html", "<html")):
        out.append({"name": "index.html", "content": text.strip() + "\n", "complete": "</html>" in text.lower()})
    return out


def save_files(files) -> None:
    if not files:
        return
    d = os.path.join(OUT, "files")
    os.makedirs(d, exist_ok=True)
    for f in files:
        with open(os.path.join(d, f["name"]), "w", encoding="utf-8") as fh:
            fh.write(f["content"])


# ----------------------------------------------------------------------------
# הפעלת llama-server
# ----------------------------------------------------------------------------
def start_llama(job: dict):
    print(sh("nvidia-smi"), flush=True)
    n_gpu = len([l for l in sh("nvidia-smi -L").splitlines() if l.startswith("GPU")])
    print(f"[gpu] count={n_gpu}", flush=True)
    print(sh("free -h"), flush=True)

    work = pick_workdir()
    bindir = os.path.join(work, "llama-bin")
    os.makedirs(bindir, exist_ok=True)

    url = RELEASE_URL.format(repo=job["release_repo"])
    print("[llama] downloading", url, flush=True)
    tgz = os.path.join(work, "llama-bin.tar.gz")
    try:
        urllib.request.urlretrieve(url, tgz)
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"Could not download llama binaries ({e}). Run the 'Build llama.cpp' workflow first.")
    with tarfile.open(tgz) as t:
        t.extractall(bindir)
    server = os.path.join(bindir, "llama-server")
    os.chmod(server, 0o755)

    from huggingface_hub import snapshot_download

    print("[model] downloading", job["model_repo"], job["model_pattern"], flush=True)
    t0 = time.time()
    mdir = snapshot_download(
        job["model_repo"],
        allow_patterns=[job["model_pattern"]],
        local_dir=os.path.join(work, "models"),
    )
    ggufs = sorted(glob.glob(os.path.join(mdir, "**", "*.gguf"), recursive=True))
    if not ggufs:
        raise SystemExit("No .gguf file matched the pattern")
    print(f"[model] done in {time.time() - t0:.0f}s:", ggufs, flush=True)
    gguf = ggufs[0]

    env = dict(os.environ)
    env["LD_LIBRARY_PATH"] = ":".join([bindir, "/usr/local/cuda/lib64", env.get("LD_LIBRARY_PATH", "")])
    cmd = [server, "-m", gguf, "-ngl", "99", "-c", str(job.get("ctx", 16384)), "-np", "1",
           "--jinja", "--host", "127.0.0.1", "--port", "8080"]
    if n_gpu > 1:
        cmd += ["--tensor-split", ",".join(["1"] * n_gpu)]
    log = open(os.path.join(OUT, "server.log"), "w")
    print("[server] starting:", " ".join(cmd), flush=True)
    proc = subprocess.Popen(cmd, env=env, stdout=log, stderr=subprocess.STDOUT)

    ok = False
    for _ in range(180):  # עד 15 דקות
        if proc.poll() is not None:
            break
        try:
            if requests.get(LLM_URL + "/health", timeout=3).status_code == 200:
                ok = True
                break
        except Exception:  # noqa: BLE001
            pass
        time.sleep(5)
    if not ok:
        log.flush()
        print(sh(f"tail -n 60 {OUT}/server.log"), flush=True)
        raise SystemExit("llama-server did not become healthy")
    print("[server] ready", flush=True)
    return proc


def chat_full(llm_url: str, messages, max_tokens: int, thinking: bool, tools=None,
              temperature: float = 0.6, on_delta=None):
    body = {
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "chat_template_kwargs": {"enable_thinking": bool(thinking)},
        "stream": True,
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"

    content, reasoning = [], []
    tool_calls = {}
    usage, finish = {}, None
    with requests.post(llm_url + "/v1/chat/completions", json=body,
                       stream=True, timeout=(15, 3600)) as r:
        if r.status_code >= 400:
            raise RuntimeError(f"LLM HTTP {r.status_code}: {r.text[:300]}")
        for raw in r.iter_lines(decode_unicode=True):
            if not raw:
                continue
            line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                event = json.loads(payload)
            except ValueError:
                continue
            if event.get("usage"):
                usage = event["usage"]
            choices = event.get("choices") or []
            if not choices:
                continue
            choice = choices[0]
            delta = choice.get("delta") or {}
            piece = delta.get("content")
            if isinstance(piece, str) and piece:
                content.append(piece)
            thought = delta.get("reasoning_content") or delta.get("reasoning")
            if isinstance(thought, str) and thought:
                reasoning.append(thought)
            for tc in delta.get("tool_calls") or []:
                idx = tc.get("index", 0)
                item = tool_calls.setdefault(idx, {"id": "", "type": "function",
                                                     "function": {"name": "", "arguments": ""}})
                if tc.get("id"):
                    item["id"] = tc["id"]
                if tc.get("type"):
                    item["type"] = tc["type"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    item["function"]["name"] += fn["name"]
                if fn.get("arguments"):
                    item["function"]["arguments"] += fn["arguments"]
            if choice.get("finish_reason") is not None:
                finish = choice["finish_reason"]
            if on_delta and (piece or thought):
                on_delta(piece or "", thought or "")

    return {
        "content": "".join(content),
        "reasoning": "".join(reasoning),
        "usage": usage,
        "finish": finish,
        "tool_calls": [tool_calls[k] for k in sorted(tool_calls)],
    }


def chat_complete(llm_url: str, messages, max_tokens: int, thinking: bool, tools=None,
                  temperature: float = 0.6, on_delta=None, before_request=None,
                  max_continuations: int = 32):
    """Generate in bounded chunks and automatically continue after each output-token boundary."""
    content_parts, reasoning_parts = [], []
    total_tokens = 0
    last = None
    for continuation in range(max_continuations + 1):
        if before_request:
            before_request()
        d = chat_full(llm_url, messages, max_tokens, thinking, tools, temperature, on_delta)
        last = d
        total_tokens += int((d.get("usage") or {}).get("completion_tokens", 0) or 0)
        if d.get("finish") != "length":
            d["content"] = "".join(content_parts) + (d.get("content") or "")
            d["reasoning"] = "".join(reasoning_parts) + (d.get("reasoning") or "")
            d["usage"] = {"completion_tokens": total_tokens}
            return d
        content_parts.append(d.get("content") or "")
        reasoning_parts.append(d.get("reasoning") or "")
        if continuation >= max_continuations:
            break
        # A cut-off tool call is deliberately not executed. Ask the model to finish
        # the answer or issue a fresh, complete tool call in the next segment.
        messages.append({"role": "assistant", "content": d.get("content") or ""})
        messages.append({"role": "user", "content":
            "המשך בדיוק מהמקום שבו הפסקת, בלי לחזור על הטקסט שכבר כתבת. "
            "אם נדרשת פעולה באמצעות כלי, שלח קריאת כלי חדשה ושלמה עם JSON תקין; "
            "אל תתייחס לקריאת כלי חלקית מהקטע הקודם."})
    last["content"] = "".join(content_parts)
    last["reasoning"] = "".join(reasoning_parts)
    last["usage"] = {"completion_tokens": total_tokens}
    last["finish"] = "length"
    return last


def chat(llm_url: str, messages, max_tokens: int, thinking: bool,
         temperature: float = 0.6, on_delta=None):
    d = chat_complete(llm_url, messages, max_tokens, thinking, None, temperature, on_delta)
    return d["content"], d["reasoning"], d["usage"], d["finish"]


# ----------------------------------------------------------------------------
# מצב משימה
# ----------------------------------------------------------------------------
def run_task(job: dict) -> None:
    messages = []
    if job.get("system"):
        messages.append({"role": "system", "content": job["system"]})
    messages.append({"role": "user", "content": job["prompt"]})

    t0 = time.time()
    text, reasoning, usage, finish = chat(LLM_URL, messages, job["max_tokens"], job.get("thinking", False))
    dt = time.time() - t0

    files = extract_code(text)
    save_files(files)

    out = text
    if reasoning:
        out += "\n\n---\n(reasoning)\n" + reasoning
    notes = []
    if finish == "length":
        notes.append("⚠️ התשובה הגיעה למספר מקטעי ההמשך המרבי. אפשר לבקש להמשיך.")
    elif any(not f["complete"] for f in files):
        notes.append("⚠️ אחד מבלוקי הקוד לא נסגר, ייתכן שהתשובה חלקית.")
    if files:
        notes.append("קבצים שחולצו: " + ", ".join(f["name"] for f in files))
    out += f"\n\n---\n{dt:.1f}s, usage: {usage}"
    if notes:
        out += "\n" + "\n".join(notes)

    with open(os.path.join(OUT, "result.json"), "w", encoding="utf-8") as f:
        json.dump({"content": text, "reasoning": reasoning, "usage": usage, "finish_reason": finish},
                  f, ensure_ascii=False, indent=2)
    with open(os.path.join(OUT, "result.txt"), "w", encoding="utf-8") as f:
        f.write(out)
    print(out, flush=True)


# ----------------------------------------------------------------------------
# מצב Worker: צ'אט דרך Issues
# ----------------------------------------------------------------------------
class GH:
    def __init__(self, repo: str, token: str, api: str = "https://api.github.com"):
        self.repo, self.api = repo, api.rstrip("/")
        self.s = requests.Session()
        self.s.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    def call(self, method, path, json_body=None, etag=None, params=None):
        headers = {"If-None-Match": etag} if etag else {}
        r = self.s.request(method, f"{self.api}/repos/{self.repo}{path}", json=json_body,
                           params=params, headers=headers, timeout=30)
        if r.status_code == 304:
            return 304, None, etag
        try:
            data = r.json() if r.content else None
        except ValueError:
            data = None
        return r.status_code, data, r.headers.get("ETag")


def all_comments(gh: GH, number: int):
    res, page = [], 1
    while True:
        st, data, _ = gh.call("GET", f"/issues/{number}/comments", params={"per_page": 100, "page": page})
        if st != 200:
            raise RuntimeError(f"comments HTTP {st}: {data}")
        res += data or []
        if not data or len(data) < 100:
            return res
        page += 1


def is_owner(comment: dict, owner: str) -> bool:
    return (comment.get("user") or {}).get("login", "").lower() == owner.lower()


def needs_reply(comments, owner: str, handled) -> bool:
    if not comments:
        return False
    last = comments[-1]
    body = last.get("body") or ""
    if body.startswith(STOP_MARKER):
        return False
    return (not body.startswith((MARKER, STREAM_MARKER))) and is_owner(last, owner) and last["id"] not in handled


def clean_reply(body: str) -> str:
    text = body[len(MARKER):]
    text = FOOTER_RE.sub("", text)
    text = DETAILS_RE.sub("", text)
    return text.strip()


def build_messages(comments, owner: str, system: str, max_chars: int = 36000):
    msgs = []
    for c in comments:
        body = c.get("body") or ""
        if body.startswith(STOP_MARKER):
            continue
        if body.startswith(MARKER):
            role, content = "assistant", clean_reply(body)
        elif is_owner(c, owner):
            role, content = "user", body.strip()
        else:
            continue
        if not content:
            continue
        if msgs and msgs[-1]["role"] == role:
            msgs[-1]["content"] += "\n\n" + content
        else:
            msgs.append({"role": role, "content": content})
    while len(msgs) > 1 and sum(len(m["content"]) for m in msgs) > max_chars:
        msgs.pop(0)
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    head = [{"role": "system", "content": system}] if system else []
    return head + msgs


SKILL_TOOLS = [
    {"type": "function", "function": {
        "name": "list_skills",
        "description": "List installed skill packs and their descriptions. Use this before choosing a workflow.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "read_skill",
        "description": "Load the full instructions for one installed skill by its exact name.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "Exact skill name returned by list_skills."}},
            "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "inspect_compute",
        "description": "Inspect this Kaggle kernel's actual CPU, GPU/VRAM, RAM, free disk, loaded model settings, and local inference server health. It does not expose credentials.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "web_search",
        "description": "Search the public web using DuckDuckGo and return a small set of result titles, URLs, and snippets. Treat results as leads; open and verify sources before relying on them.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["query"]}}},
]

WINDOWS_EXECUTOR_TOOLS = [
    {"type": "function", "function": {
        "name": "win_powershell",
        "description": "Run a PowerShell command on the connected Windows GitHub Actions runner. The process runs with the runner account's Administrator token and inherits the workflow environment, including available secrets. Work in the current Windows Workspace directory. Default timeout 120 seconds, maximum 600.",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string"}, "timeout": {"type": "integer"}}, "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "win_get_environment",
        "description": "Inspect the connected Windows runner, current account, Administrator-token status, CPU, Python and Workspace path. Does not print environment variables or secret values.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
]

EXECUTOR_TOOLS = [
    {"type": "function", "function": {
        "name": "bash",
        "description": "Run a bash command in the workspace (Linux, Python 3, Java 17, Node.js, gcc, git). Returns exit code and combined output. Default timeout 120s, max 600s.",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string"}, "timeout": {"type": "integer"}}, "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Create or overwrite a text file. The path is relative to the workspace directory.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read a text file (path relative to the workspace). Output is truncated.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "list_files",
        "description": "List files and folders in a workspace directory. Use path '.' for the workspace root.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "limit": {"type": "integer"}}, "required": []}}},
    {"type": "function", "function": {
        "name": "search_files",
        "description": "Search literal text in workspace text files recursively and return matching file names and line numbers.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}, "path": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "get_environment",
        "description": "Inspect the GitHub Actions executor host OS, architecture, CPU, RAM, free disk, and installed tool versions. Never returns secrets or environment variables.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
]

TOOLS = SKILL_TOOLS + EXECUTOR_TOOLS


def skill_catalog_text(job: dict) -> str:
    skills = job.get("skills") or {}
    if not isinstance(skills, dict) or not skills:
        return "אין כרגע חבילות Skills מותקנות."
    rows = []
    for name, item in sorted(skills.items()):
        if isinstance(item, dict):
            rows.append(f"- {name}: {item.get('description', '')}")
    return "\n".join(rows)


SKILL_HINT = (
    "\n\nיש לך מערכת Skills מודולרית. תחילה השתמש ב-list_skills כדי לראות יכולות, "
    "ואז ב-read_skill כדי לטעון את ההוראות המלאות של ה-Skill המתאים למשימה. "
    "אל תטען חבילות שאינן רלוונטיות. השתמש ב-inspect_compute לנתוני חומרה עדכניים וב-web_search לחיפוש ראשוני ברשת. "
    "Skills הם הוראות עבודה, לא הוכחה שיש כלי או הרשאה מסוימים."
)


AGENT_HINT = (
    "\n\nיש לך סביבת עבודה אמיתית ב-Linux. הכלים הזמינים כוללים bash, write_file, read_file, "
    "list_files, search_files ו-get_environment. inspect_compute מדווח על חומרת Kaggle עצמה. הקבצים נשמרים בין שיחות. "
    "השתמש ב-list_files כדי למפות תיקיות וב-search_files כדי לאתר הגדרות וקוד לפני שינוי. "
    "כתוב קבצים עם write_file ולא עם heredoc. הרץ ובדוק את הקוד לפני שאתה מדווח שהוא עובד. "
    "כשסיימת, ענה בעברית בקצרה מה עשית, אילו קבצים נוצרו ואילו בדיקות עברו, בלי להדביק קבצים שלמים בתשובה."
)


def context_budget(job: dict) -> int:
    """כמה תווים של היסטוריה מותר לשלוח, כך שהקלט ועוד max_tokens ייכנסו בהקשר של המודל."""
    if job.get("history_chars"):
        return int(job["history_chars"])
    ctx = int(job.get("ctx", 16384))
    mt = int(job.get("max_tokens", 6000))
    return max(6000, int((ctx - mt - 800) * 2.2))


def executor_online(gh: GH, cache: dict, title: str = EXECUTOR_TITLE) -> bool:
    """האם סביבת העבודה (executor) מחוברת כרגע. בודק לכל היותר פעם ב-15 שניות."""
    now = time.time()
    if now - cache.get("checked", 0) < 15:
        return cache.get("online", False)
    cache["checked"] = now
    online = False
    try:
        if not cache.get("no"):
            cache["no"] = find_status_issue(gh, title)
        if cache.get("no"):
            st, data, _ = gh.call("GET", f"/issues/{cache['no']}")
            m = re.search(r"\{[^{}]*\}", (data or {}).get("body") or "")
            if st == 200 and m:
                j = json.loads(m.group(0))
                online = j.get("state") == "online" and now - float(j.get("ts", 0)) < 150
    except Exception as e:  # noqa: BLE001
        print("[worker] executor check failed:", e, flush=True)
    cache["online"] = online
    return online


class GenerationStopped(Exception):
    """Raised when the user stops the active response."""


def call_tool(gh: GH, number: int, name: str, args: dict, poll: float = 2.0, should_stop=None) -> dict:
    """שולח בקשת כלי כתגובה ב-Issue וממתין לתוצאה מה-executor."""
    cid = uuid.uuid4().hex[:8]
    body = f"<!--tool-call:{cid}-->\n" + json.dumps({"tool": name, "args": args}, ensure_ascii=False)
    if len(body) > 60000:
        return {"ok": False, "exit": 1, "output": "הבקשה גדולה מדי (מעל 60KB). פצל לכמה קבצים."}
    st, data, _ = gh.call("POST", f"/issues/{number}/comments", {"body": body})
    if st != 201:
        return {"ok": False, "exit": 1, "output": f"לא הצלחתי לשלוח בקשה ל-executor (HTTP {st})"}
    since = data.get("created_at")
    t = args.get("timeout") if isinstance(args, dict) else None
    try:
        wait = (min(int(t), 600) if t else 120) + 90 if name in ("bash", "win_powershell") else 120
    except (TypeError, ValueError):
        wait = 210
    deadline = time.time() + wait
    marker = f"<!--tool-result:{cid}-->"
    etag = None
    while time.time() < deadline:
        if should_stop:
            should_stop()
        time.sleep(poll)
        if should_stop:
            should_stop()
        try:
            st, items, new_etag = gh.call("GET", f"/issues/{number}/comments", etag=etag,
                                          params={"since": since, "per_page": 100})
        except Exception:  # noqa: BLE001
            continue
        if st == 200:
            etag = new_etag
            for c in items or []:
                b = c.get("body") or ""
                # מקבלים תוצאות רק מ-github-actions[bot], כדי שאף אחד אחר לא יזייף תוצאה
                if b.startswith(marker) and (c.get("user") or {}).get("login") == BOT_LOGIN:
                    try:
                        return json.loads(b[len(marker):].strip())
                    except ValueError:
                        return {"ok": False, "exit": 1, "output": "תוצאה לא קריאה מה-executor"}
    return {"ok": False, "exit": 124, "output": "ה-executor לא ענה בזמן. ייתכן שהוא כבוי."}


def model_view(res: dict, name: str, limit: int = 3500) -> str:
    out = res.get("output", "")
    if len(out) > limit:
        out = out[: limit // 2] + f"\n...[נחתכו {len(out) - limit} תווים]...\n" + out[-limit // 2:]
    if name == "bash":
        return f"exit code: {res.get('exit')}\n{out}"
    return ("" if res.get("ok") else "ERROR: ") + out


def trim_agent_context(msgs: list, budget: int) -> None:
    """מקצר תוצאות כלים ישנות ואחר כך מוחק היסטוריה ישנה, עד שהשיחה נכנסת בתקציב."""
    def total():
        return sum(len(m.get("content") or "") + len(json.dumps(m.get("tool_calls") or [])) for m in msgs)

    if total() <= budget:
        return
    tools_idx = [i for i, m in enumerate(msgs) if m["role"] == "tool"]
    for i in tools_idx[:-2]:
        if total() <= budget:
            return
        msgs[i]["content"] = msgs[i]["content"][:300] + "\n...[הפלט קוצר]"
    cur = max((i for i, m in enumerate(msgs) if m["role"] == "user"), default=0)
    while total() > budget and cur > 1:
        del msgs[1]
        cur -= 1
        while len(msgs) > 1 and msgs[1]["role"] != "user" and cur > 1:
            del msgs[1]
            cur -= 1


def web_search(query: str, limit: int = 5) -> dict:
    """Search the public web; search snippets are leads, not verified evidence."""
    from html import unescape
    from urllib.parse import parse_qs, urlparse

    if not isinstance(query, str) or not query.strip():
        return {"ok": False, "exit": 1, "output": "חסר query"}
    query = query.strip()[:500]
    try:
        limit = max(1, min(int(limit or 5), 8))
    except (TypeError, ValueError):
        limit = 5
    try:
        response = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0 (compatible; WorkspaceAgent/1.0)"},
            timeout=15)
        response.raise_for_status()
        page = response.text
    except requests.RequestException as e:
        return {"ok": False, "exit": 1, "output": f"חיפוש הרשת נכשל: {type(e).__name__}: {e}"}

    anchors = list(re.finditer(
        r'<a\b(?=[^>]*class=["\'][^"\']*\bresult__a\b[^"\']*["\'])[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        page, re.I | re.S))
    results = []
    for i, match in enumerate(anchors):
        if len(results) >= limit:
            break
        href = unescape(match.group(1))
        title = unescape(re.sub(r"<[^>]+>", " ", match.group(2)))
        title = re.sub(r"\s+", " ", title).strip()
        parsed = urlparse(href)
        params = parse_qs(parsed.query)
        if "uddg" in params:
            href = params["uddg"][0]
        if not href.startswith(("http://", "https://")) or not title:
            continue
        end = anchors[i + 1].start() if i + 1 < len(anchors) else min(len(page), match.end() + 1800)
        tail = page[match.end():end]
        snip = re.search(
            r'<(?:a|div|span)\b(?=[^>]*class=["\'][^"\']*\bresult__snippet\b[^"\']*["\'])[^>]*>(.*?)</(?:a|div|span)>',
            tail, re.I | re.S)
        snippet = ""
        if snip:
            snippet = unescape(re.sub(r"<[^>]+>", " ", snip.group(1)))
            snippet = re.sub(r"\s+", " ", snippet).strip()
        results.append({"title": title[:240], "url": href, "snippet": snippet[:500]})
    if not results:
        return {"ok": False, "exit": 1, "output": "לא התקבלו תוצאות שניתן לפענח; ייתכן שמנוע החיפוש חסם את הבקשה או שפורמט הדף השתנה."}
    lines = [f"נמצאו {len(results)} תוצאות (תקצירים בלבד — יש לפתוח ולאמת את המקורות):"]
    for n, item in enumerate(results, 1):
        lines.append(f"{n}. {item['title']}\n   {item['url']}\n   {item['snippet']}")
    return {"ok": True, "exit": 0, "output": "\n".join(lines)}


def inspect_compute(job: dict) -> dict:
    """Return safe hardware and inference diagnostics from the Kaggle kernel itself."""
    import platform
    import shutil

    facts = [
        f"Runtime: {platform.system()} {platform.release()} ({platform.machine()})",
        f"CPU cores visible: {os.cpu_count()}",
        f"Model repository: {job.get('model_repo', 'unknown')}",
        f"Model file pattern: {job.get('model_pattern', 'unknown')}",
        f"Context setting: {job.get('ctx', 'default')}",
        f"Output chunk size: {job.get('max_tokens', 6000)} tokens (automatic continuation enabled)",
    ]
    try:
        with open("/proc/meminfo", encoding="ascii", errors="replace") as fh:
            mem = next((line for line in fh if line.startswith("MemTotal:")), "")
        if mem:
            facts.append("System RAM: " + mem.split(":", 1)[1].strip())
    except OSError:
        pass
    try:
        with open("/proc/meminfo", encoding="ascii", errors="replace") as fh:
            mem = next((line for line in fh if line.startswith("MemAvailable:")), "")
        if mem:
            facts.append("Available RAM: " + mem.split(":", 1)[1].strip())
    except OSError:
        pass
    try:
        gpu = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.free,driver_version", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=8)
        if gpu.returncode == 0 and gpu.stdout.strip():
            facts.append("GPU(s):\n" + gpu.stdout.strip())
        else:
            facts.append("GPU: nvidia-smi unavailable (" + (gpu.stderr or "no GPU details")[:180].strip() + ")")
    except (OSError, subprocess.TimeoutExpired) as e:
        facts.append(f"GPU: unavailable ({e})")
    for path in (OUT, "/kaggle/temp", "/tmp"):
        try:
            usage = shutil.disk_usage(path)
            facts.append(f"Disk {path}: total {usage.total // (1024**3)} GiB, free {usage.free // (1024**3)} GiB")
        except OSError:
            pass
    try:
        response = requests.get(LLM_URL + "/health", timeout=3)
        facts.append(f"llama-server health: HTTP {response.status_code}")
    except requests.RequestException as e:
        facts.append(f"llama-server health: unavailable ({type(e).__name__})")
    return {"ok": True, "exit": 0, "output": "\n".join(facts)}


def list_skill_packs(job: dict) -> dict:
    skills = job.get("skills") or {}
    if not isinstance(skills, dict):
        skills = {}
    items = []
    for name, item in sorted(skills.items()):
        if isinstance(item, dict):
            items.append({"name": name, "description": str(item.get("description", ""))})
    return {"ok": True, "exit": 0, "output": json.dumps(items, ensure_ascii=False, indent=2)}


def read_skill_pack(job: dict, name: str) -> dict:
    skills = job.get("skills") or {}
    item = skills.get(name) if isinstance(skills, dict) else None
    if not isinstance(item, dict):
        return {"ok": False, "exit": 1, "output": f"Skill לא נמצא: {name}. השתמש ב-list_skills."}
    content = str(item.get("content", ""))
    if len(content) > 16000:
        content = content[:16000] + "\n...[skill truncated]"
    return {"ok": True, "exit": 0, "output": f"# {name}\n{content}"}


def agent_loop(gh: GH, number: int, msgs: list, llm_url: str, job: dict, thinking: bool,
               available_tools=None, on_delta=None, should_stop=None):
    max_tokens = int(job.get("max_tokens", 6000))
    budget = context_budget(job)
    available_tools = available_tools if available_tools is not None else TOOLS
    local_tools = {"list_skills", "read_skill", "inspect_compute", "web_search"}
    allowed = {x["function"]["name"] for x in available_tools}
    steps, completion = 0, 0
    while True:
        if should_stop:
            should_stop()
        trim_agent_context(msgs, budget)
        d = chat_complete(llm_url, msgs, max_tokens, thinking, available_tools,
                          on_delta=on_delta, before_request=should_stop)
        if should_stop:
            should_stop()
        completion += int(d["usage"].get("completion_tokens", 0) or 0)
        calls = d["tool_calls"]
        if not calls:
            text = d["content"]
            return text, d["reasoning"], {"completion_tokens": completion}, d["finish"], steps
        msgs.append({"role": "assistant", "content": d["content"] or "", "tool_calls": calls})
        for tc in calls:
            if should_stop:
                should_stop()
            fn = tc.get("function") or {}
            name = fn.get("name", "")
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args) if args.strip() else {}
                except ValueError:
                    args = {}
            if not isinstance(args, dict):
                args = {}
            print(f"[worker] tool {name} in #{number}", flush=True)
            if name not in allowed:
                res = {"ok": False, "exit": 1, "output": f"Tool לא זמין: {name}"}
            elif name == "list_skills":
                res = list_skill_packs(job)
            elif name == "read_skill":
                res = read_skill_pack(job, str(args.get("name", "")))
            elif name == "inspect_compute":
                res = inspect_compute(job)
            elif name == "web_search":
                res = web_search(str(args.get("query", "")), args.get("limit", 5))
            elif name in local_tools:
                res = {"ok": False, "exit": 1, "output": "Unknown local skill tool"}
            else:
                res = call_tool(gh, number, name, args, should_stop=should_stop)
            msgs.append({"role": "tool", "tool_call_id": tc.get("id", ""), "content": model_view(res, name)})
            steps += 1


def reply_to(gh: GH, number: int, comments, owner: str, llm_url: str, job: dict, handled, exec_cache=None) -> None:
    last = comments[-1]
    handled.add(last["id"])
    try:
        gh.call("POST", f"/issues/comments/{last['id']}/reactions", {"content": "eyes"})
    except Exception:  # noqa: BLE001
        pass

    msgs = build_messages(comments, owner, job.get("system", ""), context_budget(job))
    thinking = False
    if msgs and msgs[-1]["content"].startswith("/think"):
        thinking = True
        msgs[-1]["content"] = msgs[-1]["content"][len("/think"):].strip() or "המשך."

    active_tools = list(SKILL_TOOLS) if job.get("skills") else []
    executor_cache = exec_cache if exec_cache is not None else {}
    executor_ready = bool(job.get("tools", True)) and executor_online(gh, executor_cache)
    windows_ready = bool(job.get("tools", True)) and executor_online(gh, executor_cache.setdefault("windows", {}), WINDOWS_EXECUTOR_TITLE)
    if executor_ready:
        active_tools.extend(EXECUTOR_TOOLS)
    if windows_ready:
        active_tools.extend(WINDOWS_EXECUTOR_TOOLS)
    use_tools = bool(active_tools)
    if use_tools:
        hint = SKILL_HINT + "\n\nחבילות Skills זמינות:\n" + skill_catalog_text(job)
        if executor_ready:
            hint += AGENT_HINT
        if windows_ready:
            hint += "\n\nיש לך גם Windows Workspace מחובר. השתמש ב-win_get_environment לבדיקת מצב והרשאות Administrator וב-win_powershell להרצת פקודות PowerShell. סביבת Windows נפרדת מסביבת Linux; הקבצים שלה נשמרים בענף workspace-windows. פקודות Windows רצות בהרשאות Administrator ויורשות את סביבת ה-executor, לרבות GH_TOKEN אם הוגדר; אל תדפיס סודות."
        if msgs and msgs[0]["role"] == "system":
            msgs[0]["content"] += hint
        else:
            msgs.insert(0, {"role": "system", "content": hint.strip()})

    # תגובת Worker יחידה שמתעדכנת בזמן יצירת התשובה.
    st, stream_data, _ = gh.call("POST", f"/issues/{number}/comments",
                                 {"body": STREAM_MARKER + "⏳ המודל חושב ומתחיל לכתוב..."})
    if st != 201:
        raise RuntimeError(f"cannot create streaming comment HTTP {st}: {stream_data}")
    stream_id = stream_data["id"]
    request_id = str(last["id"])
    cancel_marker = f"{STOP_MARKER}{request_id}-->"
    cancel_state = {"checked": 0.0, "stopped": False}

    def check_cancel(force=False):
        if cancel_state["stopped"]:
            raise GenerationStopped("stopped by user")
        now = time.monotonic()
        if not force and now - cancel_state["checked"] < 1.0:
            return
        cancel_state["checked"] = now
        try:
            status, items, _ = gh.call("GET", f"/issues/{number}/comments",
                                       params={"since": last.get("created_at", ""), "per_page": 100})
            if status == 200 and any((c.get("body") or "").strip() == cancel_marker
                                     and is_owner(c, owner) for c in (items or [])):
                cancel_state["stopped"] = True
                raise GenerationStopped("stopped by user")
        except GenerationStopped:
            raise
        except Exception as e:  # noqa: BLE001
            print("[stop] poll failed:", type(e).__name__, e, flush=True)

    stream_text = []
    last_publish = [0.0]
    last_size = [0]

    def publish_stream(piece="", thought=""):
        check_cancel()
        if piece:
            stream_text.append(piece)
        current = "".join(stream_text)
        now = time.monotonic()
        if not current or (now - last_publish[0] < 2.0 and len(current) - last_size[0] < 100):
            return
        # גם אם עדכון GitHub נכשל, לא עוצרים את יצירת התשובה ולא מציפים בקשות חוזרות.
        last_publish[0] = now
        last_size[0] = len(current)
        try:
            status, result, _ = gh.call("PATCH", f"/issues/comments/{stream_id}",
                                        {"body": STREAM_MARKER + current[-58000:]})
            if status != 200:
                print(f"[stream] update failed HTTP {status}: {result}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[stream] update failed: {type(e).__name__}: {e}", flush=True)

    t0 = time.time()
    reasoning, usage, finish, steps, text = "", {}, None, 0, ""
    try:
        if use_tools:
            text, reasoning, usage, finish, steps = agent_loop(
                gh, number, msgs, llm_url, job, thinking, active_tools, publish_stream, check_cancel)
        else:
            text, reasoning, usage, finish = chat(
                llm_url, msgs, int(job.get("max_tokens", 6000)), thinking,
                on_delta=publish_stream)
        check_cancel(force=True)
    except GenerationStopped:
        text = "".join(stream_text)
        finish = "cancelled"
    except Exception as e:  # noqa: BLE001
        text = f"⚠️ שגיאה בהפעלת המודל: {e}"
        finish = "error"
    dt = time.time() - t0

    body = MARKER + (text or "(תשובה ריקה)")
    if finish == "length":
        body += "\n\n> ⚠️ נעשה ניסיון להמשיך אוטומטית, אך הגעת למספר מקטעי ההמשך המרבי. אפשר לבקש להמשיך."
    elif finish == "cancelled":
        body += "\n\n> ⏹ נעצר לבקשתך. מוצג כאן החלק שנוצר עד העצירה."
    if reasoning:
        body += f"\n\n<details><summary>חשיבה</summary>\n\n{reasoning[:8000]}\n</details>"
    extra = f" · 🛠 {steps} כלים" if steps else ""
    body += f"\n\n<sub>⏱ {dt:.1f}s · {usage.get('completion_tokens', '?')} tokens{extra}</sub>"
    body = body[:60000]

    st, data, _ = gh.call("PATCH", f"/issues/comments/{stream_id}", {"body": body})
    if st != 200:
        raise RuntimeError(f"finalize streaming comment HTTP {st}: {data}")


def find_status_issue(gh: GH, title: str = STATUS_TITLE):
    st, data, _ = gh.call("GET", "/issues", params={"state": "open", "per_page": 100,
                                                    "sort": "created", "direction": "asc"})
    for i in data or []:
        if i.get("title") == title and "pull_request" not in i:
            return i["number"]
    return None


def ensure_status_issue(gh: GH) -> int:
    n = find_status_issue(gh, STATUS_TITLE)
    if n:
        return n
    st, data, _ = gh.call("POST", "/issues", {"title": STATUS_TITLE, "body": "starting"})
    if st != 201:
        raise RuntimeError(f"cannot create status issue: HTTP {st}: {data}")
    return data["number"]


def heartbeat(gh: GH, number: int, state: str, job: dict) -> None:
    payload = {"state": state, "ts": int(time.time()), "model": job.get("model_repo", "")}
    body = "Worker status (updated automatically)\n\n```json\n" + json.dumps(payload) + "\n```"
    gh.call("PATCH", f"/issues/{number}", {"body": body})


def read_state(gh: GH, number: int) -> str:
    st, data, _ = gh.call("GET", f"/issues/{number}")
    if st != 200 or not data:
        return ""
    m = re.search(r"\{[^{}]*\}", data.get("body") or "")
    if not m:
        return ""
    try:
        return json.loads(m.group(0)).get("state", "")
    except ValueError:
        return ""


def worker_loop(gh: GH, owner: str, llm_url: str, job: dict):
    idle_s = float(job.get("idle_minutes", 30)) * 60
    max_s = float(job.get("max_hours", 5.2)) * 3600
    poll_active = float(job.get("poll_active", 5))
    poll_idle = float(job.get("poll_idle", 12))
    hb_every = float(job.get("heartbeat_seconds", 60))

    status_no = ensure_status_issue(gh)
    heartbeat(gh, status_no, "online", job)
    print(f"[worker] online, status issue #{status_no}, owner={owner}", flush=True)

    t0 = last_act = last_hb = time.time()
    etag, seen, handled, count = None, {}, set(), 0
    exec_cache = {}
    reason = "unknown"
    while True:
        now = time.time()
        if now - t0 > max_s:
            reason = "max-time"
            break
        if now - last_act > idle_s:
            reason = "idle"
            break
        if now - last_hb > hb_every:
            last_hb = now
            try:
                if read_state(gh, status_no) == "stop":
                    reason = "stop-requested"
                    break
                heartbeat(gh, status_no, "online", job)
            except Exception as e:  # noqa: BLE001
                print("[worker] heartbeat error:", e, flush=True)
        try:
            st, issues, new_etag = gh.call("GET", "/issues", etag=etag, params={
                "labels": "chat", "state": "open", "per_page": 50, "sort": "updated"})
            if st in (401, 403):
                reason = f"auth-error-{st}"
                break
            if st == 200:
                for issue in issues or []:
                    if "pull_request" in issue or (issue.get("user") or {}).get("login", "").lower() != owner.lower():
                        continue
                    if seen.get(issue["number"]) == issue["updated_at"]:
                        continue
                    comments = all_comments(gh, issue["number"])
                    if needs_reply(comments, owner, handled):
                        print(f"[worker] replying in #{issue['number']}", flush=True)
                        reply_to(gh, issue["number"], comments, owner, llm_url, job, handled, exec_cache)
                        count += 1
                        last_act = time.time()
                    seen[issue["number"]] = issue["updated_at"]
                etag = new_etag
            elif st != 304:
                raise RuntimeError(f"GitHub API HTTP {st}: {issues}")
        except Exception as e:  # noqa: BLE001
            print("[worker] error:", e, flush=True)
            etag = None
            time.sleep(10)
        time.sleep(poll_active if time.time() - last_act < 300 else poll_idle)

    try:
        heartbeat(gh, status_no, "offline", job)
    except Exception:  # noqa: BLE001
        pass
    print(f"[worker] stopped: {reason}, handled {count} messages", flush=True)
    return reason, count


def run_worker(job: dict) -> None:
    gh = GH(job["release_repo"], job["gh_token"])
    reason, count = worker_loop(gh, job["gh_owner"], LLM_URL, job)
    with open(os.path.join(OUT, "result.txt"), "w", encoding="utf-8") as f:
        f.write(f"Worker stopped: {reason}. Handled {count} messages.")


# ----------------------------------------------------------------------------
def main() -> None:
    proc = start_llama(JOB)
    try:
        if JOB.get("mode") == "worker":
            run_worker(JOB)
        else:
            run_task(JOB)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
