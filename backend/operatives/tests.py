from datetime import date, timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from .icnf import match, normalize_number, parse_list_text
from .models import IcnfTechnician, Operative

STRONG_PW = 'Fogo-Bom-2026!x'

SAMPLE_LIST = """                                           TÉCNICOS CREDENCIADOS EM FOGO CONTROLADO
                                                              Atualização: 27 de agosto de 2026
Nº ICNF         Nome                                                  Concelho de Residência          Validade Credenciação
3-2005          Hermínio da Silva Botelho                                     Vila Real                       Vitalícia
7-2005          Miguel Gomes da Cruz                                                                           Vitalícia
547-2026        João Ricardo Valejo Castanheiro                               Portimão                       29/07/2031
"""


def load_sample_list():
    list_date, rows = parse_list_text(SAMPLE_LIST)
    IcnfTechnician.objects.bulk_create(IcnfTechnician(list_date=list_date, **r) for r in rows)


@override_settings(SECURE_SSL_REDIRECT=False)
class OperativeTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user('u', password='x'))

    def test_create_with_optional_fields_empty(self):
        r = self.client.post('/operacionais/novo/', {'name': 'Op'})
        self.assertRedirects(r, '/operacionais/', fetch_redirect_response=False)
        self.assertEqual(Operative.objects.get().email, '')

    def test_invalid_input_rejected_and_kept(self):
        r = self.client.post('/operacionais/novo/', {'name': '', 'email': 'nao-email'})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Operative.objects.exists())
        self.assertContains(r, 'nao-email')

    def test_edit(self):
        op = Operative.objects.create(name='Op', email='a@example.com', phone='1', certification_level='A')
        self.client.post(f'/operacionais/{op.pk}/editar/', {'name': 'Op 2', 'phone': '2'})
        op.refresh_from_db()
        self.assertEqual((op.name, op.phone), ('Op 2', '2'))

    def test_only_staff_can_delete(self):
        op = Operative.objects.create(name='Op', email='a@example.com', phone='1', certification_level='A')
        self.client.post(f'/operacionais/{op.pk}/eliminar/')
        self.assertTrue(Operative.objects.exists())


class IcnfListTests(TestCase):
    def test_parse(self):
        list_date, rows = parse_list_text(SAMPLE_LIST)
        self.assertEqual(list_date, date(2026, 8, 27))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0], {'number': '3-2005', 'name': 'Hermínio da Silva Botelho', 'concelho': 'Vila Real',
                                   'lifetime': True, 'valid_until': None})
        self.assertEqual((rows[1]['name'], rows[1]['concelho']), ('Miguel Gomes da Cruz', ''))
        self.assertEqual((rows[2]['concelho'], rows[2]['valid_until']), ('Portimão', date(2031, 7, 29)))

    def test_normalize_number(self):
        self.assertEqual(normalize_number(' 547 / 2026 '), '547-2026')

    def test_match(self):
        load_sample_list()
        ok = match('547/2026', 'João Ricardo Valejo Castanheiro')
        self.assertTrue(ok['found'] and ok['name_match'])
        self.assertTrue(match('547-2026', 'joao castanheiro')['name_match'])  # case/accents/partial
        wrong = match('547-2026', 'Maria Silva')
        self.assertTrue(wrong['found'] and not wrong['name_match'])
        self.assertFalse(match('999-2026', 'X')['found'])


class CredentialStateTests(TestCase):
    def op(self, **kw):
        base = dict(name='T', email='t@example.com', phone='', certification_level='',
                    credential_type=Operative.CRED_TECNICO, credential_number='1-2020',
                    credential_status=Operative.STATUS_VALIDADA)
        return Operative(**{**base, **kw})

    def test_is_tecnico_and_expiry(self):
        today = date.today()
        self.assertTrue(self.op(credential_lifetime=True).is_tecnico)
        self.assertTrue(self.op(credential_valid_until=today + timedelta(days=400)).is_tecnico)
        expiring = self.op(credential_valid_until=today + timedelta(days=30))
        self.assertTrue(expiring.is_tecnico and expiring.credential_expiring)
        expired = self.op(credential_valid_until=today - timedelta(days=1))
        self.assertTrue(expired.credential_expired)
        self.assertFalse(expired.is_tecnico)
        self.assertFalse(self.op(credential_status=Operative.STATUS_PENDENTE).is_tecnico)
        self.assertFalse(self.op(credential_type=Operative.CRED_OPERACIONAL).is_tecnico)


@override_settings(SECURE_SSL_REDIRECT=False)
class RegistrationAndValidationTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user('admin', password='x', is_staff=True)
        load_sample_list()

    def register(self, **overrides):
        data = {'form_type': 'register', 'reg_username': 'joao', 'reg_fullname': 'João Ricardo Valejo Castanheiro',
                'reg_email': 'joao@example.com', 'reg_password': STRONG_PW, 'reg_confirm': STRONG_PW,
                'reg_cred_type': 'tecnico_fc', 'reg_cred_number': '547/2026', **overrides}
        with mock.patch('core.views._send_async'):
            return self.client.post('/login/', data)

    def test_register_as_technician_creates_pending_credential(self):
        self.register()
        op = Operative.objects.get(user__username='joao')
        self.assertEqual((op.credential_type, op.credential_number, op.credential_status),
                         ('tecnico_fc', '547-2026', 'pendente'))
        self.assertFalse(op.user.is_active)

    def test_register_operacional_has_no_number(self):
        self.register(reg_cred_type='operacional')
        op = Operative.objects.get(user__username='joao')
        self.assertEqual((op.credential_number, op.credential_status), ('', 'na'))

    def test_register_rejects_bad_or_duplicate_number(self):
        r = self.register(reg_cred_number='547')
        self.assertIn('número-ano', r.context['reg_error'])
        self.assertContains(r, 'João Ricardo')  # values kept
        self.register()
        r = self.register(reg_username='outro', reg_email='outro@example.com')
        self.assertIn('já está associado', r.context['reg_error'])

    def test_pending_page_shows_icnf_match(self):
        self.register()
        self.client.force_login(self.staff)
        r = self.client.get('/utilizadores/pendentes/')
        self.assertContains(r, 'N.º e nome coincidem')
        self.assertContains(r, '29/07/2031')

    def test_validate_copies_validity_and_notifies(self):
        self.register()
        op = Operative.objects.get(user__username='joao')
        self.client.force_login(self.staff)
        with mock.patch('operatives.views.send_async') as send:
            self.client.post(f'/utilizadores/credenciacao/{op.pk}/', {'decision': 'validar'})
        op.refresh_from_db()
        self.assertEqual((op.credential_status, op.credential_valid_until, op.credential_reviewed_by),
                         ('validada', date(2031, 7, 29), self.staff))
        self.assertEqual(send.call_args.args[2], ['joao@example.com'])
        self.assertTrue(op.is_tecnico)

    def test_reject_requires_reason(self):
        self.register()
        op = Operative.objects.get(user__username='joao')
        self.client.force_login(self.staff)
        with mock.patch('operatives.views.send_async'):
            self.client.post(f'/utilizadores/credenciacao/{op.pk}/', {'decision': 'recusar', 'reason': ''})
            op.refresh_from_db()
            self.assertEqual(op.credential_status, 'pendente')
            self.client.post(f'/utilizadores/credenciacao/{op.pk}/', {'decision': 'recusar', 'reason': 'Não consta'})
        op.refresh_from_db()
        self.assertEqual((op.credential_status, op.credential_rejection_reason), ('recusada', 'Não consta'))

    def test_non_staff_cannot_review(self):
        self.register()
        op = Operative.objects.get(user__username='joao')
        self.client.force_login(User.objects.create_user('normal', password='x'))
        self.client.post(f'/utilizadores/credenciacao/{op.pk}/', {'decision': 'validar'})
        op.refresh_from_db()
        self.assertEqual(op.credential_status, 'pendente')

    def test_decline_account_removes_profile(self):
        self.register()
        user = User.objects.get(username='joao')
        self.client.force_login(self.staff)
        with mock.patch('core.views._send_async'):
            self.client.post(f'/utilizadores/{user.pk}/recusar/')
        self.assertFalse(Operative.objects.filter(name__startswith='João').exists())

    def test_badge_counts_pending(self):
        self.register()
        self.client.force_login(self.staff)
        r = self.client.get('/')
        self.assertEqual(r.context['pending_validations'], 2)  # account + credential

    def test_icnf_upload_replaces_list(self):
        self.client.force_login(self.staff)
        fake = SimpleUploadedFile('lista.pdf', b'%PDF-fake', content_type='application/pdf')
        with mock.patch('operatives.icnf.parse_list_pdf',
                        return_value=(date(2026, 9, 1), [{'number': '1-2020', 'name': 'A B', 'concelho': 'Faro', 'lifetime': True,
                                                          'valid_until': None}])):
            r = self.client.post('/utilizadores/lista-icnf/', {'lista': fake}, follow=True)
        self.assertContains(r, 'Lista importada: 1 técnicos')
        self.assertContains(r, '<td>Faro</td>')  # concelho in its own column
        self.assertEqual(list(IcnfTechnician.objects.values_list('number', flat=True)), ['1-2020'])

    def test_icnf_upload_updates_validated_validity(self):
        self.register()
        op = Operative.objects.get(user__username='joao')
        Operative.objects.filter(pk=op.pk).update(credential_status='validada', credential_valid_until=date(2030, 1, 1))
        self.client.force_login(self.staff)
        fake = SimpleUploadedFile('lista.pdf', b'%PDF-fake', content_type='application/pdf')
        with mock.patch('operatives.icnf.parse_list_pdf',
                        return_value=(None, [{'number': '547-2026', 'name': 'João Ricardo Valejo Castanheiro', 'concelho': 'Portimão',
                                              'lifetime': False, 'valid_until': date(2035, 1, 1)}])):
            self.client.post('/utilizadores/lista-icnf/', {'lista': fake})
        op.refresh_from_db()
        self.assertEqual(op.credential_valid_until, date(2035, 1, 1))


@override_settings(SECURE_SSL_REDIRECT=False)
class ProfileTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ana', email='ana@example.com', password='x')
        self.client.force_login(self.user)

    def save(self, **data):
        base = {'name': 'Ana Silva', 'phone': '', 'nif': '', 'credential_type': 'nenhuma', 'credential_number': ''}
        with mock.patch('operatives.views.send_async'):
            return self.client.post('/perfil/', {**base, **data})

    def test_profile_created_on_first_save(self):
        self.assertEqual(self.client.get('/perfil/').status_code, 200)
        self.save()
        op = Operative.objects.get(user=self.user)
        self.assertEqual((op.name, op.email), ('Ana Silva', 'ana@example.com'))

    def test_declaring_credential_goes_pending_and_switching_back_clears(self):
        self.save(credential_type='tecnico_fc', credential_number='12/2020')
        op = Operative.objects.get(user=self.user)
        self.assertEqual((op.credential_number, op.credential_status), ('12-2020', 'pendente'))
        Operative.objects.filter(pk=op.pk).update(credential_status='validada')
        self.save(credential_type='tecnico_fc', credential_number='12-2020')  # unchanged: stays validated
        op.refresh_from_db()
        self.assertEqual(op.credential_status, 'validada')
        self.save(credential_type='tecnico_fc', credential_number='13-2020')  # changed: back to pending
        op.refresh_from_db()
        self.assertEqual(op.credential_status, 'pendente')
        self.save(credential_type='operacional')
        op.refresh_from_db()
        self.assertEqual((op.credential_number, op.credential_status), ('', 'na'))

    def test_invalid_number_rejected(self):
        r = self.save(credential_type='tecnico_fc', credential_number='abc')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Operative.objects.filter(user=self.user).exists())
