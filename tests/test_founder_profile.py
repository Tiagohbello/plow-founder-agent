import json, os, sqlite3, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "founder-profile" / "profile.py"

class FounderProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.db = Path(self.temp.name) / "profile.db"
    def tearDown(self): self.temp.cleanup()
    def run_profile(self,*args):
        env=os.environ.copy(); env["FOUNDER_PROFILE_DB"]=str(self.db)
        result=subprocess.run([sys.executable,str(SCRIPT),*args],capture_output=True,text=True,env=env)
        self.assertEqual(result.returncode,0,result.stderr); return json.loads(result.stdout)
    def test_company_sources_and_permissions_are_separate_configuration(self):
        self.run_profile("set-company","--name","Example","--product","SaaS","--main-goal","Activation")
        self.run_profile("add-repo","--local-path","/work/product","--remote-url","https://github.test/example/product","--primary")
        profile=self.run_profile("set-source","--kind","sentry","--status","blocked","--evidence","session unavailable")
        self.assertEqual(profile["company"]["name"],"Example")
        self.assertEqual(profile["repositories"][0]["local_path"],"/work/product")
        self.assertEqual(profile["sources"][0]["status"],"blocked")
        policies={item["capability"]:item["policy"] for item in profile["permissions"]}
        self.assertEqual(policies["open_draft_pr"],"autonomous")
        self.assertEqual(policies["send_communication"],"approval")
        self.assertEqual(policies["merge"],"forbidden")

    def test_product_access_calendar_and_operation_policy_are_persisted(self):
        self.run_profile("add-repo","--local-path","/work/product","--primary")
        self.run_profile("set-access","--name","backoffice","--kind","admin",
                         "--url","https://admin.example.test","--environment","production",
                         "--credential-item-ref","vault-item-1","--status","available",
                         "--evidence","authenticated dashboard")
        self.run_profile("link-access-repo","--name","backoffice","--local-path","/work/product")
        self.run_profile("set-access-policy","--name","backoffice","--access-operation",
                         "refund_order","--policy","approval")
        profile=self.run_profile("set-calendar","--account","founder@example.test",
                                 "--calendar-id","primary","--calendar-id","team@example.test",
                                 "--default-calendar","primary","--timezone","America/Recife",
                                 "--working-hours",'{"mon":["09:00","18:00"]}',
                                 "--preferences",'{"preserve_meetings":true}',
                                 "--status","available","--is-default")
        access=profile["product_accesses"][0]
        self.assertEqual(access["repositories"],["/work/product"])
        self.assertEqual(access["policies"],{"refund_order":"approval"})
        self.assertEqual(access["credential_item_ref"],"vault-item-1")
        self.assertNotIn("password",access)
        calendar=profile["calendars"][0]
        self.assertEqual(calendar["calendar_ids"],["primary","team@example.test"])
        self.assertEqual(calendar["timezone"],"America/Recife")
        self.assertTrue(calendar["preferences"]["preserve_meetings"])
        updated=self.run_profile("set-access","--name","backoffice","--kind","admin",
                                 "--url","https://admin.example.test/dashboard","--environment","production",
                                 "--status","available")
        self.assertEqual(updated["product_accesses"][0]["credential_item_ref"],"vault-item-1")
        updated=self.run_profile("set-calendar","--account","founder@example.test",
                                 "--timezone","America/Recife","--status","available")
        self.assertTrue(updated["calendars"][0]["is_default"])
        self.assertEqual(updated["calendars"][0]["calendar_ids"],["primary","team@example.test"])
        self.assertTrue(updated["calendars"][0]["preferences"]["preserve_meetings"])

    def test_legacy_whatsapp_source_is_preserved_but_hidden(self):
        self.run_profile("show")
        connection=sqlite3.connect(self.db)
        connection.execute("INSERT INTO source VALUES (?,?,?,?,?)",
                           ("whatsapp","available","legacy","historical","2026-01-01T00:00:00Z"))
        connection.commit(); connection.close()
        profile=self.run_profile("show")
        self.assertNotIn("whatsapp",{item["kind"] for item in profile["sources"]})

    def test_additive_migration_preserves_existing_company_and_repository(self):
        connection=sqlite3.connect(self.db)
        connection.executescript("""
            CREATE TABLE company (id INTEGER PRIMARY KEY, name TEXT NOT NULL,
                product TEXT NOT NULL DEFAULT '', main_goal TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL);
            CREATE TABLE repository (id INTEGER PRIMARY KEY, local_path TEXT NOT NULL UNIQUE,
                remote_url TEXT NOT NULL DEFAULT '', is_primary INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL);
            CREATE TABLE source (kind TEXT PRIMARY KEY, status TEXT NOT NULL,
                locator TEXT NOT NULL DEFAULT '', evidence TEXT NOT NULL DEFAULT '', checked_at TEXT NOT NULL);
            CREATE TABLE permission (capability TEXT PRIMARY KEY, policy TEXT NOT NULL, updated_at TEXT NOT NULL);
            INSERT INTO company VALUES (1,'Legacy','SaaS','Retention','2026-01-01T00:00:00Z');
            INSERT INTO repository VALUES (7,'/work/legacy','',1,'2026-01-01T00:00:00Z');
        """)
        connection.commit(); connection.close()
        profile=self.run_profile("show")
        self.assertEqual(profile["company"]["name"],"Legacy")
        self.assertEqual(profile["repositories"][0]["id"],7)
        self.assertEqual(profile["product_accesses"],[])
        self.assertEqual(profile["calendars"],[])

if __name__ == "__main__": unittest.main()
