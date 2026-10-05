import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from app.server import make_server


class LocalAPI(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.server=make_server(0,Path(self.temp.name)/'api.sqlite3',require_auth=False)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start(); self.base=f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.temp.cleanup()

    def get(self,path):
        with urlopen(self.base+path,timeout=5) as response:
            return response.status,json.load(response)

    def post(self,data,path='/api/requests',**headers):
        request=Request(self.base+path,data=json.dumps(data).encode(),headers={'Content-Type':'application/json',**headers})
        try:
            with urlopen(request,timeout=5) as response:return response.status,json.load(response)
        except HTTPError as error:
            with error:
                return error.code,json.load(error)

    def test_http_flow_and_history(self):
        self.assertEqual(self.get('/api/health')[1]['backend'],'offline')
        status,result=self.post({'message':'Allocate ORD-045.','request_id':'api-1'})
        self.assertEqual(status,200); self.assertTrue(result['result']['success'])
        self.assertTrue(self.post({'message':'Allocate ORD-045.','request_id':'api-1'})[1]['replayed'])
        self.assertEqual(self.get('/api/history')[1][0]['request_id'],'api-1')
        self.assertEqual(self.post({'message':'Allocate ORD-073.','request_id':'api-1'})[0],409)
        with urlopen(self.base+'/legacy',timeout=5) as response:
            self.assertIn(b'/api/requests',response.read())

    def test_bad_inputs_and_cross_origin(self):
        for value in ([],{}, {'message':3}, {'message':'Allocate ORD-045.','objective':[]}, {'message':'Allocate ORD-045.','db':'/tmp/other'}):
            self.assertEqual(self.post(value)[0],400)
        self.assertEqual(self.post({'message':'Allocate ORD-045.'},Origin='https://example.com')[0],403)
        self.assertEqual(self.get('/api/history')[1],[])

    def test_session_http_clarification_preview_confirm_and_restore(self):
        self.assertEqual(self.post({'session_id':'api-session'},path='/api/sessions')[0],200)
        route='/api/sessions/api-session/turns'
        first={'request_id':'turn-1','expected_version':0,'message':'Allocate cheapest.'}
        self.assertEqual(self.post(first,path=route)[1]['session']['state'],'AWAITING_CLARIFICATION')
        second={'request_id':'turn-2','expected_version':1,'message':'ORD-045'}
        self.assertEqual(self.post(second,path=route)[1]['result']['decision_status'],'REVIEW')
        self.assertEqual(self.get('/api/orders/ORD-045')[1]['state'],'READY')
        self.assertEqual(self.get('/api/sessions/api-session')[1]['version'],2)
        confirm={'request_id':'turn-3','expected_version':2,'action':'confirm'}
        self.assertTrue(self.post(confirm,path=route)[1]['committed'])
        self.assertTrue(self.post(confirm,path=route)[1]['replayed'])
        self.assertEqual(self.get('/api/sessions/api-session')[1]['state'],'CLOSED')
        with urlopen(self.base+'/sessions.js',timeout=5) as response:
            self.assertIn(b'localStorage',response.read())

    def test_session_http_validation_version_and_origin(self):
        self.assertEqual(self.post({'session_id':'s'},path='/api/sessions')[0],200)
        route='/api/sessions/s/turns'
        body={'request_id':'one','expected_version':0,'message':'ORD-045'}
        self.assertEqual(self.post(body,path=route,Origin='https://example.com')[0],403)
        self.assertEqual(self.post(body,path=route)[0],200)
        self.assertEqual(self.post({**body,'request_id':'two'},path=route)[0],409)
        for invalid in ({},[],{**body,'expected_version':True},{**body,'db':'/tmp/other'}):
            self.assertEqual(self.post(invalid,path=route)[0],400)
        self.assertEqual(self.post({},path='/api/sessions',Origin='https://example.com')[0],403)
        self.assertEqual(self.post({'backend':'llm'},path='/api/sessions')[0],400)

    def test_lifecycle_api_partial_cancel_reallocate_reassign_complete(self):
        self.post({'message':'Allocate ORD-045 to Nimble Needle.'})
        def event(action, **kwargs):
            order = self.get('/api/orders/ORD-045')[1]
            body = {'action':action,'order_id':'ORD-045','actor':'api-operator','reason':'Production confirmation',
                    'expected_version':order['version'],'event_id':f"event-{order['version']}",**kwargs}
            status,result = self.post(body,path='/api/events')
            self.assertEqual(status,200,result)
            return body,result
        body,partial = event('complete',workshop_id='W6',pieces=50)
        self.assertEqual(partial['order']['completed_pieces'],50)
        replay = self.post(body,path='/api/events')[1]
        self.assertTrue(replay['replayed'])
        event('cancel')
        allocation = self.post({'message':'Allocate ORD-045 to Nimble Needle.'})[1]
        self.assertEqual(allocation['result']['allocation'][0]['pieces'],100)
        event('reassign',preferred_workshop='W8')
        _,final = event('complete',workshop_id='W8',pieces=100)
        self.assertEqual(final['order']['state'],'COMPLETED')
        self.assertEqual(len(self.get('/api/orders/ORD-045')[1]['events']),4)
        latest = self.get('/api/history')[1][0]
        self.assertEqual(latest['order_id'],'ORD-045')
        self.assertEqual(latest['status'],'COMPLETE')

    def test_lifecycle_api_rejects_stale_version_unknown_order_and_bad_fields(self):
        self.post({'message':'Allocate ORD-045.'})
        body = {'action':'cancel','order_id':'ORD-045','actor':'api-operator','reason':'Change allocation',
                'expected_version':0,'event_id':'stale'}
        self.assertEqual(self.post(body,path='/api/events')[0],409)
        self.assertEqual(self.post({**body,'expected_version':1},path='/api/events')[0],409)
        self.assertEqual(self.post({**body,'order_id':'ORD-999','event_id':'missing'},path='/api/events')[0],404)
        for data in ([],{}, {**body,'actor':''},{**body,'expected_version':True}, {**body,'db':'/tmp/other'},
                     {**body,'as_of':'2026-04-03'}, {**body,'action':[]}):
            with self.subTest(data=data):
                self.assertEqual(self.post(data,path='/api/events')[0],400)
        self.assertEqual(self.post(body,path='/api/events',Origin='https://example.com')[0],403)
        self.assertEqual(self.get('/api/orders/ORD-045')[1]['state'],'WORKING')

    def test_lifecycle_page_exposes_review_and_explicit_operations(self):
        with urlopen(self.base+'/legacy',timeout=5) as response:
            page=response.read()
        for marker in (b'/api/events',b'/api/orders/',b'expected_version',b'event-actor',b'event-reason'):
            self.assertIn(marker,page)
