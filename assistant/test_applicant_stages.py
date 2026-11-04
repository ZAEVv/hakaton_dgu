import re
import unittest

from test_tracking import TrackingTests
from main import app, db


class ApplicantStagesTests(TrackingTests):
    def stages(self, link):
        page = self.applicant.get(link).get_data(as_text=True)
        return page, re.findall(r'<li class="stage[^\"]*"[^>]*>(.*?)</li>', page, re.S)

    def login_staff(self):
        self.staff.get('/login')
        self.assertEqual(self.staff.post('/login', data={'csrf_token': self.csrf(self.staff), 'login': 'staff', 'password': 'password'}).status_code, 302)

    def update(self, status, comment='служебный секрет', visibility='internal'):
        card = self.staff.get('/admin/tickets/1').get_data(as_text=True)
        version = re.search(r'name="version" value="(\d+)"', card).group(1)
        result = self.staff.post('/admin/tickets/1', data={'csrf_token': self.csrf(self.staff), 'version': version, 'status': status, 'assignee_id': '', 'comment': comment, 'visibility': visibility})
        self.assertEqual(result.status_code, 302)

    def test_new_ticket_shows_five_stages_without_inventing_progress(self):
        page = self.applicant.get(self.create('Лампа')).get_data(as_text=True)
        stages = re.findall(r'<li class="stage[^\"]*"[^>]*>(.*?)</li>', page, re.S)
        self.assertEqual(len(stages), 5)
        for stage, label in zip(stages, ('Отправлено', 'Просмотрено', 'Поиск свободного сотрудника', 'В работе', 'Выполнено')):
            self.assertIn(label, stage)
        self.assertIn('Текущий этап', stages[0])
        for stage in stages[1:]:
            self.assertIn('Не зафиксирован', stage)

    def test_every_staff_status_including_exception_states(self):
        link = self.create('Лампа')
        self.login_staff()
        for status, index in [('На рассмотрении', 1), ('Назначен исполнитель', None), ('Поиск свободного сотрудника', 2), ('В работе', 3), ('Решена', 4), ('Нужны уточнения', None), ('Отклонена', None), ('Новая', 0)]:
            with self.subTest(status=status):
                self.update(status)
                page, stages = self.stages(link)
                self.assertNotIn('служебный секрет', page)
                self.assertEqual(sum('Текущий этап' in stage for stage in stages), int(index is not None))
                if index is not None:
                    self.assertIn('Текущий этап', stages[index])
                    self.assertEqual(page.count('aria-current="step"'), 1)
                else:
                    self.assertIn('Текущее состояние: ' + status, page)
                    self.assertNotIn('aria-current="step"', page)

    def test_assigned_does_not_imply_search_but_real_search_is_preserved(self):
        link = self.create('Лампа')
        self.login_staff()
        self.update('Назначен исполнитель')
        page, stages = self.stages(link)
        self.assertIn('Текущее состояние: Назначен исполнитель', page)
        self.assertIn('Не зафиксирован', stages[2])
        self.update('Поиск свободного сотрудника')
        page, stages = self.stages(link)
        self.assertIn('Текущий этап', stages[2])
        self.update('Назначен исполнитель')
        page, stages = self.stages(link)
        self.assertIn('Текущее состояние: Назначен исполнитель', page)
        self.assertIn('Зафиксирован ранее', stages[2])

    def test_skips_and_returns_only_show_evidenced_statuses(self):
        link = self.create('Лампа')
        self.login_staff()
        self.update('Решена')
        page, stages = self.stages(link)
        self.assertIn('Зафиксирован ранее', stages[0])
        for stage in stages[1:4]:
            self.assertIn('Не зафиксирован', stage)
        self.assertIn('Текущий этап', stages[4])
        self.update('Новая')
        page, stages = self.stages(link)
        self.assertIn('Текущий этап', stages[0])
        self.assertIn('Зафиксирован ранее', stages[4])
        for stage in stages[1:4]:
            self.assertIn('Не зафиксирован', stage)
        self.assertNotIn('служебный секрет', page)

    def test_legacy_and_unknown_status_do_not_invent_stages(self):
        link = self.create('Лампа')
        for status, marker in [('Закрыта', 'Текущий этап'), ('неизвестный', 'Не зафиксирован')]:
            with self.subTest(status=status), app.app_context():
                db().execute('UPDATE tickets SET status=? WHERE id=1', (status,))
                db().commit()
                page, stages = self.stages(link)
                self.assertIn(marker, stages[4])
                for stage in stages[1:4]:
                    self.assertIn('Не зафиксирован', stage)

    def test_invalid_link_has_no_ticket_or_stage_information(self):
        self.create('уникальный текст')
        response = self.applicant.get('/ticket/incorrect')
        self.assertEqual(response.status_code, 404)
        self.assertNotIn('уникальный текст', response.get_data(as_text=True))
        self.assertNotIn('Этапы заявки', response.get_data(as_text=True))
