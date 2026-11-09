"""Regression cases from the October 31 audit; temporary fixtures only."""
from datetime import date
from pathlib import Path
import tempfile
import unittest

from app.db.database import Database
from app.services.chat import service as chat
from app.services.chat.context import build_context
from app.services.chat.extraction import validate_candidate, ExtractionValidationError
from app.services.chat.interpretation import rule_interpret
from app.services.intake.normalization import order_ids
from app.services.chat.constraint_patches import apply_interpretation
from app.services.chat import allocation_preparation
from app.services.chat.explanation_guard import claim_problem
from tests.test_allocation_node import ExtractionScript, actions


class IntakeRemediation(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.db = str(Path(folder.name) / 'test.sqlite3')
        self.sid = chat.create(owner='alice', request_id='create', db_path=self.db,
            as_of=date(2026,4,1), mode='llm')['session_id']
        self.session = chat.inspect(self.sid, owner='alice', db_path=self.db)
        with Database(self.db) as db:
            self.context = build_context(db.connection, self.session)

    def extract(self, text, *patches, answers=()):
        # Focused field fixtures still need to retain explicit order references.
        ids = order_ids(text, allow_short=True)
        if len(ids) == 1 and not any(field == 'order_id' for _, field, _, _ in patches):
            patches = (*patches, ('set', 'order_id', ids[0], text))
        return validate_candidate({'intent':'modify_constraints', 'answered_question_ids':list(answers),
            'patch_operations':[dict(op=op, field=field, value=value, quote=quote)
                                for op,field,value,quote in patches]}, message=text, conversation=self.context)

    def test_short_dates_use_business_year_and_explicit_years_survive(self):
        for month_day in ('Mar 31', 'Apr 10', 'Mar 17', 'Mar 29'):
            month, day = month_day.split()
            expected = f'2026-{3 if month == "Mar" else 4:02d}-{int(day):02d}'
            result = self.extract('ORD-045 due '+month_day,
                ('set','due_date',expected.replace('2026','2027'),month_day))
            self.assertEqual(result.patch_operations[0].value, expected)
        result = self.extract('ORD-045 due Mar 29, 2027', ('set','due_date','2027-03-29','Mar 29, 2027'))
        self.assertEqual(result.patch_operations[0].value,'2027-03-29')
        with self.assertRaises(ExtractionValidationError):
            self.extract('Order placed Mar 29; due Apr 10.', ('set','due_date','2026-03-29','Mar 29'))

    def test_dispatch_today_does_not_replace_explicit_due_date(self):
        text = 'ORD-041 needs a home today. 600 beanies, back by Apr 21.'
        due = [p.value for p in rule_interpret(text, self.context).patch_operations if p.field == 'due_date']
        self.assertEqual(due, ['2026-04-21'])
        result = self.extract(text, ('set', 'due_date', '2026-04-21', 'Apr 21'),
                              ('set', 'product', 'Beanie', 'beanies'))
        self.assertEqual(result.patch_operations[0].value, '2026-04-21')
        with self.assertRaises(ExtractionValidationError):
            self.extract(text, ('set', 'due_date', '2026-04-01', text))
        self.assertEqual(self._due('ORD-041 due today.'), '2026-04-01')
        self.assertEqual(self._due('ORD-041 back by tomorrow.'), '2026-04-02')
        self.assertEqual(self._due('ORD-041 截止明天.'), '2026-04-02')

    def test_pending_due_date_answer_is_modify_constraints(self):
        plain = {**self.context, 'pending_questions': [],
                 'draft': {**self.context['draft'], 'order_id': None}}
        self.assertFalse(any(p.field == 'due_date' for p in rule_interpret('Apr 21', plain).patch_operations))
        self.context['draft']['order_id'] = 'ORD-041'
        self.context['pending_questions'] = [{'field': 'due_date',
            'question': 'Please restate the due date including its year.'}]
        parsed = rule_interpret('Apr 21', self.context)
        self.assertEqual(parsed.intent, 'modify_constraints')
        self.assertEqual([p.value for p in parsed.patch_operations if p.field == 'due_date'], ['2026-04-21'])
        result = self.extract('Apr 21', ('set', 'due_date', '2026-04-21', 'Apr 21'))
        self.assertEqual(result.intent, 'modify_constraints')
        self.assertEqual(result.patch_operations[0].value, '2026-04-21')

    def _due(self, text):
        values = [p.value for p in rule_interpret(text, self.context).patch_operations if p.field == 'due_date']
        self.assertEqual(len(values), 1)
        return values[0]

    def test_dynamic_names_add_remove_clear_and_undo_preserve_other_constraints(self):
        self.context['workshop_names']['W1'] = 'Renamed Stitch'
        task = self.session['task']
        task['draft'].update(exclusion=['W3'], objective='min_cost')
        for text,patch,expected in (
            ('Also exclude Renamed Stitch.',('set','exclusion',['Renamed Stitch'],'Renamed Stitch'),['W1','W3']),
            ('Do not exclude W3.',('remove','exclusion',['W3'],'W3'),['W1']),
            ('Undo the exclusion change.',('undo','exclusion',None,'Undo the exclusion change.'),['W1','W3']),
            ('Clear exclusions.',('set','exclusion',[],'Clear exclusions.'),[]),
        ):
            self.context['draft'] = task['draft']
            interpretation = self.extract(text, patch)
            task = apply_interpretation(task, interpretation, self.context['current_sequence'])
            self.context['current_sequence'] += 2
            self.assertEqual(task['draft']['exclusion'], expected)
            self.assertEqual(task['draft']['objective'],'min_cost')

    def test_false_negation_and_unsupported_fact_evidence_are_rejected(self):
        for text,patch in (
            ('Do not exclude W3.', ('set','exclusion',['W3'],'W3')),
            ('Allocate ORD-109.', ('set','customer','Invented Customer','ORD-109')),
            ('Allocate ORD-109.', ('set','product','Hoodie','ORD-109')),
            ('Allocate ORD-109.', ('set','category','TOPS','ORD-109')),
            ('Allocate ORD-109.', ('unset','preferred_workshop',None,'ORD-109')),
            ('Do not clear preferred workshop.', ('unset','preferred_workshop',None,'Do not clear preferred workshop.')),
            ('Do not clear exclusions.', ('set','exclusion',[],'Do not clear exclusions.')),
            ('Undo the objective change.', ('undo','exclusion',None,'Undo the objective change.')),
        ):
            with self.subTest(patch=patch), self.assertRaises(ExtractionValidationError):
                self.extract(text, patch)

    def test_clear_preferred_and_grounded_withdrawal(self):
        result = self.extract('Clear preferred workshop.', ('unset','preferred_workshop',None,'Clear preferred workshop.'))
        self.assertEqual(result.patch_operations[0].op, 'unset')
        self.assertEqual(self.extract('Remove budget.', answers=['unsupported_constraint']).answered_question_ids,['unsupported_constraint'])
        with self.assertRaises(ExtractionValidationError):
            self.extract('Allocate ORD-109.', answers=['unsupported_constraint'])

    def test_minor_objective_typo_remains_grounded(self):
        result = self.extract('Allocate ORD-109 at minimun cost.', ('set','objective','min_cost','minimun cost'))
        self.assertEqual(result.patch_operations[0].value,'min_cost')

    def test_pending_replacement_due_date_blocks_old_registered_value(self):
        text = 'ORD-066 due date moved; will confirm the new date after the call.'
        interpretation = self.extract(text, ('set','order_id','ORD-066','ORD-066'))
        result = allocation_preparation.prepare(db_path=self.db, session_id=self.sid, owner='alice',
            request_id='pending', interpretation=interpretation, as_of=date(2026,4,1), sequence=1)
        self.assertFalse(result['ready'])
        self.assertTrue(any(i['field'] == 'due_date' for i in result['issues']))
        # Supplying the new date resolves this field-scoped blocker.
        interpretation = self.extract('The due date is Apr 15.', ('set','due_date','2026-04-15','Apr 15'))
        result = allocation_preparation.prepare(db_path=self.db, session_id=self.sid, owner='alice',
            request_id='date', interpretation=interpretation, as_of=date(2026,4,1), sequence=3)
        self.assertFalse(any(i['code'] == 'AMBIGUOUS_MESSAGE' for i in result['issues']))

    def test_registered_difference_is_in_plan_and_survives_revision(self):
        model = ExtractionScript(patches=[('pieces',999)], actions=actions())
        result = chat.turn(self.sid, owner='alice', request_id='allocate', expected_version=0,
            db_path=self.db, message='Allocate ORD-045, 999 pieces.', registry=model)
        expected = [{'field':'pieces','supplied':999,'recorded':150}]
        self.assertEqual(result['allocation']['resolved_differences'], expected)
        self.assertEqual(result['cards'][0]['result']['resolved_differences'], expected)
        self.context['current_sequence'] = 3
        revision = self.extract('Also exclude W3.', ('add','exclusion',['W3'],'W3'))
        changed = allocation_preparation.prepare(db_path=self.db, session_id=self.sid, owner='alice',
            request_id='change', interpretation=revision, as_of=date(2026,4,1), sequence=3)
        self.assertEqual(changed['resolved_differences'], expected)
        with Database(self.db) as db:
            self.assertEqual(db.connection.execute('SELECT COUNT(*) FROM working_order').fetchone()[0],0)

    def test_explanation_rejects_invented_fact_and_keeps_saved_plan(self):
        from langchain_core.messages import AIMessage
        model = ExtractionScript(actions=[*actions()[:3], AIMessage(content='Allocate ORD-999 to W99 for 99999 units.')])
        result = chat.turn(self.sid, owner='alice', request_id='allocate', expected_version=0,
            db_path=self.db, message='Allocate ORD-045.', registry=model)
        self.assertIn('Verified summary', result['explanation'])
        self.assertNotIn('99999', result['explanation'])
        self.assertEqual(result['allocation']['order_id'], 'ORD-045')
        self.assertEqual(claim_problem('Estimated completion 2099-01-01.', result['allocation']), 'unsupported_date')
        self.assertFalse(result['committed'])

    def test_due_date_follow_up_updates_the_saved_request_and_recommends(self):
        import json
        from langchain_core.messages import AIMessage
        from tests.test_architecture_alignment import NativeScript

        class SupplementScript(NativeScript):
            def invoke(self, messages):
                system = messages[0]['content'] if isinstance(messages[0], dict) else messages[0].content
                user = messages[-1]['content'] if isinstance(messages[-1], dict) else messages[-1].content
                if 'Classify the current user message' in system:
                    route = 'compat' if 'Apr 21' in user else 'allocation'
                    return AIMessage(content='{"task_type":"%s"}' % route)
                return super().invoke(messages)

            def invoke_task(self, mode, key, bundle):
                message = bundle.as_messages()[-1]['content']
                if 'Apr 21' in message:
                    patches = [{'op': 'set', 'field': 'due_date', 'value': '2026-04-21', 'quote': 'Apr 21'}]
                else:
                    patches = [{'op': 'set', 'field': 'order_id', 'value': 'ORD-045', 'quote': 'ORD-045'},
                               {'op': 'set', 'field': 'due_date', 'value': '2026-04-01', 'quote': 'today'}]
                return {'text': json.dumps({'intent': 'allocate_request', 'patch_operations': patches})}, {}

        model = SupplementScript(actions=actions())
        blocked = chat.turn(self.sid, owner='alice', request_id='partial', expected_version=0,
            db_path=self.db, message='Allocate ORD-045 today.', registry=model)
        self.assertIsNone(blocked['recommendation_id'])
        self.assertEqual(blocked['session']['task']['draft']['order_id'], 'ORD-045')
        self.assertTrue(any(item['field'] == 'due_date' for item in blocked['session']['task']['issues']))
        self.assertIn('due date', blocked['assistant_message']['content'])
        self.assertNotIn('has not changed the allocation requirements', blocked['assistant_message']['content'])
        answered = chat.turn(self.sid, owner='alice', request_id='date',
            expected_version=blocked['session_version'], db_path=self.db, message='Apr 21', registry=model)
        self.assertIsNotNone(answered['recommendation_id'])
        self.assertFalse(answered['committed'])
        self.assertEqual(answered['allocation']['order_id'], 'ORD-045')
