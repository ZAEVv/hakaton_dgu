import unittest
from ai_helper import assist, AssistantUnavailable, DANGER_TEXT, UNKNOWN_TEXT
from demo_knowledge import DEMO_KNOWLEDGE, DEMO_NOTICE


class AssistantTests(unittest.TestCase):
    def setUp(self):
        self.knowledge = [dict(id=1, question='Как подключить проектор?', answer='Проверенная инструкция.', is_verified=1),
                          dict(id=2, question='Пароль Wi-Fi?', answer='Секрет', is_verified=0)]
        self.categories = ('Электрика', 'Оборудование', 'Другое')

    def run_model(self, text, result):
        return assist(text, self.knowledge, self.categories, 'test-key', classify=lambda *args: result)

    def test_danger_works_without_api_and_never_returns_instructions(self):
        for text in ('Из розетки идут искры', 'Запах гари', 'Как заменить проводку самому?'):
            with self.subTest(text=text):
                self.assertEqual(assist(text, [], self.categories, '')['answer'], DANGER_TEXT)

    def test_uses_only_checked_knowledge(self):
        response = self.run_model('Как подключить проектор?', {'type':'question', 'category':None, 'knowledge_id':1})
        self.assertEqual(response['answer'], 'Проверенная инструкция.')
        with self.assertRaises(AssistantUnavailable):
            self.run_model('Расскажи про сеть', {'type':'question', 'category':None, 'knowledge_id':2})
        self.assertIn('не сообщает', assist('Какой пароль от Wi-Fi сотрудников?', [], self.categories, '')['answer'])

    def test_demo_answers_are_visibly_labelled(self):
        result = assist('Как подключить проектор?', DEMO_KNOWLEDGE, self.categories, 'key',
                        classify=lambda *args: {'type': 'question', 'category': None, 'knowledge_id': -1})
        self.assertIn(DEMO_NOTICE, result['answer'])
        self.assertEqual(result['source'], DEMO_NOTICE)

    def test_unknown_question_never_invents_answer(self):
        self.assertEqual(self.run_model('Когда починят?', {'type':'question', 'category':None, 'knowledge_id':None})['answer'], UNKNOWN_TEXT)

    def test_fault_returns_original_editable_draft(self):
        response = self.run_model('Не работает свет', {'type':'fault', 'category':'Электрика', 'knowledge_id':None})
        self.assertEqual(response['draft'], 'Не работает свет')
        self.assertEqual(response['category'], 'Электрика')

    def test_incomplete_and_invalid_category(self):
        self.assertTrue(self.run_model('Сломалось', {'type':'unclear', 'category':None, 'knowledge_id':None})['question'])
        with self.assertRaises(AssistantUnavailable):
            self.run_model('Сломалось', {'type':'fault', 'category':'Несуществующая', 'knowledge_id':None})
        with self.assertRaises(AssistantUnavailable):
            self.run_model('Сломалось', {'type':'other'})

    def test_input_limit_and_missing_key(self):
        with self.assertRaises(ValueError): assist('x' * 2001, [], self.categories, 'key')
        with self.assertRaises(AssistantUnavailable): assist('Не работает свет', [], self.categories, '')


if __name__ == '__main__':
    unittest.main()
