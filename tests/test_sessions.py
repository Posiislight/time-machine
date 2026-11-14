import tempfile
import unittest
from core import Store
from sessions import Sessions
from fixtures import seeded_session

class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.engine=Sessions(Store(self.temp.name))
    def tearDown(self): self.temp.cleanup()
    def demo(self,uncertain=False):
        sid=seeded_session(self.engine,uncertain)
        cp=self.engine.state(sid)['checkpoints'][0]['id']
        return sid,cp
    def test_rewind_preserves_external_effects_without_restoring_observations(self):
        sid,cp=self.demo()
        plan=self.engine.preview(sid,cp)
        self.assertTrue(any('payment' in w and 'cannot undo' in w for w in plan['warnings']))
        branch=self.engine.rewind(sid,cp,plan['receipt'],True)
        restored=self.engine.state(branch)
        self.assertEqual(len(restored['effects']),2)
        self.assertEqual(restored['document']['resources']['agent']['state']['step'],'Compare basket')
        self.assertNotIn('network',restored['document']['resources'])
        self.assertIn('network',restored['document']['historical_observations'])
        self.assertEqual(self.engine.state(sid)['document']['resources']['agent']['state']['step'],'Connection lost after checkout')
        with self.assertRaisesRegex(ValueError,'already recorded'):
            self.engine.effect(branch,'checkout-order-001','payment','completed','Duplicate payment')
        self.assertEqual(len(Sessions(Store(self.temp.name)).state(branch)['effects']),2)
    def test_uncertain_payment_blocks_until_evidence_reconciles_it(self):
        sid,cp=self.demo(True)
        plan=self.engine.preview(sid,cp)
        with self.assertRaisesRegex(ValueError,'blocked'):
            self.engine.rewind(sid,cp,plan['receipt'],True)
        effect=next(e for e in plan['effects'] if e['kind']=='payment')
        with self.assertRaises(ValueError):self.engine.reconcile(sid,effect['id'],'completed','')
        self.engine.reconcile(sid,effect['id'],'completed','Checked order demo-001 in merchant service')
        with self.assertRaisesRegex(ValueError,'changed'):
            self.engine.rewind(sid,cp,plan['receipt'],True)
        fresh=self.engine.preview(sid,cp)
        self.engine.rewind(sid,cp,fresh['receipt'],True)
    def test_stale_preview_and_missing_acknowledgment_rejected(self):
        sid,cp=self.demo()
        plan=self.engine.preview(sid,cp)
        with self.assertRaisesRegex(ValueError,'acknowledge'):
            self.engine.rewind(sid,cp,plan['receipt'])
        self.engine.effect(sid,'another-booking','booking','completed','Hotel reservation')
        with self.assertRaisesRegex(ValueError,'changed'):
            self.engine.rewind(sid,cp,plan['receipt'],True)
    def test_checkpoint_isolation_and_cross_session_rejected(self):
        sid,cp=self.demo()
        other,_=self.demo()
        with self.assertRaises(ValueError):self.engine.preview(other,cp)
        with self.assertRaises(ValueError):self.engine.reconcile(other,self.engine.state(sid)['effects'][0]['id'],'completed','evidence')

class RunnerTests(unittest.TestCase):
    setUp=SessionTests.setUp
    tearDown=SessionTests.tearDown
    demo=SessionTests.demo
    def test_external_dispatch_crash_persists_pending_and_prevents_duplicate(self):
        from session_runner import SessionRunner
        sid,cp=self.demo()
        class Adapter:
            calls=0
            def capture(self):return {'recovery':'logical','state':{'screen':'checkout'}}
            def execute(self,action,operation_key=None):
                self.calls+=1
                raise TimeoutError('Merchant response lost')
        adapter=Adapter()
        # Create a dedicated single-resource session for the real dispatch wrapper.
        sid=self.engine.create('Instrumented tool',{'browser':adapter.capture()})
        runner=SessionRunner(self.engine,sid,{'browser':adapter})
        cp=runner.checkpoint('Before purchase')
        with self.assertRaises(TimeoutError):
            runner.act('browser',{'click':'pay'},operation_key='purchase-1',effect_kind='payment',description='Purchase headphones')
        self.assertTrue(self.engine.preview(sid,cp)['blocked'])
        with self.assertRaises(ValueError):
            runner.act('browser',{'click':'pay'},operation_key='purchase-1',effect_kind='payment',description='Purchase headphones')
        self.assertEqual(adapter.calls,1)

if __name__=='__main__':unittest.main()
