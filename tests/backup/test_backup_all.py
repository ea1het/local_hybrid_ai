# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Protect global disaster-recovery backup publication and destination safety.

The suite verifies deployed-stack discovery, ownership checks, exact/private
operational-environment capture, quiesced archive handling and the fail-closed
rule that backup destinations cannot overlap or contain STACKS_ROOT/BASE_PATH.
These are orchestration-contract tests; they do not perform a real production backup.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import backup_all


class CP:
    def __init__(self, rc=0, stdout="", stderr=""):
        self.returncode = rc
        self.stdout = stdout
        self.stderr = stderr


class BackupAllTests(unittest.TestCase):
    def manifests(self):
        return {
            0:{"id":0,"directory":"stack0","owns":[]},
            1:{"id":1,"directory":"stack1","owns":["container:a","container:b"]},
            2:{"id":2,"directory":"stack2","owns":["container:c"]},
        }

    def lifecycle(self):
        return {"schema_version":1,"stacks":{
            "0":{"directory":"stack0","required_containers":[]},
            "1":{"directory":"stack1","required_containers":["a","b"]},
            "2":{"directory":"stack2","required_containers":["c"]},
        }}

    def test_detects_only_deployed_stacks_and_always_platform(self):
        def runner(cmd): return CP(0 if cmd[-1]=="b" else 1)
        with patch.object(backup_all,"load_lifecycle",return_value=self.lifecycle()):
            self.assertEqual(backup_all.detect_deployed_stacks(self.manifests(),runner),[0,1])

    def test_partial_deployment_is_not_silently_omitted(self):
        def runner(cmd): return CP(0 if cmd[-1]=="a" else 1)
        with patch.object(backup_all,"load_lifecycle",return_value=self.lifecycle()):
            self.assertIn(1,backup_all.detect_deployed_stacks(self.manifests(),runner))

    def test_rejects_lifecycle_container_not_owned_by_manifest(self):
        lifecycle=self.lifecycle(); lifecycle["stacks"]["1"]["required_containers"]=["foreign"]
        with patch.object(backup_all,"load_lifecycle",return_value=lifecycle):
            with self.assertRaises(backup_all.BackupAllError):
                backup_all.detect_deployed_stacks(self.manifests(),lambda _:CP(1))

    def test_backup_destination_outside_source_trees_is_allowed(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            stacks=root/"stacks"; runtime=root/"runtime"; backup=root/"backup"
            stacks.mkdir(); runtime.mkdir(); backup.mkdir()
            self.assertEqual(
                backup_all.validate_backup_destination(backup,stacks,runtime),
                backup.resolve(),
            )

    def test_backup_destination_equal_or_below_protected_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            stacks=root/"stacks"; runtime=root/"runtime"
            stacks.mkdir(); runtime.mkdir(); (runtime/"backups").mkdir()
            for destination in (stacks, stacks/"backup", runtime, runtime/"backups"):
                with self.subTest(destination=destination):
                    with self.assertRaises(backup_all.BackupAllError):
                        backup_all.validate_backup_destination(destination,stacks,runtime)

    def test_backup_destination_ancestor_of_protected_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            protected_parent=root/"docker"; protected_parent.mkdir()
            stacks=protected_parent/"stacks"; runtime=protected_parent/"runtime"
            stacks.mkdir(); runtime.mkdir()
            with self.assertRaises(backup_all.BackupAllError):
                backup_all.validate_backup_destination(protected_parent,stacks,runtime)

    def test_backup_destination_resolves_dotdot_and_symlink_before_overlap_check(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            stacks=root/"stacks"; runtime=root/"runtime"; alias=root/"runtime-link"
            stacks.mkdir(); runtime.mkdir(); alias.symlink_to(runtime,target_is_directory=True)
            disguised=root/"stacks"/".."/"runtime-link"
            with self.assertRaises(backup_all.BackupAllError):
                backup_all.validate_backup_destination(disguised,stacks,runtime)

    def test_unsafe_destination_rejected_before_root_mode_validation(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            stacks=root/"stacks"; runtime=root/"runtime"
            stacks.mkdir(); runtime.mkdir()
            values={"STACKS_ROOT":str(stacks),"BASE_PATH":str(runtime)}
            with (
                patch.object(backup_all.planner,"load_manifests",return_value={}),
                patch.object(backup_all,"detect_deployed_stacks",return_value=[0]),
                patch.object(backup_all.planner,"resolve_plan",return_value=[0]),
                patch.object(backup_all.planner,"build_plan_entries",return_value=[]),
                patch.object(backup_all.planner,"build_backup_plan",return_value=([],[])),
                patch.object(backup_all,"_resource_map",return_value={}),
                patch.object(backup_all.planner,"preflight_runtime_sources"),
                patch.object(backup_all.planner,"read_dotenv_presence",return_value=values),
                patch.object(backup_all.planner,"resolve_base_path",return_value=runtime),
                patch.object(backup_all.planner,"require_env_value",return_value=str(stacks)),
                patch.object(backup_all.filesystem,"validate_existing_root") as validate_root,
            ):
                with self.assertRaisesRegex(backup_all.BackupAllError,"unsafe backup destination overlaps STACKS_ROOT"):
                    backup_all.execute_backup_all(stacks)
                validate_root.assert_not_called()

    def test_operational_env_copy_is_exact_and_private(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); source=root/"source.env"; dest=root/"copy.env"
            payload=b"SECRET=value\nLITELLM_SALT_KEY=identity\n"
            source.write_bytes(payload)
            backup_all._copy_private(source,dest)
            self.assertEqual(dest.read_bytes(),payload)
            self.assertEqual(dest.stat().st_mode & 0o777,0o600)

    def test_quiesced_archive_stops_archives_restarts_and_waits(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td); source=base/"service"/"data"; source.mkdir(parents=True)
            (source/"db.sqlite").write_text("state",encoding="utf-8")
            destination=base/"backup.tar"
            resource={"config":{"source":{"type":"runtime-path","path":"${BASE_PATH}/service/data"},"quiesce_container":"open-webui"}}
            manifest={"id":7,"owns":["container:open-webui"]}
            commands=[]

            def runner(cmd):
                commands.append(cmd)
                if cmd[:4]==["docker","inspect","-f","{{.State.Running}}"]:
                    return CP(stdout="true\n")
                if cmd[:4]==["docker","inspect","-f","{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}"]:
                    return CP(stdout="running|healthy\n")
                return CP(stdout="open-webui\n")

            with patch.object(backup_all.planner,"run_command",side_effect=runner):
                backup_all._create_archive_artifact(resource,manifest,base,destination)

            self.assertTrue(destination.is_file())
            self.assertIn(["docker","stop","--time","30","open-webui"],commands)
            self.assertIn(["docker","start","open-webui"],commands)

    def test_quiesced_archive_rejects_foreign_container(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td); source=base/"service"/"data"; source.mkdir(parents=True)
            resource={"config":{"source":{"type":"runtime-path","path":"${BASE_PATH}/service/data"},"quiesce_container":"foreign"}}
            manifest={"id":7,"owns":["container:open-webui"]}
            with self.assertRaises(backup_all.BackupAllError):
                backup_all._create_archive_artifact(resource,manifest,base,base/"backup.tar")


if __name__=="__main__": unittest.main()
