import concurrent.futures, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"external-operations"/"operations.py"

class ExternalOperationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.db=Path(self.temp.name)/"operations.db"
    def tearDown(self): self.temp.cleanup()
    def run_operation(self,*args,success=True):
        env=os.environ.copy(); env["FOUNDER_OPERATIONS_DB"]=str(self.db)
        result=subprocess.run([sys.executable,str(SCRIPT),*args],capture_output=True,text=True,env=env)
        if success:
            self.assertEqual(result.returncode,0,result.stderr); return json.loads(result.stdout)
        self.assertNotEqual(result.returncode,0); return result.stderr

    def test_autonomous_operation_is_idempotent_and_claimed_once(self):
        args=("prepare","--scope","calendar","--target","account/primary/new",
              "--operation","create_event","--intent","demo 2026-09-07 10:00",
              "--policy","autonomous")
        created=self.run_operation(*args)
        duplicate=self.run_operation(*args)
        self.assertTrue(created["created"]); self.assertTrue(duplicate["duplicate"])
        operation_id=created["operation"]["id"]
        self.assertTrue(self.run_operation("claim","--id",str(operation_id))["claimed"])
        repeated=self.run_operation("claim","--id",str(operation_id))
        self.assertTrue(repeated["reconciliation_required"])
        finished=self.run_operation("finish","--id",str(operation_id),"--outcome","uncertain",
                                    "--evidence","request timed out")
        self.assertEqual(finished["operation"]["status"],"uncertain")
        reconciled=self.run_operation("reconcile","--id",str(operation_id),"--outcome","completed",
                                      "--external-ref","event-1","--evidence","event fetched")
        self.assertEqual(reconciled["operation"]["external_ref"],"event-1")

    def test_approval_and_forbidden_policies_are_enforced(self):
        pending=self.run_operation("prepare","--scope","product","--target","admin/order/1",
                                   "--operation","refund_order","--intent","refund order 1",
                                   "--policy","approval")
        operation_id=pending["operation"]["id"]
        self.assertTrue(pending["approval_required"])
        self.assertIn("must be approved",self.run_operation("claim","--id",str(operation_id),success=False))
        self.run_operation("approve","--id",str(operation_id))
        self.assertTrue(self.run_operation("claim","--id",str(operation_id))["claimed"])
        error=self.run_operation("prepare","--scope","product","--target","admin/order/2",
                                 "--operation","delete","--intent","delete order 2",
                                 "--policy","forbidden",success=False)
        self.assertIn("forbidden",error)

    def test_concurrent_claim_allows_one_executor(self):
        prepared=self.run_operation("prepare","--scope","product","--target","admin/customer/1",
                                    "--operation","update_customer","--intent","set plan to pro",
                                    "--policy","autonomous")
        operation_id=str(prepared["operation"]["id"])
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _: self.run_operation("claim","--id",operation_id),range(2)))
        self.assertEqual(sum(bool(item.get("claimed")) for item in results),1)
        self.assertEqual(sum(bool(item.get("reconciliation_required")) for item in results),1)

if __name__=="__main__": unittest.main()
