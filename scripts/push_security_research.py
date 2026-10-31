"""Push a dedicated, private Kaggle kernel for read-only source security research."""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time

KERNEL_SLUG = "llm-security-research"

def load_skills():
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
        raise ValueError(f"Skill bundle too large: {total} characters")
    print(f"[skills] loaded {len(skills)} skill packs", flush=True)
    return skills

def build_dir(user, slug, job):
    push_dir = pathlib.Path("/tmp/kaggle-security-research-push")
    shutil.rmtree(push_dir, ignore_errors=True)
    push_dir.mkdir(parents=True)
    runner_src = pathlib.Path("kaggle/runner.py").read_text(encoding="utf-8")
    research_src = pathlib.Path("kaggle/security_research.py").read_text(encoding="utf-8")
    main_guard = '\\nif __name__ == "__main__":\\n    main()\\n'
    if main_guard not in runner_src:
        raise ValueError("Could not find the standard runner main guard")
    runner_src = runner_src.rsplit(main_guard, 1)[0]
    research_src = research_src.replace(
        "import runner_lib as base",
        "import sys\\nbase = sys.modules[\"__main__\"]",
        1,
    )
    # Kaggle executes one script file; bundle the shared model runtime and
    # the read-only audit agent into that file instead of relying on sidecars.
    bundled = "JOB = " + repr(job) + "\\n\\n" + runner_src + "\\n\\n" + research_src
    (push_dir / "security_research.py").write_text(bundled, encoding="utf-8")
    metadata = {
        "id": f"{user}/{slug}",
        "title": "Read-only source security research",
        "code_file": "security_research.py",
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
    (push_dir / "kernel-metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return push_dir

def push(user, slug, job):
    directory = build_dir(user, slug, job)
    command = ["kaggle", "kernels", "push", "-p", str(directory)]
    accelerator = os.environ.get("IN_ACCELERATOR", "").strip()
    if accelerator:
        command += ["--accelerator", accelerator]
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    output = ((result.stdout or "") + (result.stderr or "")).strip()
    if output:
        print(output, flush=True)
    return result.returncode, output

def main():
    user = os.environ["KAGGLE_USERNAME"]
    job = {
        "mode": "security-research",
        "release_repo": os.environ["RELEASE_REPO"],
        "target_repo": os.environ.get("IN_TARGET_REPO", "torvalds/linux").strip(),
        "target_ref": os.environ.get("IN_TARGET_REF", "master").strip(),
        "target_subdir": os.environ.get("IN_TARGET_SUBDIR", ".").strip() or ".",
        "research_prompt": os.environ.get("IN_RESEARCH_PROMPT", "").strip(),
        "model_repo": os.environ.get("IN_MODEL_REPO", "unsloth/Qwen3.8-27B-GGUF"),
        "model_pattern": os.environ.get("IN_MODEL_PATTERN", "*UD-Q4_K_M*"),
        "ctx": int(os.environ.get("IN_CTX", "16384")),
        "max_tokens": int(os.environ.get("IN_MAX_TOKENS", "3072")),
        "max_steps": int(os.environ.get("IN_MAX_STEPS", "40")),
        "thinking": os.environ.get("IN_THINKING", "true").lower() == "true",
        "skills": load_skills(),
    }
    # Validate input early, before any kernel is pushed.
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", job["target_repo"]):
        sys.exit("target_repo must be a GitHub owner/repository pair")
    if not job["target_ref"] or job["target_ref"].startswith("-") or not re.fullmatch(r"[A-Za-z0-9._/-]+", job["target_ref"]):
        sys.exit("target_ref must be a branch or tag using letters, digits, dot, underscore, slash or dash")
    print(f"[research] target={job['target_repo']} ref={job['target_ref']}", flush=True)
    print(f"[research] model={job['model_repo']} pattern={job['model_pattern']} steps={job['max_steps']}", flush=True)
    code, output = push(user, KERNEL_SLUG, job)
    slug = KERNEL_SLUG
    if code != 0 and ("409" in output or "already running" in output.lower()):
        slug = f"{KERNEL_SLUG}-{os.environ.get('GITHUB_RUN_ID', int(time.time()))}"
        print(f"[research] kernel name is busy; using unique kernel {slug}", flush=True)
        code, output = push(user, slug, job)
    if code != 0:
        sys.exit("Kaggle kernel push failed. Check the Kaggle account, API secrets, accelerator availability and kernel permissions.")
    match = re.search(r"kaggle\.com/code/([^/\s]+)/([^/\s?#]+)", output)
    kernel_ref = f"{match.group(1)}/{match.group(2)}" if match else f"{user}/{slug}"
    print(f"Kernel ref: {kernel_ref}", flush=True)
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as handle:
            handle.write(f"ref={kernel_ref}\n")

if __name__ == "__main__":
    main()
