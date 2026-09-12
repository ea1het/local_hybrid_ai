import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import dr_backup_all


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
        with patch.object(dr_backup_all,"load_lifecycle",return_value=self.lifecycle()):
            self.assertEqual(dr_backup_all.detect_deployed_stacks(self.manifests(),runner),[0,1])

    def test_partial_deployment_is_not_silently_omitted(self):
        def runner(cmd): return CP(0 if cmd[-1]=="a" else 1)
        with patch.object(dr_backup_all,"load_lifecycle",return_value=self.lifecycle()):
            self.assertIn(1,dr_backup_all.detect_deployed_stacks(self.manifests(),runner))

    def test_rejects_lifecycle_container_not_owned_by_manifest(self):
        lifecycle=self.lifecycle(); lifecycle["stacks"]["1"]["required_containers"]=["foreign"]
        with patch.object(dr_backup_all,"load_lifecycle",return_value=lifecycle):
            with self.assertRaises(dr_backup_all.BackupAllError):
                dr_backup_all.detect_deployed_stacks(self.manifests(),lambda _:CP(1))

    def test_operational_env_copy_is_exact_and_private(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); source=root/"source.env"; dest=root/"copy.env"
            payload=b"SECRET=value\nLITELLM_SALT_KEY=identity\n"
            source.write_bytes(payload)
            dr_backup_all._copy_private(source,dest)
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

            with patch.object(dr_backup_all.dr,"run_command",side_effect=runner):
                dr_backup_all._create_archive_artifact(resource,manifest,base,destination)

            self.assertTrue(destination.is_file())
            self.assertIn(["docker","stop","--time","30","open-webui"],commands)
            self.assertIn(["docker","start","open-webui"],commands)

    def test_quiesced_archive_rejects_foreign_container(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td); source=base/"service"/"data"; source.mkdir(parents=True)
            resource={"config":{"source":{"type":"runtime-path","path":"${BASE_PATH}/service/data"},"quiesce_container":"foreign"}}
            manifest={"id":7,"owns":["container:open-webui"]}
            with self.assertRaises(dr_backup_all.BackupAllError):
                dr_backup_all._create_archive_artifact(resource,manifest,base,base/"backup.tar")


if __name__=="__main__": unittest.main()
