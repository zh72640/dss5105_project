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
        self.server=make_server(0,Path(self.temp.name)/'api.sqlite3')
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start(); self.base=f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.temp.cleanup()

    def get(self,path):
        with urlopen(self.base+path,timeout=5) as response:
            return response.status,json.load(response)

    def post(self,data,**headers):
        request=Request(self.base+'/api/requests',data=json.dumps(data).encode(),headers={'Content-Type':'application/json',**headers})
        try:
            with urlopen(request,timeout=5) as response:return response.status,json.load(response)
        except HTTPError as error:return error.code,json.load(error)

    def test_http_flow_and_history(self):
        self.assertEqual(self.get('/api/health')[1]['backend'],'offline')
        status,result=self.post({'message':'Allocate ORD-045.','request_id':'api-1'})
        self.assertEqual(status,200); self.assertTrue(result['result']['success'])
        self.assertTrue(self.post({'message':'Allocate ORD-045.','request_id':'api-1'})[1]['replayed'])
        self.assertEqual(self.get('/api/history')[1][0]['request_id'],'api-1')
        self.assertEqual(self.post({'message':'Allocate ORD-073.','request_id':'api-1'})[0],409)
        with urlopen(self.base+'/',timeout=5) as response:
            self.assertIn(b'/api/requests',response.read())

    def test_bad_inputs_and_cross_origin(self):
        for value in ([],{}, {'message':3}, {'message':'Allocate ORD-045.','objective':[]}, {'message':'Allocate ORD-045.','db':'/tmp/other'}):
            self.assertEqual(self.post(value)[0],400)
        self.assertEqual(self.post({'message':'Allocate ORD-045.'},Origin='https://example.com')[0],403)
        self.assertEqual(self.get('/api/history')[1],[])
