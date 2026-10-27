import io
import shutil
import tempfile
import zipfile
from datetime import date

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from fire_actions.models import BurningPlan, FireAction, ParcelExecution
from operatives.models import Operative
from parcelas.models import FireParcel
from .document import generate_poq_impacto
from .models import Assessment, AssessmentPhoto, CriterionValue, ParcelCriterion, VisitWaiver
from .schedule import add_months, all_visits, expected_visits

MEDIA = tempfile.mkdtemp()
SQUARE = 'POLYGON((-8 37.1,-7.999 37.1,-7.999 37.101,-8 37.101,-8 37.1))'


def png():
    buf = io.BytesIO()
    Image.new('RGB', (30, 20), 'green').save(buf, 'PNG')
    return SimpleUploadedFile('m.png', buf.getvalue(), content_type='image/png')


def make_burn(parcel, d, name='A'):
    action = FireAction.objects.create(name=name, scheduled_date=d)
    action.parcels.set([parcel])
    plan = BurningPlan.objects.create(pre_plan=action, execution_date=d)
    return ParcelExecution.objects.create(plan=plan, parcel=parcel, date=d)


class ScheduleTests(TestCase):
    def setUp(self):
        self.parcel = FireParcel.objects.create(name='P', geometry=SQUARE, status='apta')

    def test_add_months_clamps_day(self):
        self.assertEqual(add_months(date(2026, 8, 31), 6), date(2027, 2, 28))
        self.assertEqual(add_months(date(2024, 2, 29), 12), date(2025, 2, 28))

    def test_visits_and_statuses(self):
        ex = make_burn(self.parcel, date(2024, 12, 2))
        Assessment.objects.create(execution=ex, phase='imediata', date=date(2024, 12, 10))
        visits = expected_visits(ex, today=date(2026, 10, 26))
        self.assertEqual([(v['phase'], v['year'], v['status']) for v in visits],
                         [('imediata', 0, 'feita'), ('6meses', 0, 'atrasada'), ('anual', 1, 'atrasada'),
                          ('anual', 2, 'futura')])
        self.assertEqual(visits[1]['due'], date(2025, 6, 2))
        today = date(2025, 6, 20)   # within the window of the 6 months visit
        self.assertEqual(expected_visits(ex, today=today)[1]['status'], 'em_curso')

    def test_new_burn_ends_cycle_and_same_plan_days_are_one_burn(self):
        ex = make_burn(self.parcel, date(2024, 1, 10))
        second_day = ParcelExecution.objects.create(plan=ex.plan, parcel=self.parcel, date=date(2024, 1, 11))
        make_burn(self.parcel, date(2024, 12, 1), name='B')
        visits = expected_visits(ex, today=date(2026, 10, 26))
        self.assertEqual([v['phase'] for v in visits], ['imediata', '6meses'])   # annual 1 (2025-01-10) is after
        self.assertEqual(expected_visits(second_day), [])
        # all_visits computes the same thing without per-execution queries
        by_ex = {}
        for v in all_visits(date(2026, 10, 26)):
            by_ex.setdefault(v['execution'].pk, []).append(v['phase'])
        self.assertEqual(by_ex[ex.pk], ['imediata', '6meses'])
        self.assertNotIn(second_day.pk, by_ex)


@override_settings(SECURE_SSL_REDIRECT=False, MEDIA_ROOT=MEDIA)
class AssessmentViewTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        cache.clear()
        self.tec = User.objects.create_user('tec', password='x')
        Operative.objects.create(user=self.tec, name='Técnico T', email='t@example.com', phone='',
                                 certification_level='', credential_type=Operative.CRED_TECNICO,
                                 credential_number='9-2020', credential_status=Operative.STATUS_VALIDADA,
                                 credential_lifetime=True)
        self.user = User.objects.create_user('u', password='x')
        self.parcel = FireParcel.objects.create(name='P', geometry=SQUARE, status='apta')
        self.ex = make_burn(self.parcel, date(2026, 10, 1))
        self.client.force_login(self.tec)

    def test_create_immediate_shows_only_phase_fields(self):
        r = self.client.get(f'/monitorizacao/nova/{self.ex.pk}/?fase=imediata')
        self.assertIn('litter_area', r.context['form'].fields)
        self.assertNotIn('gullying', r.context['form'].fields)
        crit = ParcelCriterion.objects.create(parcel=self.parcel, name='Sobreiros regenerados', unit='n.º/100 m²')
        r = self.client.post(f'/monitorizacao/nova/{self.ex.pk}/?fase=imediata', {
            'date': '2026-10-05', 'litter_area': '51-75', 'litter_red_f': '2 cm', 'soil_exposed_pct': '30',
            'shrub_resprout': 'true', 'tree_resin': 'false', f'crit_{crit.pk}': '12',
            'photo_caption': 'Vista geral', 'photos': [png()]})
        a = Assessment.objects.get()
        self.assertRedirects(r, f'/monitorizacao/{a.pk}/', fetch_redirect_response=False)
        self.assertEqual((a.phase, a.year, a.observer, a.shrub_resprout, a.tree_resin, a.gullying),
                         ('imediata', 0, self.tec, True, False, None))
        self.assertEqual(CriterionValue.objects.get().value, '12')
        self.assertEqual(AssessmentPhoto.objects.get().caption, 'Vista geral')
        detail = self.client.get(f'/monitorizacao/{a.pk}/')
        self.assertContains(detail, 'Sobreiros regenerados')
        self.assertContains(detail, '51–75 %')
        # The same visit again goes to the edit page
        r = self.client.get(f'/monitorizacao/nova/{self.ex.pk}/?fase=imediata')
        self.assertRedirects(r, f'/monitorizacao/{a.pk}/editar/', fetch_redirect_response=False)

    def test_validation(self):
        r = self.client.post(f'/monitorizacao/nova/{self.ex.pk}/?fase=6meses',
                             {'date': '2027-04-01', 'herb_resprout_pct': '150', 'soil_ph': '20'})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Assessment.objects.exists())

    def test_annual_year_and_permissions(self):
        self.client.post(f'/monitorizacao/nova/{self.ex.pk}/?fase=anual&ano=2', {'date': '2028-10-01'})
        self.assertEqual(Assessment.objects.get().year, 2)
        self.client.force_login(self.user)   # not a manager of the action
        self.client.post(f'/monitorizacao/nova/{self.ex.pk}/?fase=imediata', {'date': '2026-10-05'})
        self.assertEqual(Assessment.objects.count(), 1)
        a = Assessment.objects.get()
        self.client.post(f'/monitorizacao/{a.pk}/eliminar/')
        self.assertTrue(Assessment.objects.exists())   # only staff deletes

    def test_execution_with_assessments_cannot_be_deleted(self):
        Assessment.objects.create(execution=self.ex, phase='imediata', date=date(2026, 10, 2))
        self.client.post(f'/acoes/execucao/{self.ex.pk}/eliminar/')
        self.assertTrue(ParcelExecution.objects.filter(pk=self.ex.pk).exists())

    def test_criteria_management(self):
        r = self.client.post(f'/monitorizacao/parcela/{self.parcel.pk}/criterios/', {
            'form-TOTAL_FORMS': '1', 'form-INITIAL_FORMS': '0',
            'form-0-name': 'Estacas de erosão', 'form-0-unit': 'cm', 'form-0-active': 'on'})
        self.assertRedirects(r, f'/parcelas/{self.parcel.pk}/', fetch_redirect_response=False)
        c = ParcelCriterion.objects.get()
        a = Assessment.objects.create(execution=self.ex, phase='imediata', date=date(2026, 10, 2))
        CriterionValue.objects.create(assessment=a, criterion=c, value='3')
        self.client.post(f'/monitorizacao/parcela/{self.parcel.pk}/criterios/', {
            'form-TOTAL_FORMS': '1', 'form-INITIAL_FORMS': '1', 'form-0-id': c.pk,
            'form-0-name': c.name, 'form-0-active': 'on', 'form-0-DELETE': 'on'})
        c.refresh_from_db()
        self.assertFalse(c.active)   # used: deactivated, not deleted
        self.client.force_login(self.user)
        self.client.post(f'/monitorizacao/parcela/{self.parcel.pk}/criterios/', {
            'form-TOTAL_FORMS': '1', 'form-INITIAL_FORMS': '0', 'form-0-name': 'X'})
        self.assertEqual(ParcelCriterion.objects.count(), 1)

    def test_list_pages_and_badge(self):
        r = self.client.get('/monitorizacao/')
        self.assertEqual([v['phase'] for v in r.context['visits']][:1], ['imediata'])
        self.assertContains(self.client.get(f'/acoes/burning/{self.ex.plan_id}/'), 'POQ-Impacto')
        self.assertContains(self.client.get(f'/parcelas/{self.parcel.pk}/'), 'Impacto e monitorização')
        self.assertIn('monitoring_overdue', r.context)

    def test_poq_impacto_document(self):
        crit = ParcelCriterion.objects.create(parcel=self.parcel, name='Sobreiros')
        a1 = Assessment.objects.create(execution=self.ex, phase='imediata', date=date(2026, 10, 3),
                                       litter_area='>75', tree_scorch_pct=20, notes='Bom resultado')
        a2 = Assessment.objects.create(execution=self.ex, phase='6meses', date=date(2027, 4, 2), gullying=True,
                                       tree_mortality_pct=5, tree_mortality_dbh_cm=10, soil_ph=5.6)
        CriterionValue.objects.create(assessment=a2, criterion=crit, value='8')
        AssessmentPhoto.objects.create(assessment=a1, image=png(), caption='Depois')
        r = self.client.get(f'/monitorizacao/poq-impacto/{self.ex.plan_id}/')
        self.assertEqual(r.status_code, 200)
        xml = zipfile.ZipFile(io.BytesIO(r.content)).read('word/document.xml').decode()
        for text in ['POQ - Impacto', 'Parcela: P', 'MANTA MORTA', '1.ª FASE', '2.ª FASE', '&gt; 75 %',
                     '5 % - DAP ≤ 10 cm', 'Bom resultado', 'Sobreiros', 'Ano de 2026', 'Foto 1']:
            self.assertIn(text, xml)

    def test_poq_impacto_without_assessments(self):
        self.assertEqual(generate_poq_impacto(self.ex.plan)[:2], b'PK')

    def test_waive_visit(self):
        url = f'/monitorizacao/dispensar/{self.ex.pk}/?fase=6meses'
        r = self.client.post(url, {'reason': '  '})
        self.assertEqual(r.status_code, 200)   # reason is required
        self.assertFalse(VisitWaiver.objects.exists())
        r = self.client.post(url, {'reason': 'Queima anterior à plataforma', 'next': '/acoes/'})
        self.assertRedirects(r, '/acoes/', fetch_redirect_response=False)
        w = VisitWaiver.objects.get()
        self.assertEqual((w.phase, w.year, w.waived_by), ('6meses', 0, self.tec))
        visits = {v['phase']: v for v in expected_visits(self.ex, today=date(2027, 12, 1))}
        self.assertEqual((visits['6meses']['status'], visits['6meses']['waiver']), ('dispensada', w))
        self.assertIn('Queima anterior à plataforma',
                      zipfile.ZipFile(io.BytesIO(generate_poq_impacto(self.ex.plan))).read('word/document.xml')
                      .decode())
        # Unsafe redirect targets are ignored
        r = self.client.post(url, {'reason': 'Outro motivo', 'next': 'https://evil.example/'})
        self.assertRedirects(r, '/monitorizacao/', fetch_redirect_response=False)
        self.assertEqual(VisitWaiver.objects.get().reason, 'Outro motivo')
        # Undo
        self.client.post(url, {'undo': '1'})
        self.assertFalse(VisitWaiver.objects.exists())

    def test_recording_the_visit_removes_the_waiver_and_done_visits_cannot_be_waived(self):
        VisitWaiver.objects.create(execution=self.ex, phase='imediata', reason='x')
        self.client.post(f'/monitorizacao/nova/{self.ex.pk}/?fase=imediata', {'date': '2026-10-05'})
        self.assertFalse(VisitWaiver.objects.exists())
        self.client.post(f'/monitorizacao/dispensar/{self.ex.pk}/?fase=imediata', {'reason': 'y'})
        self.assertFalse(VisitWaiver.objects.exists())

    def test_only_managers_waive(self):
        self.client.force_login(self.user)
        self.client.post(f'/monitorizacao/dispensar/{self.ex.pk}/?fase=imediata', {'reason': 'y'})
        self.assertFalse(VisitWaiver.objects.exists())
