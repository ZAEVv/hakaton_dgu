import unittest
from ai_helper import assist, danger_detected, AssistantUnavailable, DANGER_TEXT, UNKNOWN_TEXT
from demo_knowledge import DEMO_KNOWLEDGE, DEMO_NOTICE


class AssistantTests(unittest.TestCase):
    def setUp(self):
        self.knowledge = [dict(id=1, question='Как подключить проектор?', answer='Проверенная инструкция.', is_verified=1),
                          dict(id=2, question='Пароль Wi-Fi?', answer='Секрет', is_verified=0)]
        self.categories = ('Электрика', 'Оборудование', 'Другое')

    def run_model(self, text, result):
        return assist(text, self.knowledge, self.categories, 'test-key', classify=lambda *args: result)

    def test_danger_works_without_api_and_never_returns_instructions(self):
        for text in ('Искрит', 'Дым', 'Гарь', 'Замена проводки', 'Оголённый провод',
                     'Ударило током', 'Из розетки идут искры', 'Запах гари',
                     'Как заменить проводку самому?'):
            with self.subTest(text=text):
                self.assertEqual(assist(text, [], self.categories, '')['answer'], DANGER_TEXT)

    def test_electrical_danger_variants_bypass_classifier(self):
        for text in ('В комнате гарь', 'Провод оголён', 'Ударило меня током',
                     'Током ударило', 'Проводку нужно заменить', 'Как поменять провод?',
                     'Розетку хочу починить', 'Изоляция провода повреждена'):
            with self.subTest(text=text):
                result = assist(text, self.knowledge, self.categories, '',
                                classify=lambda *args: self.fail('classifier called'))
                self.assertEqual(result['type'], 'danger')
                self.assertEqual(result['answer'], DANGER_TEXT)

    def test_electrical_change_verbs_do_not_match_pronouns(self):
        for text in ('У меня сломалась розетка', 'Розетка у меня не работает',
                     'У меня сломался провод'):
            with self.subTest(text=text):
                self.assertFalse(danger_detected(text))
        for text in ('поменять проводку', 'проводку меняют', 'менять провод',
                     'проводку меняли', 'проводку заменяют'):
            with self.subTest(text=text):
                self.assertTrue(danger_detected(text))

    def test_wire_word_boundaries_and_electrical_safety(self):
        for text in ('проводит собрание по замене мебели', 'проводить замену мебели',
                     'проводник обсуждает замену мебели', 'сопроводительное письмо о замене мебели'):
            with self.subTest(text=text):
                self.assertFalse(danger_detected(text))
        for text in ('заменить провод', 'замена провода', 'ремонт проводку',
                     'проводка повреждена', 'заменить электропроводку',
                     'оголённые провода', 'повреждены провода', 'заменить провода',
                     'отремонтировать кабель', 'заменить розетку', 'ударило током',
                     'искры и дым', 'запах газа'):
            with self.subTest(text=text):
                self.assertTrue(danger_detected(text))

    def test_danger_summary_does_not_return_model_instructions(self):
        result = assist('Искрит розетка', [], self.categories, 'key', summarize_danger=True,
                        classify=lambda *args: {'summary': 'Разберите розетку и возьмитесь за провод.'})
        self.assertIsNone(result['draft'])

    def test_uses_only_checked_knowledge(self):
        response = self.run_model('Как подключить проектор?', {'type':'question', 'category':None, 'knowledge_id':1})
        self.assertEqual(response['answer'], 'Проверенная инструкция.')
        with self.assertRaises(AssistantUnavailable):
            self.run_model('Расскажи про сеть', {'type':'question', 'category':None, 'knowledge_id':2})
        self.assertIn('не сообщает', assist('Какой пароль от Wi-Fi сотрудников?', [], self.categories, '')['answer'])

    def test_sensitive_knowledge_is_filtered_before_classification(self):
        records = [
            dict(id=3, question='Пароль Wi-Fi: hunter2', answer='Инструкция', is_verified=1),
            dict(id=4, question='Как войти?', answer='Токен: abc123', is_verified=1),
            dict(id=5, question='Как подключиться?', answer='Выберите сеть колледжа.', is_verified=1),
        ]
        seen = []
        def classify(text, titles, *args):
            seen.extend(titles)
            return {'type': 'question', 'knowledge_id': 5}
        result = assist('Как подключиться?', records, self.categories, 'key', classify=classify)
        self.assertEqual(seen, [{'id': 5, 'question': 'Как подключиться?'}])
        self.assertEqual(result['answer'], records[2]['answer'])

    def test_heuristic_can_miss_unlabelled_secrets(self):
        # These arbitrary values could be secrets: absence of a marker is not proof of safety.
        record = dict(id=9, question='Сеть колледжа: x7q9z2',
                      answer='Значение: x7q9z2', is_verified=1)
        seen = []
        def classify(text, titles, *args):
            seen.extend(titles)
            return {'type': 'question', 'knowledge_id': None}
        assist('Как подключиться?', [record], self.categories, 'key', classify=classify)
        self.assertEqual(seen, [{'id': 9, 'question': record['question']}])

    def test_selected_verified_password_answer_is_not_disclosed(self):
        knowledge = [dict(id=3, question='Как подключиться к сети?',
                          answer='Пароль Wi-Fi: secret123', is_verified=1)]
        with self.assertRaises(AssistantUnavailable):
            assist('Как подключиться к сети?', knowledge, self.categories, 'key',
                   classify=lambda *args: {'type': 'question', 'category': None, 'knowledge_id': 3})

    def test_sensitive_verified_fields_are_refused(self):
        for field, value in (('answer', 'PASSWORD = hunter2'),
                             ('answer', 'Токен: abc123'),
                             ('answer', 'Ключ доступа: abc123'),
                             ('source', 'Пароль: secret123'),
                             ('question', 'Пароль: secret123')):
            with self.subTest(field=field):
                record = dict(id=3, question='Сеть', answer='Инструкция', is_verified=1)
                record[field] = value
                if field == 'source':
                    result = assist('Как подключиться к сети?', [record], self.categories, 'key',
                                    classify=lambda *args: {'type': 'question', 'knowledge_id': 3})
                    self.assertIn('не сообщает', result['answer'])
                    self.assertIsNone(result['source'])
                    self.assertNotIn(value, str(result))
                else:
                    with self.assertRaises(AssistantUnavailable):
                        assist('Как подключиться к сети?', [record], self.categories, 'key',
                               classify=lambda *args: {'type': 'question', 'knowledge_id': 3})

    def test_normal_password_instruction_without_secret_is_usable(self):
        record = dict(id=8, question='Как войти в аккаунт?',
                      answer='Введите свой пароль и нажмите «Войти».', is_verified=1)
        result = assist('Как войти в аккаунт?', [record], self.categories, 'key',
                        classify=lambda *args: {'type': 'question', 'knowledge_id': 8})
        self.assertEqual(result['answer'], record['answer'])

    def test_safe_network_instruction_is_returned(self):
        record = dict(id=3, question='Как подключиться к сети?',
                      answer='Откройте настройки сети и выберите сеть колледжа.',
                      source='Инструкция по сети', is_verified=1)
        result = assist('Как подключиться к сети?', [record], self.categories, 'key',
                        classify=lambda *args: {'type': 'question', 'knowledge_id': 3})
        self.assertEqual(result['answer'], record['answer'])
        self.assertEqual(result['source'], record['source'])

    def test_demo_answers_are_visibly_labelled(self):
        result = assist('Как подключить проектор?', DEMO_KNOWLEDGE, self.categories, 'key',
                        classify=lambda *args: {'type': 'question', 'category': None, 'knowledge_id': -1})
        self.assertIn(DEMO_NOTICE, result['answer'])
        self.assertEqual(result['source'], DEMO_NOTICE)

    def test_unknown_question_never_invents_answer(self):
        self.assertEqual(self.run_model('Когда починят?', {'type':'question', 'category':None, 'knowledge_id':None})['answer'], UNKNOWN_TEXT)

    def test_fault_returns_short_model_summary(self):
        response = self.run_model('Не работает свет', {'type':'fault', 'category':'Электрика', 'knowledge_id':None, 'summary':'Неисправно освещение.'})
        self.assertEqual(response['draft'], 'Неисправно освещение.')
        self.assertEqual(response['category'], 'Электрика')

    def test_invalid_fault_summary_is_not_used(self):
        for summary in (None, '', 'x' * 301):
            with self.assertRaises(AssistantUnavailable):
                self.run_model('Не работает свет', {'type':'fault', 'category':'Электрика', 'knowledge_id':None, 'summary':summary})

    def test_danger_summary_keeps_warning_without_classifier(self):
        result = assist('Из розетки идут искры', [], self.categories, 'key', summarize_danger=True,
                        classify=lambda *args: self.fail('classifier called'))
        self.assertEqual(result['answer'], DANGER_TEXT)
        self.assertIsNone(result['draft'])

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
