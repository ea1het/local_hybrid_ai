#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Protect the Stack6 externalized Git-memory recovery prerequisite."""
import importlib.util,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]/"src"/"local_ai_cli"/"restore"
MODULE_PATH=ROOT/"stack6_verify.py"
SPEC=importlib.util.spec_from_file_location("dr_stack6_verify_tested",MODULE_PATH);mod=importlib.util.module_from_spec(SPEC);assert SPEC.loader is not None;sys.modules[SPEC.name]=mod
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
SPEC.loader.exec_module(mod)
class Stack6VerifyTests(unittest.TestCase):
 def init_repo(self,root):
  tree=root/"runtime"/"service_-_hermes-memory"/"data";tree.mkdir(parents=True);mod.subprocess.run(["git","init","-b","main",str(tree)],check=True,stdout=mod.subprocess.DEVNULL);mod.subprocess.run(["git","-C",str(tree),"config","user.name","Test"],check=True);mod.subprocess.run(["git","-C",str(tree),"config","user.email","test@example.invalid"],check=True);(tree/"MEMORY.md").write_text("");(tree/"USER.md").write_text("user\n");mod.subprocess.run(["git","-C",str(tree),"add","MEMORY.md","USER.md"],check=True);mod.subprocess.run(["git","-C",str(tree),"commit","-m","init"],check=True,stdout=mod.subprocess.DEVNULL);mod.subprocess.run(["git","-C",str(tree),"remote","add","origin","ssh://git@gitea/example/hermes-memory.git"],check=True);head=mod.subprocess.run(["git","-C",str(tree),"rev-parse","HEAD"],check=True,text=True,stdout=mod.subprocess.PIPE).stdout.strip();mod.subprocess.run(["git","-C",str(tree),"update-ref","refs/remotes/origin/main",head],check=True);return tree
 def write_env(self,root):
  env=root/".env";env.write_text(f"BASE_PATH={root/'runtime'}\nHERMES_MEMORY_SERVICE=service_-_hermes-memory\nGITMEM_REPOSITORY=ssh://git@gitea/example/hermes-memory.git\nGITMEM_BRANCH=main\n");return env
 def test_verifier_accepts_clean_aligned_memory_repo(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);tree=self.init_repo(root);result=mod.verify_stack6_memory(self.write_env(root));self.assertEqual(result.working_tree,tree.resolve());self.assertEqual(result.required_files,("MEMORY.md","USER.md"))
 def test_soul_is_not_required(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);self.init_repo(root);self.assertNotIn("SOUL.md",mod.verify_stack6_memory(self.write_env(root)).required_files)
 def test_verifier_rejects_dirty_memory_repo(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);tree=self.init_repo(root);env=self.write_env(root);(tree/"USER.md").write_text("changed\n")
   with self.assertRaises(mod.Stack6VerifyError):mod.verify_stack6_memory(env)
 def test_verifier_rejects_untracked_required_file(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);tree=self.init_repo(root);env=self.write_env(root);mod.subprocess.run(["git","-C",str(tree),"rm","--cached","USER.md"],check=True,stdout=mod.subprocess.DEVNULL)
   with self.assertRaises(mod.Stack6VerifyError):mod.verify_stack6_memory(env)
 def test_verifier_rejects_missing_remote_tracking_ref(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);tree=self.init_repo(root);env=self.write_env(root);mod.subprocess.run(["git","-C",str(tree),"update-ref","-d","refs/remotes/origin/main"],check=True)
   with self.assertRaises(mod.Stack6VerifyError):mod.verify_stack6_memory(env)
if __name__=="__main__":unittest.main()
