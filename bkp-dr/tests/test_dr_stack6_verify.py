import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "dr_stack6_verify.py"
SPEC = importlib.util.spec_from_file_location("dr_stack6_verify_tested", MODULE_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mod)


class Stack6VerifyTests(unittest.TestCase):
    def init_repo(self, root: Path) -> Path:
        tree = root / "runtime" / "service_-_hermes-memory" / "data"
        tree.mkdir(parents=True)
        mod.subprocess.run(["git", "init", "-b", "main", str(tree)], check=True, stdout=mod.subprocess.DEVNULL)
        mod.subprocess.run(["git", "-C", str(tree), "config", "user.name", "Test"], check=True)
        mod.subprocess.run(["git", "-C", str(tree), "config", "user.email", "test@example.invalid"], check=True)
        (tree / "MEMORY.md").write_text("", encoding="utf-8")
        (tree / "USER.md").write_text("user\n", encoding="utf-8")
        mod.subprocess.run(["git", "-C", str(tree), "add", "MEMORY.md", "USER.md"], check=True)
        mod.subprocess.run(["git", "-C", str(tree), "commit", "-m", "init"], check=True, stdout=mod.subprocess.DEVNULL)
        mod.subprocess.run(["git", "-C", str(tree), "remote", "add", "origin", "ssh://git@gitea/example/hermes-memory.git"], check=True)
        head = mod.subprocess.run(["git", "-C", str(tree), "rev-parse", "HEAD"], check=True, text=True, stdout=mod.subprocess.PIPE).stdout.strip()
        mod.subprocess.run(["git", "-C", str(tree), "update-ref", "refs/remotes/origin/main", head], check=True)
        return tree

    def write_env(self, root: Path) -> Path:
        env = root / ".env"
        env.write_text(
            f"BASE_PATH={root / 'runtime'}\n"
            "HERMES_MEMORY_SERVICE=service_-_hermes-memory\n"
            "GITMEM_REPOSITORY=ssh://git@gitea/example/hermes-memory.git\n"
            "GITMEM_BRANCH=main\n",
            encoding="utf-8",
        )
        return env

    def test_verifier_accepts_clean_aligned_memory_repo(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tree = self.init_repo(root)
            env = self.write_env(root)
            result = mod.verify_stack6_memory(env)
            self.assertEqual(result.working_tree, tree.resolve())
            self.assertEqual(result.required_files, ("MEMORY.md", "USER.md"))

    def test_soul_is_not_required(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.init_repo(root)
            env = self.write_env(root)
            result = mod.verify_stack6_memory(env)
            self.assertNotIn("SOUL.md", result.required_files)

    def test_verifier_rejects_dirty_memory_repo(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tree = self.init_repo(root)
            env = self.write_env(root)
            (tree / "USER.md").write_text("changed\n", encoding="utf-8")
            with self.assertRaises(mod.Stack6VerifyError):
                mod.verify_stack6_memory(env)

    def test_verifier_rejects_untracked_required_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tree = self.init_repo(root)
            env = self.write_env(root)
            mod.subprocess.run(["git", "-C", str(tree), "rm", "--cached", "USER.md"], check=True, stdout=mod.subprocess.DEVNULL)
            with self.assertRaises(mod.Stack6VerifyError):
                mod.verify_stack6_memory(env)

    def test_verifier_rejects_remote_tracking_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tree = self.init_repo(root)
            env = self.write_env(root)
            old = mod.subprocess.run(["git", "-C", str(tree), "rev-parse", "HEAD^"], text=True, stdout=mod.subprocess.PIPE)
            # One-commit repositories have no HEAD^; use an all-zero invalid ref by deleting tracking ref.
            mod.subprocess.run(["git", "-C", str(tree), "update-ref", "-d", "refs/remotes/origin/main"], check=True)
            with self.assertRaises(mod.Stack6VerifyError):
                mod.verify_stack6_memory(env)


if __name__ == "__main__":
    unittest.main()
