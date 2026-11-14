import unittest
from unittest.mock import patch
from live import Live

class LiveTests(unittest.TestCase):
    def test_create_uses_documented_route_and_stable_user(self):
        with patch.object(Live,'request',return_value={'id':'computer-1'}) as request:
            self.assertEqual(Live().create('local-user','android')['id'],'computer-1')
            self.assertEqual(request.call_args.args,('/api/v1/computers',{'externalUserId':'local-user','name':'Time Machine / local-user','os':'android'}))
    def test_actions_reject_unsafe_transport_paths_and_unknown_tools(self):
        with self.assertRaises(ValueError):Live().action('../outside',{'action':'key'})
        with self.assertRaises(ValueError):Live().action('valid',{'action':'exec'})
    def test_missing_key_returns_clear_error(self):
        with patch.dict('os.environ',{'MARITIME_API_KEY':''}):
            with self.assertRaisesRegex(ValueError,'Settings'):Live().capture('valid')
