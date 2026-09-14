import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from app.db.database import Database
from app.pipeline import process_request
from app.agent.llm_client import BackendError
from test_parser import SequenceBackend


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.db=Database()

    def tearDown(self):
        self.db.close()

    def run_request(self,text='Allocate ORD-045.',**kwargs):
        return process_request(text,database=self.db,backend=kwargs.pop('backend','offline'),**kwargs)

    def count(self,table):
        return self.db.connection.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]

    def state(self,order='ORD-045'):
        return self.db.connection.execute('SELECT state FROM orders WHERE order_id=?',(order,)).fetchone()[0]

    def test_01_normal_single_workshop_and_mapping(self):
        r=self.run_request('Allocate ORD-045 cheapest; exclude W3; at most one workshop.')
        self.assertTrue(r['result']['success']); self.assertEqual(self.count('working_order'),1)
        self.assertEqual(self.state(),'WORKING'); self.assertEqual(self.count('decision_log'),1)
        row=self.db.connection.execute('SELECT * FROM request_parsing_history').fetchone()
        self.assertEqual(row['parsed_order_id'],'ORD-045'); self.assertEqual(row['parsed_exclusion'],'["W3"]')
        self.assertEqual(row['parsed_objective'],'min_cost'); self.assertIsNone(row['parsed_pieces'])

    def test_02_multiple_workshops_conserve_pieces(self):
        r=self.run_request('Allocate ORD-093 fastest; at most two workshops.')
        parts=r['result']['allocation']; self.assertEqual(len(parts),2)
        self.assertEqual(sum(p['pieces'] for p in parts),100)
        self.assertEqual(self.count('working_order'),2)
        for p in parts:
            queue=self.db.connection.execute('SELECT current_queue_days FROM workshop_queue WHERE workshop_id=?',(p['workshop_id'],)).fetchone()[0]
            self.assertAlmostEqual(queue,p['queue_days']+p['processing_days'])

    def test_03_exclusion_applied_before_allocation(self):
        r=self.run_request('Allocate ORD-045 cheapest; exclude W3.')
        self.assertNotIn('W3',[p['workshop_id'] for p in r['result']['allocation']])
        self.assertEqual(r['result']['rejected']['W3'],'excluded_by_user')

    def test_04_count_limit_one(self):
        r=self.run_request('Allocate ORD-093 fastest; at most one workshop.')
        self.assertEqual(len(r['result']['allocation']),1)

    def test_05_no_eligible_workshop_unassigned(self):
        self.db.connection.execute("UPDATE workshops SET status='SUSPENDED'")
        r=self.run_request()
        self.assertEqual(r['result']['reason_codes'],['NO_ELIGIBLE_WORKSHOP'])
        self.assertEqual(self.count('unassigned_order'),1); self.assertEqual(self.count('working_order'),0)

    def test_06_capacity_infeasible_no_dirty_queue(self):
        self.db.connection.execute('UPDATE workshops SET max_batch_pieces=20')
        before=list(self.db.connection.execute('SELECT * FROM workshop_queue'))
        r=self.run_request('Allocate ORD-045; at most two workshops.')
        self.assertEqual(r['result']['reason_codes'],['CAPACITY_INFEASIBLE'])
        self.assertEqual(before,list(self.db.connection.execute('SELECT * FROM workshop_queue')))
        self.assertEqual(self.state(),'UNASSIGNED')

    def test_07_unknown_order_stops_at_retrieval(self):
        r=self.run_request('Allocate ORD-999.')
        self.assertEqual(r['result']['reason_codes'],['ORDER_NOT_FOUND'])
        self.assertNotIn('workshop_count',r['trace']); self.assertEqual(self.count('working_order'),0)

    def test_08_missing_identity_does_not_retrieve(self):
        r=self.run_request('Please allocate the order.')
        self.assertEqual(r['result']['decision_status'],'CLARIFY'); self.assertNotIn('order',r['trace'])

    def test_09_invalid_intent_stops(self):
        r=self.run_request('Cancel ORD-045.')
        self.assertEqual(r['result']['decision_status'],'DECLINE'); self.assertNotIn('order',r['trace'])

    def test_10_idempotent_replay_no_queue_growth(self):
        first=self.run_request(request_id='same'); before=list(self.db.connection.execute('SELECT * FROM workshop_queue'))
        second=self.run_request(request_id='same')
        self.assertTrue(second['replayed']); self.assertEqual(first['result'],second['result'])
        self.assertEqual(self.count('requests'),1); self.assertEqual(before,list(self.db.connection.execute('SELECT * FROM workshop_queue')))

    def test_11_reused_key_conflict(self):
        self.run_request(request_id='same')
        r=self.run_request('Allocate ORD-073.',request_id='same')
        self.assertEqual(r['result']['reason_codes'],['IDEMPOTENCY_CONFLICT']); self.assertEqual(self.count('requests'),1)

    def test_12_already_working_blocks_new_request(self):
        self.run_request()
        r=self.run_request()
        self.assertEqual(r['result']['reason_codes'],['ORDER_ALREADY_WORKING']); self.assertEqual(self.count('working_order'),1)

    def test_13_completed_and_lapsed_states(self):
        r=self.run_request('Allocate ORD-001.')
        self.assertEqual(r['result']['reason_codes'],['ORDER_ALREADY_COMPLETED'])
        self.db.connection.execute("UPDATE orders SET state='LAPSED' WHERE order_id='ORD-045'")
        self.assertEqual(self.run_request()['result']['reason_codes'],['ORDER_ALREADY_LAPSED'])

    def test_14_db_failure_rolls_back_work_and_keeps_error_audit(self):
        self.db.connection.execute("""CREATE TRIGGER fail_queue BEFORE UPDATE ON workshop_queue BEGIN
                                    SELECT RAISE(ABORT,'injected write failure'); END""")
        before=list(self.db.connection.execute('SELECT * FROM workshop_queue'))
        r=self.run_request('Allocate ORD-093 fastest; at most two workshops.')
        self.assertEqual(r['result']['reason_codes'],['DB_ERROR']); self.assertTrue(r['error_logged'])
        self.assertEqual(self.count('working_order'),0); self.assertEqual(self.state('ORD-093'),'READY')
        self.assertEqual(before,list(self.db.connection.execute('SELECT * FROM workshop_queue')))
        self.assertEqual(self.db.connection.execute('SELECT decision_status FROM decision_log').fetchone()[0],'ERROR')

    def test_15_llm_error_never_persists_bad_parsed_columns(self):
        r=self.run_request(backend=SequenceBackend('{bad'))
        self.assertEqual(r['result']['reason_codes'],['PARSER_ERROR'])
        self.assertEqual(self.count('request_parsing_history'),0); self.assertEqual(self.count('working_order'),0)
        self.assertEqual(r['parser_telemetry']['retry_count'],1)

    def test_16_preferred_suspended_cap_and_category(self):
        for text,code in [('Allocate ORD-045 to OldMill.','STATUS_SUSPENDED'),
                          ('Allocate ORD-073 to FreshStart.','EXCEEDS_300_PIECE_LIMIT'),
                          ('Allocate ORD-061 to QuickStitch.','CANNOT_MAKE_ACCESSORIES')]:
            with self.subTest(text=text):
                self.assertIn(code,self.run_request(text)['result']['reason_codes'])
        self.assertEqual(self.count('working_order'),0)

    def test_17_order_field_conflict_not_overwritten(self):
        for phrase in ('200 pieces','due 2026-04-01','customer: Fake Customer','400 hoodies'):
            r=self.run_request('Allocate ORD-045: '+phrase+'.')
            self.assertEqual(r['result']['decision_status'],'CLARIFY')
        self.assertEqual(self.state(),'READY')

    def test_18_queue_persistence_decay_and_missing(self):
        first=self.run_request(); self.assertEqual(first['trace']['queue']['W6'],1.)
        later=self.run_request('Allocate ORD-109 fastest.',as_of=date(2026,4,2))
        self.assertAlmostEqual(later['trace']['queue']['W6'],150/130)
        self.db.connection.execute("DELETE FROM workshop_queue WHERE workshop_id='W1'")
        self.assertEqual(self.run_request('Allocate ORD-073.')['result']['reason_codes'],['QUEUE_DATA_MISSING'])

    def test_19_hard_deadline_infeasible_soft_deadline_warning(self):
        r=self.run_request('Allocate ORD-093; must arrive by 2026-03-29.')
        self.assertEqual(r['result']['reason_codes'],['DEADLINE_INFEASIBLE'])
        r=self.run_request('Allocate ORD-093 fastest; at most two workshops.')
        self.assertTrue(r['result']['success']); self.assertIn('ESTIMATED_DEADLINE_MISS',r['result']['warnings'])
        self.assertEqual(self.count('unassigned_order'),0)

    def test_20_concurrent_same_key_and_different_key_same_order(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'concurrent.sqlite3'
            with Database(path): pass
            def submit(key):
                return process_request('Allocate ORD-045.',db_path=path,request_id=key,backend='offline')
            with ThreadPoolExecutor(max_workers=2) as executor:
                results=list(executor.map(submit,['same','same']))
            self.assertEqual(sum(r['replayed'] for r in results),1)
            with Database(path) as db:
                self.assertEqual(db.connection.execute('SELECT COUNT(*) FROM working_order').fetchone()[0],1)
            self.assertEqual(submit('new')['result']['reason_codes'],['ORDER_ALREADY_WORKING'])

    def test_unknown_workshop_and_temporal_rewind(self):
        self.assertEqual(self.run_request('Allocate ORD-045 exclude W99.')['result']['reason_codes'],['UNKNOWN_EXCLUDED_WORKSHOP'])
        self.assertEqual(self.run_request(as_of=date(2026,3,31))['result']['reason_codes'],['QUEUE_DATE_REWIND'])

    def test_full_db_unavailable_returns_error(self):
        with tempfile.TemporaryDirectory() as path:
            r=process_request('Allocate ORD-045.',db_path=path,backend='offline')
        self.assertEqual(r['result']['reason_codes'],['DB_ERROR']); self.assertFalse(r['error_logged'])
