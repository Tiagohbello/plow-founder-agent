import hashlib, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"runtime"/"variant_init.py"

class VariantInitTests(unittest.TestCase):
    def test_reconcile_updates_owned_files_preserves_data_and_backs_up(self):
        with tempfile.TemporaryDirectory() as value:
            root=Path(value)/"variant"; home=Path(value)/"home"; payload=root/"payload"
            (payload/"skills"/"sample").mkdir(parents=True); (home/"skills"/"sample").mkdir(parents=True)
            source=payload/"skills"/"sample"/"SKILL.md"; source.write_text("new\n")
            target=home/"skills"/"sample"/"SKILL.md"; target.write_text("old\n")
            data=home/"skills"/"sample"/"data.db"; data.write_text("keep")
            digest=hashlib.sha256(source.read_bytes()).hexdigest()
            (root/"manifest.json").write_text(json.dumps({"version":"test","files":{"skills/sample/SKILL.md":digest}}))
            env=os.environ.copy(); env.update({"FOUNDER_AGENT_ROOT":str(root),"HERMES_HOME":str(home),
                                               "HERMES_UID":str(os.getuid()),"HERMES_GID":str(os.getgid())})
            result=subprocess.run([sys.executable,str(SCRIPT)],capture_output=True,text=True,env=env)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(target.read_text(),"new\n"); self.assertEqual(data.read_text(),"keep")
            self.assertEqual(home.stat().st_mode & 0o7777, 0o3770)
            self.assertEqual((home/"skills").stat().st_mode & 0o7777, 0o3770)
            backups=list((home/"backups"/"founder-agent").glob("**/SKILL.md"))
            self.assertEqual(len(backups),1); self.assertEqual(backups[0].read_text(),"old\n")
            second=subprocess.run([sys.executable,str(SCRIPT)],capture_output=True,text=True,env=env)
            self.assertIn("0 file(s) reconciled",second.stdout)

    def test_reconcile_retires_only_unchanged_owned_file_and_backs_it_up(self):
        with tempfile.TemporaryDirectory() as value:
            root=Path(value)/"variant"; home=Path(value)/"home"; payload=root/"payload"
            payload.mkdir(parents=True); (home/"skills"/"whatsapp").mkdir(parents=True)
            required=payload/"SOUL.md"; required.write_text("soul\n")
            retired=home/"skills"/"whatsapp"/"SKILL.md"; retired.write_text("owned\n")
            manifest={"version":"test","files":{"SOUL.md":hashlib.sha256(required.read_bytes()).hexdigest()},
                      "retired_files":{"skills/whatsapp/SKILL.md":hashlib.sha256(retired.read_bytes()).hexdigest()}}
            (root/"manifest.json").write_text(json.dumps(manifest))
            env=os.environ.copy(); env.update({"FOUNDER_AGENT_ROOT":str(root),"HERMES_HOME":str(home),
                                               "HERMES_UID":str(os.getuid()),"HERMES_GID":str(os.getgid())})
            first=subprocess.run([sys.executable,str(SCRIPT)],capture_output=True,text=True,env=env)
            self.assertEqual(first.returncode,0,first.stderr); self.assertFalse(retired.exists())
            backups=list((home/"backups"/"founder-agent").glob("**/whatsapp/SKILL.md"))
            self.assertEqual(len(backups),1); self.assertEqual(backups[0].read_text(),"owned\n")
            second=subprocess.run([sys.executable,str(SCRIPT)],capture_output=True,text=True,env=env)
            self.assertIn("0 retired",second.stdout)

if __name__ == "__main__": unittest.main()
