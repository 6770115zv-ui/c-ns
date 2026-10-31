"""בונה תיקיית kernel מהקובץ kaggle/runner.py, מזריק לו את פרטי המשימה ודוחף ל-Kaggle."""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time

TASK_SLUG = "llm-runner"
WORKER_SLUG = "llm-worker"


def run(cmd):
    res = subprocess.run(cmd, capture_output=True, text=True)
    out = (res.stdout or "") + (res.stderr or "")
    print(out.strip(), flush=True)
    return res.returncode, out


def load_skills() -> dict:
    """Load repository SKILL.md files and embed them in the Kaggle kernel payload."""
    root = pathlib.Path("skills")
    skills = {}
    if not root.is_dir():
        return skills
    for path in sorted(root.glob("*/SKILL.md")):
        raw = path.read_text(encoding="utf-8")
        name = path.parent.name
        description = ""
        body = raw
        match = re.match(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", raw, re.S)
        if match:
            for line in match.group(1).splitlines():
                key, sep, value = line.partition(":")
                if sep and key.strip() == "name":
                    name = value.strip()
                elif sep and key.strip() == "description":
                    description = value.strip()
            body = match.group(2).strip()
        skills[name] = {
            "name": name,
            "description": description or name.replace("-", " "),
            "content": body,
        }
    total = sum(len(item["content"]) for item in skills.values())
    if total > 160_000:
        raise ValueError(f"Skill bundle too large: {total} characters (limit 160000)")
    print(f"[skills] loaded {len(skills)} skill packs ({total} chars)", flush=True)
    return skills


def build_dir(user: str, slug: str, job: dict) -> pathlib.Path:
    push_dir = pathlib.Path("/tmp/kaggle-push")
    shutil.rmtree(push_dir, ignore_errors=True)
    push_dir.mkdir(parents=True)

    src = pathlib.Path("kaggle/runner.py").read_text(encoding="utf-8")
    (push_dir / "runner.py").write_text("JOB = " + repr(job) + "\n\n" + src, encoding="utf-8")

    meta = {
        "id": f"{user}/{slug}",
        "title": slug,
        "code_file": "runner.py",
        "language": "python",
        "kernel_type": "script",
        "is_private": "true",
        "enable_gpu": "true",
        "enable_internet": "true",
        "dataset_sources": [],
        "competition_sources": [],
        "kernel_sources": [],
        "model_sources": [],
    }
    (push_dir / "kernel-metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return push_dir


def push(user: str, slug: str, job: dict):
    push_dir = build_dir(user, slug, job)
    cmd = ["kaggle", "kernels", "push", "-p", str(push_dir)]
    acc = os.environ.get("IN_ACCELERATOR", "").strip()
    if acc:
        cmd += ["--accelerator", acc]
    print("Running:", " ".join(cmd), flush=True)
    return run(cmd)


def main() -> None:
    user = os.environ["KAGGLE_USERNAME"]
    mode = os.environ.get("IN_MODE", "task")
    base_slug = WORKER_SLUG if mode == "worker" else TASK_SLUG
    job = {
        "mode": mode,
        "prompt": os.environ.get("IN_PROMPT", ""),
        "system": os.environ.get("IN_SYSTEM", ""),
        "model_repo": os.environ["IN_MODEL_REPO"],
        "model_pattern": os.environ["IN_MODEL_PATTERN"],
        "max_tokens": int(os.environ.get("IN_MAX_TOKENS") or 1024),
        "thinking": os.environ.get("IN_THINKING", "false").lower() == "true",
        "release_repo": os.environ["RELEASE_REPO"],
        "skills": load_skills(),
    }
    if mode == "worker":
        job.update({
            "gh_token": os.environ["GH_TOKEN"],
            "gh_owner": os.environ["GH_OWNER"],
            "idle_minutes": float(os.environ.get("IN_IDLE_MINUTES") or 30),
            "max_hours": 5.2,
            "ctx": int(os.environ.get("IN_CTX") or 16384),
        })

    # אבחון: מה המצב הנוכחי של ה-Kernel הקיים (אם יש)
    print("--- מצב נוכחי של ה-Kernel ---", flush=True)
    run(["kaggle", "kernels", "status", f"{user}/{base_slug}"])
    print("-----------------------------", flush=True)

    code, out = push(user, base_slug, job)

    if code != 0 and "409" in out:
        print("409 Conflict. כנראה ההרצה הקודמת עדיין פעילה. מחכה דקה ומנסה שוב...", flush=True)
        time.sleep(60)
        code, out = push(user, base_slug, job)

    if code != 0 and "409" in out:
        fallback = f"{base_slug}-{os.environ.get('GITHUB_RUN_ID', int(time.time()))}"
        print(f"עדיין 409. מנסה Kernel חדש בשם {fallback}", flush=True)
        code, out = push(user, fallback, job)

    if code != 0:
        sys.exit(
            "\nהדחיפה ל-Kaggle נכשלה. בדוק ב-kaggle.com/code (Your Work) אם יש מחברת llm-runner "
            "שרצה כרגע, ושהערך של KAGGLE_USERNAME זהה לשם המשתמש ב-URL של המחברות."
        )

    # ה-ref האמיתי של ה-Kernel נלקח מה-URL ש-Kaggle מחזיר
    m = re.search(r"kaggle\.com/code/([^/\s]+)/([^/\s?#]+)", out)
    ref = f"{m.group(1)}/{m.group(2)}" if m else f"{user}/{base_slug}"
    print("Kernel ref:", ref)

    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as f:
            f.write(f"ref={ref}\n")


if __name__ == "__main__":
    main()
