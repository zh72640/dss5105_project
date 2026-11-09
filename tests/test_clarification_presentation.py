"""Human missing-info summaries preserve LLM detail and trim only a fixed suffix."""
from copy import deepcopy
from datetime import date
from pathlib import Path
import tempfile
import unittest

from app.db.database import Database
from app.services.allocation.contracts import inspect_input
from app.services.allocation.alternatives import issue_messages
from app.services.allocation.preflight import issue
from app.services.chat import service as chat
from tests.test_order_selection import SelectionScript


MODEL_QUESTION = ('“The TrendCart order” does not identify an order unambiguously in the current message '
                  'or available context. Please provide its order ID.')
ORDER_QUESTION = 'Which order would you like to allocate?'
EXAMPLE_REQUEST = 'Provide the order ID, such as ORD-045.'
FALLBACK = ORDER_QUESTION + ' ' + EXAMPLE_REQUEST
SUMMARY = "I don't yet have the order number, product type, and quantity needed to prepare an allocation recommendation."


def missing_order(question=None):
    _, problems = inspect_input({})
    if question:
        problems.append(issue('AMBIGUOUS_MESSAGE','message',question))
    problems.append(issue('MISSING_ORDER_ID','order_id',FALLBACK))
    return problems


class ClarificationPresentation(unittest.TestCase):
    def test_summary_names_exactly_the_missing_fields(self):
        complete={'order_id':'ORD-024','product':'Vest','pieces':300,'due_date':'2026-04-15'}
        cases=[
            (('product',),'product type'),
            (('pieces',),'quantity'),
            (('order_id',),'order number'),
            (('order_id','pieces'),'order number and quantity'),
            (('order_id','product'),'order number and product type'),
            (('product','pieces'),'product type and quantity'),
            (('order_id','product','pieces'),'order number, product type, and quantity'),
        ]
        for absent,description in cases:
            with self.subTest(missing=absent):
                values={field:value for field,value in complete.items() if field not in absent}
                _,problems=inspect_input(values)
                self.assertEqual(issue_messages(problems),[
                    f"I don't yet have the {description} needed to prepare an allocation recommendation."])
        _,problems=inspect_input(complete)
        self.assertEqual(issue_messages(problems),[])
        _,invalid=inspect_input({**complete,'pieces':0})
        self.assertFalse(any(text.startswith("I don't yet have") for text in issue_messages(invalid)))

    def test_registered_product_missing_does_not_report_known_order_or_quantity(self):
        with tempfile.TemporaryDirectory() as folder:
            path=str(Path(folder)/'missing-product.sqlite3')
            created=chat.create(owner='alice',request_id='create-product',db_path=path,
                                as_of=date(2026,4,1),mode='llm')
            with Database(path) as db,db.transaction() as c:
                c.execute("UPDATE orders SET product='' WHERE order_id='ORD-024'")
            model=SelectionScript({'intent':'allocate_request','patch_operations':[
                {'op':'set','field':'order_id','value':'ORD-024','quote':'ORD-024'}]})
            result=chat.turn(created['session_id'],owner='alice',request_id='missing-product',
                expected_version=0,db_path=path,message='Allocate ORD-024.',registry=model)
            summary=result['explanation'].split('.')[0]+'.'
            self.assertEqual(summary,"I don't yet have the product type needed to prepare an allocation recommendation.")
            missing=next(p for p in result['issues'] if p['code']=='REQUIRED_INFO_INCOMPLETE')
            self.assertEqual(missing['missing_fields'],['product'])
            self.assertEqual(result['session']['task']['draft']['order_id'],'ORD-024')
            self.assertEqual(result['session']['task']['draft']['pieces'],300)
            self.assertFalse(model.offered)

    def test_human_summary_and_full_model_context_are_preserved(self):
        problems=missing_order(MODEL_QUESTION)
        before=deepcopy(problems)
        self.assertEqual(issue_messages(problems),[SUMMARY,MODEL_QUESTION,ORDER_QUESTION])
        self.assertEqual(problems,before)
        self.assertEqual(problems[0]['missing_fields'],['order_id','product','pieces'])

    def test_short_model_question_is_not_used_as_a_replacement_for_missing_info(self):
        question='Which TrendCart order do you mean?'
        self.assertEqual(issue_messages(missing_order(question)),[SUMMARY,question,ORDER_QUESTION])

    def test_explanations_and_detailed_requests_are_not_shortened(self):
        for question in ('The customer has several orders for this product. Please provide its order ID.',
                         'Which customer order do you mean?',
                         'Please provide the order ID, product type and quantity.'):
            with self.subTest(question=question):
                self.assertEqual(issue_messages(missing_order(question)),[SUMMARY,question,ORDER_QUESTION])

    def test_missing_order_without_model_detail_still_explains_the_missing_state(self):
        messages=issue_messages(missing_order())
        self.assertEqual(messages,[SUMMARY,ORDER_QUESTION])
        self.assertNotIn(EXAMPLE_REQUEST,' '.join(messages))
        explanation='The customer has several orders.'
        self.assertEqual(issue_messages(missing_order(explanation)),[SUMMARY,explanation,ORDER_QUESTION])
        _,partial=inspect_input({'product':'Vest'})
        partial.append(issue('MISSING_ORDER_ID','order_id',FALLBACK))
        self.assertEqual(issue_messages(partial),[
            "I don't yet have the order number and quantity needed to prepare an allocation recommendation.",ORDER_QUESTION])

    def test_model_authored_example_request_is_not_removed_with_the_fixed_suffix(self):
        self.assertEqual(issue_messages(missing_order(EXAMPLE_REQUEST)),[SUMMARY,EXAMPLE_REQUEST,ORDER_QUESTION])

    def test_unrelated_questions_and_unsupported_constraints_remain_visible(self):
        for question in ('What is your budget?', 'Which workshop should handle this order?',
                         'What delivery deadline should apply?'):
            with self.subTest(question=question):
                self.assertEqual(issue_messages(missing_order(question)),[SUMMARY,question,ORDER_QUESTION])
        problems=missing_order(MODEL_QUESTION)
        problems.append(issue('unsupported_constraint','unsupported','The budget cap must be withdrawn.'))
        self.assertEqual(issue_messages(problems),[SUMMARY,MODEL_QUESTION,ORDER_QUESTION,'The budget cap must be withdrawn.'])

    def test_other_missing_fields_are_stated_and_registered_errors_are_retained(self):
        _,problems=inspect_input({'order_id':'ORD-024'})
        summary="I don't yet have the product type and quantity needed to prepare an allocation recommendation."
        self.assertEqual(issue_messages(problems),[summary])
        problems.append(issue('ORDER_DATA_MISSING','product','The registered product is missing. Correct the order record.'))
        problems.append(issue('ORDER_DATA_MISSING','pieces','The registered quantity is missing. Correct the order record.'))
        self.assertEqual(issue_messages(problems),[summary]+[p['question'] for p in problems[-2:]])
        problems.append(issue('ORDER_NOT_FOUND','order_id','That order is not registered. Check the ID.'))
        self.assertIn('That order is not registered. Check the ID.',issue_messages(problems))

    def test_llm_response_keeps_detail_while_report_and_replay_keep_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            path=str(Path(folder)/'clarifications.sqlite3')
            created=chat.create(owner='alice',request_id='create',db_path=path,
                                as_of=date(2026,4,1),mode='llm')
            model=SelectionScript({'intent':'unsupported_or_ambiguous','ambiguity_reason':MODEL_QUESTION})
            kwargs=dict(owner='alice',request_id='trendcart',expected_version=0,db_path=path,
                        message='Allocate the TrendCart order.',registry=model)
            result=chat.turn(created['session_id'],**kwargs)
            expected=' '.join([SUMMARY,MODEL_QUESTION,ORDER_QUESTION])
            self.assertEqual(result['explanation'],expected)
            self.assertEqual(result['explanation'].count('provide'),1)
            self.assertNotIn(EXAMPLE_REQUEST,result['explanation'])
            self.assertEqual(result['task_state'],'BLOCKED')
            self.assertTrue(any(p['code']=='REQUIRED_INFO_INCOMPLETE' for p in result['issues']))
            self.assertTrue(any(p['code']=='MISSING_ORDER_ID' for p in result['issues']))
            self.assertIsNone(result['recommendation_id'])
            replay=chat.turn(created['session_id'],**kwargs)
            self.assertTrue(replay['replayed'])
            self.assertEqual(replay['explanation'],expected)
            self.assertEqual(model.extractions,1)
            self.assertFalse(model.offered)
            with Database(path) as db:
                self.assertEqual(db.connection.execute('SELECT COUNT(*) FROM working_order').fetchone()[0],0)

    def test_offline_reply_has_missing_info_and_no_fixed_example_request(self):
        with tempfile.TemporaryDirectory() as folder:
            result=chat.create(owner='alice',request_id='offline',db_path=str(Path(folder)/'offline.sqlite3'),
                               as_of=date(2026,4,1),mode='offline',message='Allocate cheapest.')
            text=result['assistant_message']['content']
            self.assertIn("I don't yet have the order number needed to prepare an allocation recommendation.",text)
            self.assertIn(ORDER_QUESTION,text)
            self.assertNotIn(EXAMPLE_REQUEST,text)
            self.assertNotIn('Required information is incomplete',text)
            self.assertNotIn('order_id',text)
