import asyncio
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE=Path(__file__).resolve().parent
sys.path[:0]=[str(BASE/'qa'),str(BASE),str(BASE.parent/'peakcut-source')]

class AdapterTests(unittest.TestCase):
    def test_bridge_honors_stop_and_reports_offline(self):
        import threading
        from unittest.mock import Mock,patch
        import bridge
        response=Mock();response.cookies.get.return_value='example-session';response.json.return_value=[]
        local=Mock();local.post.return_value=response;local.get.return_value=response
        overview=Mock();overview.ok=True;overview.json.return_value={'posts':[]}
        local.get.side_effect=[response,response,overview]
        ack=Mock();ack.json.return_value={'stop_requested':True}
        stop=threading.Event()
        with patch.dict(os.environ,{'PEAKCUT_OWNER_EMAIL':'owner@example.com','PEAKCUT_OWNER_PASSWORD':'example-only','PEAKCUT_BRIDGE_TOKEN':'example-bridge'}),patch.object(bridge.requests,'Session',return_value=local),patch.object(bridge.requests,'post',return_value=ack) as post:
            bridge.run(stop,'https://studio.example.com','https://test.trycloudflare.com','test-run')
            self.assertTrue(stop.is_set())
            self.assertEqual(post.call_args_list[-1].args[0],'https://studio.example.com/bridge/offline')

    def test_encrypted_backup_restore_and_wrong_password(self):
        from state_io import backup,restore
        from cryptography.exceptions import InvalidTag
        with tempfile.TemporaryDirectory(dir=BASE/'tmp') as folder:
            root=Path(folder)/'data';root.mkdir()
            (root/'ai.json').write_text(json.dumps({'key':'do-not-expose'}))
            archive=Path(folder)/'state.enc';backup(root,archive,'test-password-123')
            self.assertNotIn(b'do-not-expose',archive.read_bytes())
            restored=Path(folder)/'restored';restore(archive,restored,'test-password-123')
            self.assertEqual(json.loads((restored/'ai.json').read_text())['key'],'do-not-expose')
            with self.assertRaises(InvalidTag):restore(archive,Path(folder)/'wrong','incorrect')

    def test_bridge_omits_sensitive_fields(self):
        from bridge import sanitize_jobs
        result=sanitize_jobs([{'id':'job','source_path':'private','user':'owner','source':{'token':'secret'},'clips':[{'id':'clip','src':'private','fixed_words':['text']}]}])
        self.assertNotIn('private',json.dumps(result));self.assertNotIn('secret',json.dumps(result))

    def test_actual_upstream_login_and_closed_signup(self):
        with tempfile.TemporaryDirectory(dir=BASE/'tmp') as folder:
            os.environ.update(PEAKCUT_DATA=folder,PEAKCUT_MODELS=str(Path(folder)/'models'),PEAKCUT_ACCOUNTS='1',PEAKCUT_PUBLIC_URL='https://studio.example.com',PEAKCUT_OWNER_EMAIL='owner@example.com',PEAKCUT_OWNER_PASSWORD='test-password-123',PEAKCUT_FETCH_MODEL='0',PEAKCUT_UPDATE_CHECK='0')
            import owner_app
            import httpx
            uid=owner_app.provision();self.assertEqual(owner_app.provision(),uid)
            async def check():
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=owner_app.app),base_url='https://studio.example.com') as client:
                    self.assertEqual((await client.post('/api/auth/signup',json={'email':'other@example.com','password':'test-password-123'})).status_code,403)
                    self.assertEqual((await client.get('/api/jobs')).status_code,401)
                    response=await client.post('/api/auth/login',json={'email':'owner@example.com','password':'test-password-123'},headers={'Origin':'https://studio.example.com'})
                    self.assertEqual(response.status_code,200,response.text)
                    self.assertTrue(response.cookies.get('peakcut_session'))
                    self.assertEqual((await client.get('/api/jobs')).status_code,200)
                    self.assertEqual((await client.get('/api/overview')).status_code,200)
                    self.assertEqual((await client.get('/api/accounts')).status_code,200)
            try:asyncio.run(check())
            finally:
                from studio import db
                db.engine.dispose()

if __name__=='__main__':unittest.main()
