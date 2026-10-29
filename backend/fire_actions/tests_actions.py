"""Burning actions: announcement, legal framework, outlook, participation, communications."""
from datetime import date, timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import UserPreferences
from operatives.models import Operative
from parcelas.models import FireParcel, Freguesia
from . import outlook
from .models import BurningPlan, FireAction, Participation
from .notify import send_reminders

SQUARE = 'POLYGON((-8.46 37.37,-8.459 37.37,-8.459 37.371,-8.46 37.371,-8.46 37.37))'


def make_tecnico(username='tec'):
    user = User.objects.create_user(username, email=f'{username}@example.com', password='x')
    Operative.objects.create(user=user, name='Técnico T', email=user.email, phone='', certification_level='',
                             credential_type=Operative.CRED_TECNICO, credential_number='9-2020',
                             credential_status=Operative.STATUS_VALIDADA, credential_lifetime=True)
    return user


def in_days(n):
    return timezone.localdate() + timedelta(days=n)


QUIET = mock.patch('fire_actions.views.notify_action_update')
NO_OUTLOOK = {'blocked': False, 'probability': None, 'probability_label': 'Sem previsão', 'reasons': [],
              'fuel': None, 'danger': None, 'suggested': None, 'suggested_label': 'Sem previsão', 'manual': False}


@override_settings(SECURE_SSL_REDIRECT=False)
class AnnouncementTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ana', email='ana@example.com', password='x')
        self.client.force_login(self.user)
        self.parcel = FireParcel.objects.create(name='Parcela', geometry=SQUARE, status='apta', concelho='Monchique')

    def post(self, **data):
        base = {'name': 'Queimada X', 'action_type': 'queimada', 'scheduled_date': in_days(5).isoformat(),
                'parcels': [self.parcel.pk]}
        with mock.patch('fire_actions.notify.send_async_each') as send:
            r = self.client.post('/acoes/novo/', {**base, **data})
        return r, send

    def test_create_announces_to_users_who_want_it(self):
        other = User.objects.create_user('rui', email='rui@example.com', password='x')
        quiet = User.objects.create_user('ze', email='ze@example.com', password='x')
        UserPreferences.objects.create(user=quiet, email_new_actions=False)
        r, send = self.post(meeting_lat='37.37', meeting_lng='-8.46', meeting_notes='Igreja')
        a = FireAction.objects.get()
        self.assertRedirects(r, f'/acoes/{a.pk}/', fetch_redirect_response=False)
        self.assertEqual((a.status, a.created_by, a.action_type), ('prevista', self.user, 'queimada'))
        self.assertAlmostEqual(a.meeting_point.y, 37.37)
        self.assertEqual(send.call_args.args[2], ['rui@example.com'])   # not the creator, not opted out

    def test_type_defaults_to_queimada(self):
        self.post(action_type='')
        self.assertEqual(FireAction.objects.get().action_type, 'queimada')

    def test_responsible_only_tecnicos_and_formacao_objective(self):
        tec = make_tecnico()
        choices = [c[0].value for c in self.client.get('/acoes/novo/').context['form'].fields['responsible_user'].choices
                   if c[0]]
        self.assertEqual(choices, [tec.pk])
        self.post(objectives=['formacao', 'prevencao'])
        a = FireAction.objects.get()
        self.assertTrue(a.training)
        self.assertIn('Formação', a.objectives_display)

    def test_ics_and_map_link(self):
        from datetime import time
        a = FireAction.objects.create(name='A', scheduled_date=in_days(3), start_time=time(9),
                                      meeting_notes='Igreja', created_by=self.user)
        from django.contrib.gis.geos import Point
        a.meeting_point = Point(-8.461234, 37.371234, srid=4326)
        a.save()
        r = self.client.get(f'/acoes/{a.pk}/calendario.ics')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'DTSTART:', r.content)
        self.assertContains(self.client.get(f'/acoes/{a.pk}/'), 'maps?q=37.371234,-8.461234')

    def test_fogo_controlado_requires_a_technician(self):
        r, _ = self.post(action_type='fogo_controlado', responsible_user=self.user.pk)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(FireAction.objects.exists())
        tec = make_tecnico()
        self.post(action_type='fogo_controlado', responsible_user=tec.pk, pfc_reference='3/9-2020/2025')
        self.assertTrue(FireAction.objects.filter(action_type='fogo_controlado').exists())

    def test_alternative_date_must_differ(self):
        r, _ = self.post(alt_date_1=in_days(5).isoformat())
        self.assertEqual(r.status_code, 200)
        self.assertFalse(FireAction.objects.exists())

    def test_only_apta_parcels(self):
        prop = FireParcel.objects.create(name='Proposta', geometry=SQUARE)
        r, _ = self.post(parcels=[prop.pk])
        self.assertFalse(FireAction.objects.exists())

    def test_announcements_page_lists_open_future_actions(self):
        FireAction.objects.create(name='Futura', scheduled_date=in_days(3))
        FireAction.objects.create(name='Cancelada', scheduled_date=in_days(3), status='cancelada')
        FireAction.objects.create(name='Passada', scheduled_date=in_days(-3))
        r = self.client.get('/acoes/proximas/')
        self.assertContains(r, 'Futura')
        self.assertNotContains(r, 'Cancelada')
        self.assertNotContains(r, 'Passada')
        self.assertContains(r, 'Quero participar')

    def test_old_urls_redirect(self):
        a = FireAction.objects.create(name='A', scheduled_date=in_days(3))
        r = self.client.get(f'/preplan/{a.pk}/')
        self.assertRedirects(r, f'/acoes/{a.pk}/', status_code=301, fetch_redirect_response=False)


class LegalFrameworkTests(TestCase):
    def test_queimada(self):
        a = FireAction(name='Q', scheduled_date=date.today())
        self.assertIn('comunicação prévia ou autorização do município', a.legal_missing)
        a.legal_mode = 'comunicacao_previa'
        self.assertIn('referência/data da comunicação ou autorização', a.legal_missing)
        a.legal_reference = 'CP-12/2026'
        self.assertEqual(a.legal_missing, [])
        a.legal_mode = 'autorizacao'
        self.assertIn('acompanhamento (técnico credenciado, bombeiros, sapadores…)', a.legal_missing)
        a.accompaniment = 'Bombeiros de Monchique'
        self.assertEqual(a.legal_missing, [])

    def test_fogo_controlado(self):
        a = FireAction(name='F', scheduled_date=date.today(), action_type='fogo_controlado')
        self.assertEqual(a.legal_missing, ['n.º do PFC aprovado'])
        a.pfc_reference = '1/9-2020/2026'
        self.assertEqual(a.legal_missing, [])


@override_settings(SECURE_SSL_REDIRECT=False)
class StatusAndParticipationTests(TestCase):
    def setUp(self):
        self.tec = make_tecnico()
        self.user = User.objects.create_user('ana', email='ana@example.com', password='x')
        self.action = FireAction.objects.create(name='Q', scheduled_date=in_days(2), created_by=self.tec,
                                                responsible_user=self.tec, slots=1)

    def set_status(self, user, **data):
        self.client.force_login(user)
        with QUIET as notify, mock.patch('fire_actions.views.action_outlook', return_value=dict(NO_OUTLOOK)):
            self.client.post(f'/acoes/{self.action.pk}/estado/', data)
        self.action.refresh_from_db()
        return notify

    def test_confirm_requires_legal_framework(self):
        self.set_status(self.tec, status='confirmada')
        self.assertEqual(self.action.status, 'prevista')
        FireAction.objects.filter(pk=self.action.pk).update(legal_mode='comunicacao_previa', legal_reference='CP-1')
        notify = self.set_status(self.tec, status='confirmada')
        self.assertEqual(self.action.status, 'confirmada')
        self.assertEqual(notify.call_args.args[2], 'Ação confirmada')

    def test_confirm_blocked_by_fire_danger(self):
        FireAction.objects.filter(pk=self.action.pk).update(legal_mode='comunicacao_previa', legal_reference='CP-1')
        self.client.force_login(self.tec)
        with QUIET, mock.patch('fire_actions.views.action_outlook', return_value={**NO_OUTLOOK, 'blocked': True}):
            r = self.client.post(f'/acoes/{self.action.pk}/estado/', {'status': 'confirmada'}, follow=True)
        self.action.refresh_from_db()
        self.assertEqual(self.action.status, 'prevista')
        self.assertContains(r, 'muito elevado')

    def test_postpone_and_cancel(self):
        new = in_days(9)
        self.set_status(self.tec, status='adiada', new_date=new.isoformat(), reason='Chuva')
        self.assertEqual((self.action.status, self.action.scheduled_date, self.action.status_reason),
                         ('prevista', new, 'Chuva'))
        self.set_status(self.tec, status='cancelada')            # reason required
        self.assertEqual(self.action.status, 'prevista')
        self.set_status(self.tec, status='cancelada', reason='Sem autorização')
        self.assertEqual(self.action.status, 'cancelada')

    def test_non_manager_cannot_change_status(self):
        self.set_status(self.user, status='cancelada', reason='x')
        self.assertEqual(self.action.status, 'prevista')

    def test_participation_flow_and_slots(self):
        self.client.force_login(self.user)
        self.client.post(f'/acoes/{self.action.pk}/participar/', {'intent': 'vou', 'role': 'vigia'})
        part = Participation.objects.get(user=self.user)
        self.assertEqual((part.intent, part.role, part.confirmed), ('vou', 'vigia', None))
        # participant cannot confirm themselves
        self.client.post(f'/acoes/{self.action.pk}/participantes/{part.pk}/', {'decision': 'confirmar'})
        part.refresh_from_db()
        self.assertIsNone(part.confirmed)
        # slots are indicative: a sign-up beyond them is accepted with a warning, and the manager may confirm it
        other = User.objects.create_user('rui', password='x')
        self.client.force_login(other)
        r = self.client.post(f'/acoes/{self.action.pk}/participar/', {'intent': 'vou'}, follow=True)
        self.assertContains(r, 'já ultrapassou as 1 vagas previstas')
        p2 = Participation.objects.get(user=other)
        self.client.force_login(self.tec)
        with mock.patch('core.emails.send_async'):
            self.client.post(f'/acoes/{self.action.pk}/participantes/{part.pk}/', {'decision': 'confirmar'})
            self.client.post(f'/acoes/{self.action.pk}/participantes/{p2.pk}/', {'decision': 'confirmar'})
        part.refresh_from_db(); p2.refresh_from_db()
        self.assertEqual((part.confirmed, p2.confirmed), (True, True))

    def test_participation_closed_when_cancelled(self):
        FireAction.objects.filter(pk=self.action.pk).update(status='cancelada')
        self.client.force_login(self.user)
        self.client.post(f'/acoes/{self.action.pk}/participar/', {'intent': 'vou'})
        self.assertFalse(Participation.objects.exists())

    def test_participate_next_redirect_is_safe(self):
        self.client.force_login(self.user)
        r = self.client.post(f'/acoes/{self.action.pk}/participar/', {'intent': 'vou', 'next': 'https://evil.example/'})
        self.assertRedirects(r, f'/acoes/{self.action.pk}/', fetch_redirect_response=False)

    def test_communications(self):
        FireAction.objects.filter(pk=self.action.pk).update(scheduled_date=timezone.localdate())
        self.client.force_login(self.tec)
        self.client.post(f'/acoes/{self.action.pk}/comunicacao/', {'which': 'fim'})   # start first
        self.action.refresh_from_db()
        self.assertIsNone(self.action.comm_end_at)
        self.client.post(f'/acoes/{self.action.pk}/comunicacao/', {'which': 'inicio'})
        self.client.post(f'/acoes/{self.action.pk}/comunicacao/', {'which': 'fim'})
        self.action.refresh_from_db()
        self.assertEqual((self.action.comm_start_by, self.action.comm_end_by), (self.tec, self.tec))

    def test_detail_and_ics(self):
        self.client.force_login(self.user)
        r = self.client.get(f'/acoes/{self.action.pk}/')
        self.assertContains(r, 'Inscrever-me')
        self.assertContains(r, 'Em falta')
        ics = self.client.get(f'/acoes/{self.action.pk}/calendario.ics')
        self.assertEqual(ics['Content-Type'], 'text/calendar; charset=utf-8')
        body = ics.content.decode()
        self.assertIn('BEGIN:VEVENT', body)
        self.assertIn(f'DTSTART;VALUE=DATE:{self.action.scheduled_date:%Y%m%d}', body)
        self.assertIn('SUMMARY:Queimada: Q', body)

    def test_execution_prefills_confirmed_participants(self):
        op_user = User.objects.create_user('op', password='x')
        op = Operative.objects.create(user=op_user, name='Op', email='', phone='', certification_level='')
        Participation.objects.create(action=self.action, user=op_user, confirmed=True, role='ignicao')
        self.action.parcels.set([FireParcel.objects.create(name='P', geometry=SQUARE, status='apta')])
        self.client.force_login(self.tec)
        self.client.post(f'/acoes/burning/novo/{self.action.pk}/', {'execution_date': self.action.scheduled_date})
        ex = BurningPlan.objects.get().executions.get()
        self.assertEqual(sorted((m.operative.name, m.function) for m in ex.members.all()),
                         [('Op', 'ignicao'), ('Técnico T', 'coordenacao')])
        self.assertEqual(ex.n_men, 2)

    def test_reminders(self):
        FireAction.objects.filter(pk=self.action.pk).update(scheduled_date=in_days(1))
        going = User.objects.create_user('vai', email='vai@example.com', password='x')
        maybe = User.objects.create_user('talvez', email='talvez@example.com', password='x')
        refused = User.objects.create_user('nao', email='nao@example.com', password='x')
        muted = User.objects.create_user('mudo', email='mudo@example.com', password='x')
        UserPreferences.objects.create(user=muted, email_reminders=False)
        Participation.objects.create(action=self.action, user=going, intent='vou')
        Participation.objects.create(action=self.action, user=maybe, intent='talvez')
        Participation.objects.create(action=self.action, user=refused, intent='vou', confirmed=False)
        Participation.objects.create(action=self.action, user=muted, intent='vou')
        with mock.patch('fire_actions.notify.send_async_each') as send:
            n = send_reminders(in_days(1), 'https://exemplo.pt')
        self.assertEqual(n, 1)
        self.assertEqual(send.call_args.args[2], ['vai@example.com'])
        self.assertIn('https://exemplo.pt/acoes/', send.call_args.args[1])


class OutlookTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_simard_and_classes(self):
        self.assertAlmostEqual(outlook.simard_emc(20, 40), 2.22749 + 0.160107 * 40 - 0.014784 * 68, places=4)
        self.assertEqual(outlook.classify(17)[1], 'GO')
        self.assertEqual(outlook.classify(12)[1], 'CUIDADO')
        self.assertEqual(outlook.classify(30)[1], 'NAO-GO')
        self.assertEqual(outlook.correction(11, 0, 40, 9), 5)     # NOV_JAN, N, >30%, 8-10h

    def fake_forecast(self, d, rh=70, rain_yesterday=0.0):
        days = [(d - timedelta(days=i)).isoformat() for i in range(10, -1, -1)]
        hours = [f'{day}T{h:02d}:00' for day in days for h in range(24)]
        return {'hourly': {'time': hours, 'temperature_2m': [15] * len(hours),
                           'relative_humidity_2m': [rh] * len(hours), 'windspeed_10m': [8] * len(hours),
                           'precipitation': [0] * len(hours)},
                'daily': {'time': days, 'precipitation_sum': [0] * 9 + [rain_yesterday, 0]}}

    def test_fuel_forecast_and_rain_rule(self):
        d = in_days(1)
        with mock.patch('fire_actions.outlook._get_json', return_value=self.fake_forecast(d)):
            f = outlook.fuel_forecast(37.37, -8.46, d)
        self.assertEqual(f['dry_days'], 10)
        cache.clear()
        with mock.patch('fire_actions.outlook._get_json', return_value=self.fake_forecast(d, rain_yesterday=5)):
            f = outlook.fuel_forecast(37.37, -8.46, d)
        self.assertEqual((f['dry_days'], f['go']), (0, 'NAO-GO'))
        self.assertIsNone(outlook.fuel_forecast(37.37, -8.46, in_days(30)))   # beyond horizon

    def test_fire_danger_from_ipma(self):
        g = GEOSGeometry('POLYGON((-8.5 37.3,-8.4 37.3,-8.4 37.4,-8.5 37.4,-8.5 37.3))', srid=4326).transform(3763, clone=True)
        Freguesia.objects.create(dicofre='081101', freguesia='Alferce', concelho='Monchique', distrito='Faro',
                                 geom=MultiPolygon(g, srid=3763))
        d = in_days(1)
        ipma = {'dataPrev': d.isoformat(), 'local': {'0811': {'data': {'rcm': 4}}}}
        with mock.patch('fire_actions.outlook._get_json', return_value=ipma):
            danger = outlook.fire_danger(['Monchique'], d)
        self.assertEqual((danger['level'], danger['label'], danger['blocking']), (4, 'Muito elevado', True))
        self.assertIsNone(outlook.fire_danger(['Monchique'], in_days(5)))   # only 3 days published

    def test_action_outlook_combines_sources(self):
        p = FireParcel.objects.create(name='P', geometry=SQUARE, status='apta', concelho='Monchique')
        a = FireAction.objects.create(name='Q', scheduled_date=in_days(1))
        a.parcels.add(p)
        fuel = {'fm_mean': 17.0, 'fm_min': 15.0, 'label': 'Ótimo', 'go': 'GO', 'note': '', 'dry_days': 6,
                'rain': 0, 't_max': 18, 'rh_min': 45, 'wind_max': 10}
        with mock.patch('fire_actions.outlook.fuel_forecast', return_value=fuel), \
             mock.patch('fire_actions.outlook.fire_danger', return_value=None):
            o = outlook.action_outlook(a)
        self.assertEqual(o['suggested'], 'media')   # GO, but legal framework missing caps it
        a.legal_mode, a.legal_reference = 'comunicacao_previa', 'CP-1'
        with mock.patch('fire_actions.outlook.fuel_forecast', return_value=fuel), \
             mock.patch('fire_actions.outlook.fire_danger',
                        return_value={'level': 5, 'label': 'Máximo', 'per_concelho': {}, 'blocking': True}):
            o = outlook.action_outlook(a)
        self.assertEqual((o['suggested'], o['blocked']), ('baixa', True))
        a.probability_manual = 'alta'
        with mock.patch('fire_actions.outlook.fuel_forecast', return_value=None), \
             mock.patch('fire_actions.outlook.fire_danger', return_value=None):
            o = outlook.action_outlook(a)
        self.assertEqual((o['probability'], o['manual']), ('alta', True))


@override_settings(SECURE_SSL_REDIRECT=False)
class PreferencesTests(TestCase):
    def test_profile_saves_email_preferences(self):
        user = User.objects.create_user('ana', email='ana@example.com', password='x')
        self.client.force_login(user)
        with mock.patch('operatives.views.send_async'):
            self.client.post('/perfil/', {'name': 'Ana', 'credential_type': 'nenhuma', 'email_reminders': 'on'})
        prefs = UserPreferences.objects.get(user=user)
        self.assertEqual((prefs.email_new_actions, prefs.email_action_updates, prefs.email_reminders),
                         (False, False, True))
