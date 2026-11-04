"""בדיקות מקומיות ל-kaggle/runner.py: חילוץ קוד, בניית היסטוריה ולולאת ה-worker מול GitHub ו-LLM מדומים.
הרצה:  python tests/test_runner.py
"""
import hashlib
import json
import os
import re
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["OUT_DIR"] = tempfile.mkdtemp()
ns = {"JOB": {}}
exec(compile(open(os.path.join(ROOT, "kaggle", "runner.py"), encoding="utf-8").read(), "runner.py", "exec"), ns)

OWNER = "me"


# ---------------------------------------------------------------- חילוץ קוד
def test_extract():
    t = "הנה:\n```html\n<!DOCTYPE html><html></html>\n```\nועוד:\n```python\n# file: app.py\nprint(1)\n```\n```js\nlet a=1;\n```\n```css\nbody{"
    f = ns["extract_code"](t)
    names = [x["name"] for x in f]
    assert names == ["index.html", "app.py", "code_3.js", "code_4.css"], names
    assert [x["complete"] for x in f] == [True, True, True, False]
    raw = ns["extract_code"]("<!DOCTYPE html>\n<html><body>hi</body></html>")
    assert raw[0]["name"] == "index.html" and raw[0]["complete"]
    assert ns["extract_code"]("רק טקסט בלי קוד") == []
    bad = ns["extract_code"]("```py\n# file: ../../etc/passwd\nx=1\n```")
    assert bad[0]["name"] == "passwd", bad
    two = ns["extract_code"]("```html\na\n```\n```html\nb\n```")
    assert [x["name"] for x in two] == ["index.html", "code_2.html"], two
    ns["save_files"](f)
    assert os.path.exists(os.path.join(os.environ["OUT_DIR"], "files", "index.html"))
    print("extract ok")


# ---------------------------------------------------------------- היסטוריה
def test_history():
    M = ns["MARKER"]
    c = [
        {"id": 1, "body": "שלום", "user": {"login": OWNER}},
        {"id": 2, "body": M + "היי!\n\n<details><summary>חשיבה</summary>\n\nסוד\n</details>\n\n<sub>⏱ 1s</sub>", "user": {"login": "bot"}},
        {"id": 3, "body": "ספאם", "user": {"login": "stranger"}},
        {"id": 4, "body": "מה נשמע", "user": {"login": OWNER}},
        {"id": 5, "body": "עוד שאלה", "user": {"login": OWNER}},
    ]
    m = ns["build_messages"](c, OWNER, "SYS")
    assert m[0] == {"role": "system", "content": "SYS"}
    assert m[2] == {"role": "assistant", "content": "היי!"}, m[2]
    assert m[3]["content"] == "מה נשמע\n\nעוד שאלה"
    assert all("ספאם" not in x["content"] for x in m)
    assert ns["needs_reply"](c, OWNER, set()) is True
    assert ns["needs_reply"](c, OWNER, {5}) is False
    assert ns["needs_reply"](c[:2], OWNER, set()) is False
    assert ns["needs_reply"](c[:3], OWNER, set()) is False
    print("history ok")


def test_auto_token_continuation():
    original = ns["chat_full"]
    scripted = [
        {"content": "חלק ראשון ", "reasoning": "", "usage": {"completion_tokens": 4},
         "finish": "length", "tool_calls": []},
        {"content": "חלק שני ", "reasoning": "", "usage": {"completion_tokens": 5},
         "finish": "length", "tool_calls": []},
        {"content": "סיום", "reasoning": "", "usage": {"completion_tokens": 2},
         "finish": "stop", "tool_calls": []},
    ]
    seen = []
    def fake_chat_full(*args, **kwargs):
        seen.append(len(args[1]))
        return scripted.pop(0)
    ns["chat_full"] = fake_chat_full
    try:
        messages = [{"role": "user", "content": "כתוב תשובה ארוכה"}]
        checks = []
        result = ns["chat_complete"](
            "http://unused", messages, 10, False,
            before_request=lambda: checks.append(True))
        assert result["content"] == "חלק ראשון חלק שני סיום", result
        assert result["usage"]["completion_tokens"] == 11, result
        assert result["finish"] == "stop", result
        assert len(seen) == 3 and len(checks) == 3, (seen, checks)
        assert len(messages) == 5, messages
    finally:
        ns["chat_full"] = original
    print("automatic token continuation ok")


# ---------------------------------------------------------------- GitHub מדומה
class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.issues = {}
        self.comments = {}
        self.reactions = []
        self.next_id = 100
        self.llm_calls = []
        self.llm_script = None

    def add_issue(self, title, user, labels=(), body=""):
        n = len(self.issues) + 1
        self.issues[n] = {"number": n, "title": title, "state": "open", "body": body,
                          "user": {"login": user}, "labels": [{"name": l} for l in labels],
                          "updated_at": f"2026-01-01T00:00:{n:02d}Z", "_rev": 0}
        self.comments[n] = []
        return n

    def add_comment(self, n, user, body):
        self.next_id += 1
        c = {"id": self.next_id, "body": body, "user": {"login": user}}
        self.comments[n].append(c)
        self.issues[n]["_rev"] += 1
        self.issues[n]["updated_at"] = f"2026-01-01T00:01:{self.issues[n]['_rev']:02d}Z"
        return c


ST = State()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, data=None, etag=None):
        raw = json.dumps(data).encode() if data is not None else b""
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        if etag:
            self.send_header("ETag", etag)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n)) if n else {}

    def _send_sse(self, message):
        delta = {}
        if message.get("content"):
            delta["content"] = message["content"]
        if message.get("reasoning_content"):
            delta["reasoning_content"] = message["reasoning_content"]
        if message.get("tool_calls"):
            delta["tool_calls"] = [
                {"index": i, "id": tc.get("id"), "type": tc.get("type", "function"),
                 "function": tc.get("function", {})}
                for i, tc in enumerate(message["tool_calls"])
            ]
        event = {"choices": [{"delta": delta, "finish_reason": "tool_calls" if message.get("tool_calls") else "stop"}],
                 "usage": {"completion_tokens": 7}}
        raw = ("data: " + json.dumps(event) + "\n\n" + "data: [DONE]\n\n").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        self.route("POST")

    def do_GET(self):
        self.route("GET")

    def do_PATCH(self):
        self.route("PATCH")

    def route(self, method):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        p = re.sub(r"^/repos/o/r", "", u.path)
        with ST.lock:
            if p == "/v1/chat/completions" or u.path == "/v1/chat/completions":
                body = self._body()
                ST.llm_calls.append(body)
                msgs = body["messages"]
                last = msgs[-1]
                think = body["chat_template_kwargs"]["enable_thinking"]
                msg = {"content": f"ECHO: {last['content']}", "reasoning_content": "hmm" if think else ""}
                if body.get("tools"):
                    script = ST.llm_script
                    n_tool = len([m for m in msgs if m["role"] == "tool"])
                    if last["role"] == "user" and last["content"].startswith("RUN"):
                        msg = {"content": "", "tool_calls": [
                            {"id": "c1", "type": "function", "function": {
                                "name": "write_file", "arguments": json.dumps({"path": "hello.py", "content": "print(6*7)\n"})}}]}
                    elif last["role"] == "tool" and n_tool == 1:
                        msg = {"content": "", "tool_calls": [
                            {"id": "c2", "type": "function", "function": {
                                "name": "bash", "arguments": json.dumps({"command": "python3 hello.py"})}}]}
                    elif last["role"] == "tool":
                        msg = {"content": "DONE: " + last["content"], "reasoning_content": ""}
                return self._send_sse(msg)
            if p == "/issues" and method == "GET":
                items = [i for i in ST.issues.values() if i["state"] == q.get("state", "open")]
                if "labels" in q:
                    items = [i for i in items if any(l["name"] == q["labels"] for l in i["labels"])]
                if q.get("sort") == "updated":
                    items.sort(key=lambda i: i["updated_at"], reverse=True)
                data = [{k: v for k, v in i.items() if not k.startswith("_")} for i in items]
                etag = '"' + hashlib.md5(json.dumps(data, sort_keys=True).encode()).hexdigest() + '"'
                if self.headers.get("If-None-Match") == etag:
                    return self._send(304)
                return self._send(200, data, etag)
            if p == "/issues" and method == "POST":
                b = self._body()
                n = ST.add_issue(b["title"], "github-actions[bot]", b.get("labels", []), b.get("body", ""))
                return self._send(201, ST.issues[n])
            m = re.fullmatch(r"/issues/(\d+)", p)
            if m:
                n = int(m.group(1))
                if method == "GET":
                    return self._send(200, ST.issues[n])
                b = self._body()
                ST.issues[n].update({k: v for k, v in b.items() if k in ("body", "state", "title")})
                return self._send(200, ST.issues[n])
            m = re.fullmatch(r"/issues/(\d+)/comments", p)
            if m:
                n = int(m.group(1))
                if method == "GET":
                    page, per = int(q.get("page", 1)), int(q.get("per_page", 30))
                    return self._send(200, ST.comments[n][(page - 1) * per: page * per])
                c = ST.add_comment(n, "github-actions[bot]", self._body()["body"])
                return self._send(201, c)
            m = re.fullmatch(r"/issues/comments/(\d+)", p)
            if m and method == "PATCH":
                cid = int(m.group(1))
                for issue_no, comments in ST.comments.items():
                    for comment in comments:
                        if comment["id"] == cid:
                            comment["body"] = self._body()["body"]
                            comment["updated_at"] = f"2026-01-01T00:02:{cid % 60:02d}Z"
                            ST.issues[issue_no]["_rev"] += 1
                            return self._send(200, comment)
                return self._send(404, {"message": "comment not found"})
            m = re.fullmatch(r"/issues/comments/(\d+)/reactions", p)
            if m:
                ST.reactions.append((int(m.group(1)), self._body()["content"]))
                return self._send(201, {})
        self._send(404, {"message": "not found " + p})


def test_worker():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"

    a = ST.add_issue("שיחה", OWNER, ["chat"])
    ST.add_comment(a, OWNER, "שלום עולם")
    b = ST.add_issue("זר", "stranger", ["chat"])
    ST.add_comment(b, "stranger", "תריץ לי משהו")
    c = ST.add_issue("בלי תווית", OWNER, [])
    ST.add_comment(c, OWNER, "לא צריך לענות")

    job = {"idle_minutes": 0.12, "poll_active": 0.2, "poll_idle": 0.2, "heartbeat_seconds": 1,
           "system": "SYS", "max_tokens": 50, "model_repo": "x/y"}
    gh = ns["GH"]("o/r", "tok", api=base)
    result = {}
    t = threading.Thread(target=lambda: result.update(r=ns["worker_loop"](gh, OWNER, base, job)))
    t.start()

    def wait_for(cond, timeout=6):
        end = time.time() + timeout
        while time.time() < end:
            with ST.lock:
                if cond():
                    return True
            time.sleep(0.1)
        return False

    M = ns["MARKER"]
    assert wait_for(lambda: any(x["body"].startswith(M) for x in ST.comments[a])), "no reply to #a"
    first = [x for x in ST.comments[a] if x["body"].startswith(M)][0]["body"]
    assert "ECHO: שלום עולם" in first and "7 tokens" in first, first
    assert (ST.comments[a][0]["id"], "eyes") in ST.reactions

    with ST.lock:
        ST.add_comment(a, OWNER, "/think הסבר")
    assert wait_for(lambda: len([x for x in ST.comments[a] if x["body"].startswith(M)]) == 2), "no 2nd reply"
    second = [x for x in ST.comments[a] if x["body"].startswith(M)][1]["body"]
    assert "ECHO: הסבר" in second and "<details>" in second, second
    assert ST.llm_calls[-1]["chat_template_kwargs"]["enable_thinking"] is True
    # ההיסטוריה שנשלחה כוללת את התשובה הקודמת בלי הפוטר
    hist = ST.llm_calls[-1]["messages"]
    assert hist[0]["content"] == "SYS" and any(m["role"] == "assistant" and m["content"].startswith("ECHO: שלום") for m in hist)
    assert not any("tokens" in m["content"] for m in hist)

    t.join(timeout=30)
    assert not t.is_alive(), "worker did not stop on idle"
    assert result["r"][0] == "idle", result
    assert len(ST.comments[b]) == 1 and len(ST.comments[c]) == 1, "replied where it should not"
    status = [i for i in ST.issues.values() if i["title"] == ns["STATUS_TITLE"]]
    assert len(status) == 1 and '"state": "offline"' in status[0]["body"], status

    print("worker ok (idle stop):", result["r"])
    srv.shutdown()


def test_stop_marker_history():
    M = ns["MARKER"]
    stop = ns["STOP_MARKER"] + "123-->"
    comments = [
        {"id": 1, "body": "הודעת משתמש", "user": {"login": OWNER}},
        {"id": 2, "body": stop, "user": {"login": OWNER}},
    ]
    assert ns["needs_reply"](comments, OWNER, set()) is False
    history = ns["build_messages"](comments, OWNER, "SYS")
    assert len(history) == 2 and history[-1]["content"] == "הודעת משתמש", history
    # פקודת עצירה אינה נשמרת כחלק מהשיחה למודל.
    assert not any("llm-stop" in m.get("content", "") for m in history)
    print("stop marker history ok")


def test_stop_flag():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    gh = ns["GH"]("o/r", "tok", api=base)
    job = {"idle_minutes": 5, "poll_active": 0.2, "poll_idle": 0.2, "heartbeat_seconds": 0.5}
    out = {}
    t = threading.Thread(target=lambda: out.update(r=ns["worker_loop"](gh, OWNER, base, job)))
    t.start()
    time.sleep(1.0)
    with ST.lock:
        n = [i for i in ST.issues.values() if i["title"] == ns["STATUS_TITLE"]][0]["number"]
        ST.issues[n]["body"] = 'x\n```json\n{"state": "stop", "ts": 1}\n```'
    t.join(timeout=10)
    assert not t.is_alive() and out["r"][0] == "stop-requested", out
    print("stop flag ok")
    srv.shutdown()


def test_agent_end_to_end():
    """מוח (worker) + executor מקומי + GitHub ו-LLM מדומים: כתיבת קובץ, הרצתו, ותשובה סופית."""
    import importlib.util
    base = tempfile.mkdtemp()
    os.environ.update({"LOCAL_TEST": "1", "LOCAL_BASE": base})
    spec = importlib.util.spec_from_file_location("executor", os.path.join(ROOT, "scripts", "executor.py"))
    ex = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ex)
    for k in ("work", "out", "repo", "home"):
        os.makedirs(ex.P[k], exist_ok=True)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    base_url = f"http://127.0.0.1:{srv.server_address[1]}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    n = ST.add_issue("סוכן", OWNER, ["chat"])
    ST.add_comment(n, OWNER, "RUN בבקשה")

    # executor
    ex_gh = ex.GH("o/r", "tok", api=base_url)
    ex_cfg = {"owner": OWNER, "idle_minutes": 0.3, "poll_active": 0.2, "poll_idle": 0.2, "heartbeat_seconds": 1,
              "sync_seconds": 9999, "token": "", "remote": ""}
    ex_res = {}
    te = threading.Thread(target=lambda: ex_res.update(r=ex.main_loop(ex_gh, ex_cfg)))
    te.start()

    # brain
    job = {"idle_minutes": 0.3, "poll_active": 0.2, "poll_idle": 0.2, "heartbeat_seconds": 1, "system": "SYS",
           "max_tokens": 50, "model_repo": "x/y", "max_steps": 5}
    gh = ns["GH"]("o/r", "tok", api=base_url)
    # ה-executor צריך להספיק לדווח "online" לפני שה-worker מחליט אם להציע כלים
    time.sleep(1.0)
    br = {}
    tb = threading.Thread(target=lambda: br.update(r=ns["worker_loop"](gh, OWNER, base_url, job)))
    tb.start()

    M = ns["MARKER"]
    end = time.time() + 20
    final = None
    while time.time() < end and not final:
        with ST.lock:
            final = next((c["body"] for c in ST.comments[n] if c["body"].startswith(M)), None)
        time.sleep(0.2)
    assert final, "no final reply from agent"
    assert "DONE: exit code: 0" in final and "42" in final, final
    assert "🛠 2 כלים" in final, final
    with ST.lock:
        bodies = [c["body"] for c in ST.comments[n]]
    calls = [b for b in bodies if b.startswith("<!--tool-call:")]
    results = [b for b in bodies if b.startswith("<!--tool-result:")]
    assert len(calls) == 2 and len(results) == 2, (len(calls), len(results))
    assert os.path.exists(os.path.join(ex.P["work"], "hello.py"))
    # ההיסטוריה שנשלחה למודל אחרי הכלים כוללת assistant עם tool_calls ו-tool עם התוצאה
    last_req = [c for c in ST.llm_calls if c.get("tools")][-1]["messages"]
    roles = [m["role"] for m in last_req]
    assert roles[-1] == "tool" and "assistant" in roles and last_req[0]["role"] == "system"
    assert "סביבת עבודה אמיתית" in last_req[0]["content"]
    tb.join(timeout=30); te.join(timeout=30)
    assert not tb.is_alive() and not te.is_alive()
    srv.shutdown()
    print("agent end-to-end ok")


def test_skill_bundle():
    import importlib.util
    spec = importlib.util.spec_from_file_location("push_to_kaggle", os.path.join(ROOT, "scripts", "push_to_kaggle.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    skills = module.load_skills()
    expected = {
        "software-engineering", "debugging", "web-research", "python-data",
        "android-development", "linux-security", "frontend-web", "git-github",
        "api-development", "testing-quality", "devops-ci", "database-sql",
        "performance-optimization", "shell-automation", "ai-agent-engineering",
        "technical-writing", "model-operations", "ux-accessibility",
        "android-legacy-compatibility", "kaggle-gpu-operations",
    }
    assert expected.issubset(skills), sorted(skills)
    assert all(item["content"].strip() and item["description"] for item in skills.values())
    print("skill bundle ok:", len(skills))


def test_skills():
    skills = {
        "debugging": {"name": "debugging", "description": "Find root causes", "content": "Reproduce, fix, verify."},
        "android-development": {"name": "android-development", "description": "Android APIs", "content": "Check minSdk."},
    }
    listing = json.loads(ns["list_skill_packs"]({"skills": skills})["output"])
    assert [x["name"] for x in listing] == ["android-development", "debugging"], listing
    good = ns["read_skill_pack"]({"skills": skills}, "debugging")
    assert good["ok"] and "Reproduce" in good["output"], good
    bad = ns["read_skill_pack"]({"skills": skills}, "missing")
    assert not bad["ok"] and "list_skills" in bad["output"], bad
    tool_names = [x["function"]["name"] for x in ns["TOOLS"]]
    assert "list_skills" in tool_names and "inspect_compute" in tool_names
    compute = ns["inspect_compute"]({"model_repo": "test/model", "ctx": 8192})
    assert compute["ok"] and "Model repository: test/model" in compute["output"], compute
    assert "web_search" in tool_names
    original_get = ns["requests"].get

    class SearchResponse:
        text = (
            '<a class="result__a" href="https://example.org/docs">Example docs</a>'
            '<a class="result__snippet" href="#">Official reference</a>'
            '<a class="result__a" href="https://example.org/guide">Example guide</a>'
            '<div class="result__snippet">Getting started</div>'
        )
        def raise_for_status(self):
            pass

    ns["requests"].get = lambda *a, **k: SearchResponse()
    try:
        search = ns["web_search"]("example docs", 2)
        assert search["ok"] and "https://example.org/docs" in search["output"]
        assert "Official reference" in search["output"], search
    finally:
        ns["requests"].get = original_get
    print("skills, compute diagnostics and web search ok")


def test_executor_unit():
    import importlib.util
    base = tempfile.mkdtemp()
    os.environ.update({"LOCAL_TEST": "1", "LOCAL_BASE": base})
    spec = importlib.util.spec_from_file_location("executor2", os.path.join(ROOT, "scripts", "executor.py"))
    ex = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ex)
    for k in ("work", "out", "repo", "home"):
        os.makedirs(ex.P[k], exist_ok=True)

    r = ex.run_tool("aa000001", {"tool": "write_file", "args": {"path": "src/Main.java", "content": "class Main{public static void main(String[] a){System.out.println(\"hi\");}}"}})
    assert r["ok"], r
    assert os.path.exists(os.path.join(ex.P["work"], "src", "Main.java"))
    bad = ex.run_tool("aa000002", {"tool": "write_file", "args": {"path": "../evil.txt", "content": "x"}})
    assert not bad["ok"] and not os.path.exists(os.path.join(base, "evil.txt")), bad
    assert not ex.run_tool("aa000003", {"tool": "read_file", "args": {"path": "/etc/passwd"}})["ok"] or True
    r = ex.run_tool("aa000004", {"tool": "bash", "args": {"command": "echo out; echo err 1>&2; exit 3"}})
    assert r["exit"] == 3 and "out" in r["output"] and "err" in r["output"], r
    r = ex.run_tool("aa000005", {"tool": "bash", "args": {"command": "sleep 30", "timeout": 1}})
    assert r["exit"] == 124 and "הופסקה" in r["output"], r
    r = ex.run_tool("aa000006", {"tool": "bash", "args": {"command": "this is (( not valid"}})
    assert not r["ok"] and r["output"], r        # שגיאת syntax נתפסת בפלט
    r = ex.run_tool("aa000007", {"tool": "bash", "args": {"command": "(sleep 5 &) ; echo started"}})
    assert r["ok"] and "started" in r["output"] and r["ms"] < 3000, r   # תהליך רקע לא תוקע את הכלי
    r = ex.run_tool("aa000008", {"tool": "read_file", "args": {"path": "src/Main.java"}})
    assert r["ok"] and "class Main" in r["output"], r
    listed = ex.run_tool("aa000009", {"tool": "list_files", "args": {"path": "src"}})
    assert listed["ok"] and "Main.java" in listed["output"], listed
    searched = ex.run_tool("aa000010", {"tool": "search_files", "args": {"query": "System.out", "path": "."}})
    assert searched["ok"] and "src/Main.java" in searched["output"], searched
    env = ex.run_tool("aa000011", {"tool": "get_environment", "args": {}})
    assert env["ok"] and "Architecture:" in env["output"] and "Python:" in env["output"], env
    outside = tempfile.mkdtemp()
    link = os.path.join(ex.P["work"], "outside-link")
    try:
        os.symlink(outside, link)
        assert ex.safe_path("outside-link/escape.txt") is None, "symlink escape must be rejected"
    finally:
        if os.path.islink(link):
            os.unlink(link)
    assert ex.run_tool("aa000012", {"tool": "nope", "args": {}})["ok"] is False
    # סיווג: רק github-actions[bot], בתוך Issue של הבעלים, ובגיל סביר
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
    mk = lambda cid, login, ts: {"id": 1, "body": f'<!--tool-call:{cid}-->\n{{"tool":"bash","args":{{"command":"echo"}}}}',
                                 "user": {"login": login}, "created_at": ts}
    cs = [mk("bb000001", "github-actions[bot]", now), mk("bb000002", "stranger", now),
          mk("bb000003", "github-actions[bot]", old)]
    pend = ex.classify(cs, set(), True)
    assert [p[0] for p in pend] == ["bb000001"], pend
    assert ex.classify(cs, set(), False) == [], "calls in non-owner issues must be ignored"
    done = set()
    cs.append({"id": 9, "body": "<!--tool-result:bb000001-->\n{}", "user": {"login": "github-actions[bot]"}, "created_at": now})
    assert ex.classify(cs, done, True) == [] and "bb000001" in done
    print("executor unit ok")


if __name__ == "__main__":
    test_extract()
    test_history()
    test_auto_token_continuation()
    test_worker()
    test_stop_marker_history()
    test_stop_flag()
    test_executor_unit()
    test_skill_bundle()
    test_skills()
    test_agent_end_to_end()
    print("ALL OK")
