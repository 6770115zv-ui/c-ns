import importlib.util
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.modules.setdefault("runner_lib", types.SimpleNamespace())
spec = importlib.util.spec_from_file_location("security_research", ROOT / "kaggle" / "security_research.py")
research = importlib.util.module_from_spec(spec)
spec.loader.exec_module(research)


def test_input_validation():
    assert research.validate_target_repo("torvalds/linux") == "torvalds/linux"
    for bad in ("https://github.com/torvalds/linux", "../evil/repo", "-owner/repo", "owner/name?x=1"):
        try:
            research.validate_target_repo(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted unsafe repo selector: {bad}")

    assert research.validate_ref("master") == "master"
    assert research.validate_ref("v6.12") == "v6.12"
    for bad in ("-upload-pack=sh", "../main", "branch name", "a?b"):
        try:
            research.validate_ref(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted unsafe ref: {bad}")

    assert research.safe_relative_path(".") == "."
    assert research.safe_relative_path("drivers/net") == "drivers/net"
    for bad in ("../outside", "/etc/passwd", "drivers/../../outside"):
        try:
            research.safe_relative_path(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted unsafe path: {bad}")


def test_read_only_source_tools():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        (root / "drivers").mkdir()
        (root / "other").mkdir()
        (root / "drivers" / "net.c").write_text(
            "int probe(void) {\\n    copy_from_user(dst, src, size);\\n    return 0;\\n}\\n",
            encoding="utf-8",
        )
        (root / "other" / "ignored.c").write_text("copy_from_user(a, b, c);\\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "fixture"], check=True)

        research.SOURCE_ROOT = root.resolve()
        research.ALLOWED_SCOPE = "drivers"

        listing = research.list_source_files({"path": ".", "limit": 20})
        assert listing["ok"] and "drivers/net.c" in listing["output"], listing
        assert "other/ignored.c" not in listing["output"], listing

        read = research.read_source_file({"path": "drivers/net.c", "start_line": 2, "end_line": 3})
        assert read["ok"] and "2:     copy_from_user" in read["output"], read

        searched = research.search_source_code({"query": "copy_from_user", "path": "."})
        assert searched["ok"] and "drivers/net.c:2" in searched["output"], searched
        assert "other/ignored.c" not in searched["output"], searched

        probe = research.run_static_probe({"probe": "usercopy", "path": "."})
        assert probe["ok"] and "drivers/net.c:2" in probe["output"], probe

        outside = root.parent / (root.name + "-outside")
        outside.write_text("secret", encoding="utf-8")
        link = root / "drivers" / "escape.c"
        try:
            link.symlink_to(outside)
            result = research.read_source_file({"path": "drivers/escape.c"})
            assert not result["ok"], result
        finally:
            if link.is_symlink():
                link.unlink()
            outside.unlink()


if __name__ == "__main__":
    test_input_validation()
    test_read_only_source_tools()
    print("security research tests: OK")
