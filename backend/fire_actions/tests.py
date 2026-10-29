import io
import shutil
import tempfile
import zipfile
from datetime import date, time
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from operatives.models import Operative
from parcelas.models import FireParcel
from .models import (BurningPlan, BurningPlanPhoto, CostLine, ExecutionMember, FireAction, ParcelExecution,
                     WeatherReading)
from .poq import generate_poq_execucao

MEDIA = tempfile.mkdtemp()
SQUARE = 'POLYGON((-8 37.1,-7.999 37.1,-7.999 37.101,-8 37.101,-8 37.1))'


def image_bytes(fmt='PNG', size=(40, 30)):
    buf = io.BytesIO()
    Image.new('RGB', size, 'orange').save(buf, fmt)
    return buf.getvalue()


def formset_data(fs):
    """POST data reproducing a rendered formset (management form + current values)."""
    data = {f'{fs.prefix}-{k}': v for k, v in fs.management_form.initial.items()}
    for form in fs.forms:
        for name in form.fields:
            value = form[name].value()
            if value is None or value is False:
                continue
            data[form.add_prefix(name)] = value
    return data


def docx_text(content):
    return zipfile.ZipFile(io.BytesIO(content)).read('word/document.xml').decode()


@override_settings(SECURE_SSL_REDIRECT=False, MEDIA_ROOT=MEDIA)
class FireActionTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.user = User.objects.create_user('u', password='x')
        Operative.objects.create(user=self.user, name='Técnico U', email='u@example.com', phone='', certification_level='',
                                 credential_type=Operative.CRED_TECNICO, credential_number='5-2020',
                                 credential_status=Operative.STATUS_VALIDADA, credential_lifetime=True)
        self.staff = User.objects.create_user('s', password='x', is_staff=True)
        self.client.force_login(self.user)
        self.parcel = FireParcel.objects.create(name='P', geometry=SQUARE, status='apta', area_ha=1.2,
                                                vegetation_type='matos')
        self.op = Operative.objects.create(name='Op', email='o@example.com', phone='1', certification_level='A')
        self.pp = FireAction.objects.create(name='PP', scheduled_date='2026-11-05', created_by=self.user)
        self.pp.parcels.set([self.parcel])

    def create_bp(self, **overrides):
        return self.client.post(f'/acoes/burning/novo/{self.pp.pk}/',
                                {'pre_plan': self.pp.pk, 'execution_date': '2026-11-06', **overrides})

    def edit_data(self, ex, **overrides):
        r = self.client.get(f'/acoes/execucao/{ex.pk}/')
        data = {}
        for name in ('members', 'readings', 'strips', 'costs'):
            data.update(formset_data(r.context[name]))
        form = r.context['form']
        for name in form.fields:
            value = form[name].value()
            if value not in (None, False, ''):
                data[name] = value
        data.update(overrides)
        return data

    # Pre-plans

    def test_preplan_create_and_invalid_date(self):
        self.client.post('/acoes/novo/', {'name': 'Novo', 'scheduled_date': '2026-12-01',
                                            'parcels': [self.parcel.pk]})
        self.assertEqual(list(FireAction.objects.get(name='Novo').parcels.all()), [self.parcel])
        r = self.client.post('/acoes/novo/', {'name': 'Mau', 'scheduled_date': '31/31/2026'})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(FireAction.objects.filter(name='Mau').exists())

    def test_preplan_edit_form_shows_iso_date(self):
        r = self.client.get(f'/acoes/{self.pp.pk}/editar/')
        self.assertContains(r, 'value="2026-11-05"')

    def test_preplan_with_plan_cannot_be_deleted(self):
        self.create_bp()
        self.client.force_login(self.staff)
        self.client.post(f'/acoes/{self.pp.pk}/eliminar/')
        self.assertTrue(FireAction.objects.filter(pk=self.pp.pk).exists())

    # Execution (POQ)

    def test_create_execution_creates_parcel_rows(self):
        r = self.create_bp()
        bp = BurningPlan.objects.get()
        self.assertRedirects(r, f'/acoes/burning/{bp.pk}/', fetch_redirect_response=False)
        ex = bp.executions.get()
        self.assertEqual((ex.parcel, str(ex.date), ex.formation, ex.area_treated_ha),
                         (self.parcel, '2026-11-06', 'mato', 1.2))
        self.assertEqual(sorted(ex.strips.values_list('side', flat=True)), ['baixo', 'cima', 'lado1', 'lado2'])
        self.pp.refresh_from_db()
        self.assertEqual((self.pp.status, str(self.pp.execution_date)), ('realizada', '2026-11-06'))
        self.assertContains(self.client.get(f'/acoes/burning/{bp.pk}/'), 'Preencher')

    def test_second_plan_for_same_preplan_rejected(self):
        self.create_bp()
        r = self.client.post('/acoes/burning/novo/', {'pre_plan': self.pp.pk, 'execution_date': '2026-11-06'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(BurningPlan.objects.count(), 1)

    def test_incident_requires_circumstances(self):
        r = self.create_bp(incident='on')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(BurningPlan.objects.exists())

    def test_fill_execution(self):
        self.create_bp()
        ex = ParcelExecution.objects.get()
        data = self.edit_data(ex, start_time='10:00', end_time='13:30', n_vfci='1', problems=['ignicao', 'fumo'],
                              rating_objectives='4', fuel_method='B', fuel_superficial='C',
                              **{'members-0-operative': self.op.pk, 'members-0-function': 'ignicao',
                                 'readings-0-time': '10:15', 'readings-0-temp': '14', 'readings-0-rh': '55',
                                 'readings-0-weather': '1', 'readings-0-wind_dir': 'NW', 'readings-0-conduct': '1',
                                 'strips-0-means': '7', 'strips-0-width_m': '4',
                                 'costs-0-category': 'pessoal', 'costs-0-description': 'Sapadores',
                                 'costs-0-qty_burn': '8', 'costs-0-qty_extinction': '2',
                                 'costs-0-unit_price': '10.50',
                                 'photo_moment': 'antes', 'photo_caption': 'Antes da queima',
                                 'photos': [SimpleUploadedFile('f.png', image_bytes(), content_type='image/png')]})
        r = self.client.post(f'/acoes/execucao/{ex.pk}/', data)
        self.assertRedirects(r, f'/acoes/burning/{ex.plan_id}/', fetch_redirect_response=False)
        ex.refresh_from_db()
        self.assertEqual((ex.problems_list, ex.duration_hours, ex.n_vfci), (['ignicao', 'fumo'], 3.5, 1))
        self.assertEqual(ExecutionMember.objects.get().function, 'ignicao')
        self.assertEqual(WeatherReading.objects.get().wind_dir, 'NW')
        self.assertEqual(ex.strips.get(side='cima').width_m, 4)
        self.assertEqual(ex.cost_total, Decimal('105.00'))
        photo = BurningPlanPhoto.objects.get()
        self.assertEqual((photo.parcel, photo.moment, photo.taken_on), (self.parcel, 'antes', date(2026, 11, 6)))

    def test_problem_notes_difficulty_and_word(self):
        self.create_bp()
        ex = ParcelExecution.objects.get()
        page = self.client.get(f'/acoes/execucao/{ex.pk}/')
        for prefix in ('members', 'readings', 'costs'):
            self.assertContains(page, f'id="{prefix}-empty"')
        self.assertNotContains(page, 'Propagação')
        self.assertContains(page, 'Operacionais')
        data = self.edit_data(ex, problems=['fumo'], pnote_fumo='Inversão térmica', pnote_ignicao='ignorado',
                              **{f: '3' for f, _, _ in ParcelExecution.DIFFICULTY_ELEMENTS})
        self.client.post(f'/acoes/execucao/{ex.pk}/', data)
        ex.refresh_from_db()
        self.assertEqual(ex.problem_notes, {'fumo': 'Inversão térmica'})
        self.assertEqual((ex.difficulty_total, ex.difficulty_class), (45, 'Normal'))
        self.assertContains(self.client.get(f'/acoes/execucao/{ex.pk}/'), 'value="Inversão térmica"')
        text = docx_text(generate_poq_execucao(ex.plan))
        self.assertIn('Deficiente dispersão do fumo: Inversão térmica', text)
        self.assertIn('45 — Normal', text)
        self.assertNotIn('Propagação', text)

    def test_invalid_execution_saves_nothing(self):
        self.create_bp()
        ex = ParcelExecution.objects.get()
        for overrides in [{'start_time': '12:00', 'end_time': '11:00'}, {'eff_crowns_pct': '140'},
                          {'readings-0-temp': '20'},   # reading without time
                          {'photos': [SimpleUploadedFile('x.png', b'not an image', content_type='image/png')]}]:
            r = self.client.post(f'/acoes/execucao/{ex.pk}/', self.edit_data(ex, **overrides))
            self.assertEqual(r.status_code, 200, overrides)
        ex.refresh_from_db()
        self.assertIsNone(ex.start_time)
        self.assertFalse(WeatherReading.objects.exists() or BurningPlanPhoto.objects.exists())

    def test_add_execution_other_day_and_duplicate(self):
        self.create_bp()
        bp = BurningPlan.objects.get()
        r = self.client.post(f'/acoes/burning/{bp.pk}/parcela/', {'parcel': self.parcel.pk, 'date': '2026-11-04'})
        ex = bp.executions.get(date='2026-11-04')
        self.assertRedirects(r, f'/acoes/execucao/{ex.pk}/', fetch_redirect_response=False)
        self.client.post(f'/acoes/burning/{bp.pk}/parcela/', {'parcel': self.parcel.pk, 'date': '2026-11-04'})
        self.assertEqual(bp.executions.count(), 2)
        self.pp.refresh_from_db()
        self.assertEqual(str(self.pp.execution_date), '2026-11-04')   # first day of execution

        self.client.post(f'/acoes/execucao/{ex.pk}/eliminar/')
        self.pp.refresh_from_db()
        self.assertEqual(str(self.pp.execution_date), '2026-11-06')

    def test_only_managers_edit_executions(self):
        self.create_bp()
        ex = ParcelExecution.objects.get()
        self.client.force_login(User.objects.create_user('outro', password='x'))   # not a técnico
        r = self.client.get(f'/acoes/execucao/{ex.pk}/')
        self.assertContains(r, 'Área reservada a técnicos credenciados')
        self.assertContains(self.client.get('/acoes/burning/'), 'Área reservada a técnicos credenciados')
        self.assertContains(self.client.get('/monitorizacao/'), 'Área reservada a técnicos credenciados')
        self.client.post(f'/acoes/execucao/{ex.pk}/eliminar/')
        self.assertTrue(ParcelExecution.objects.exists())

    def test_delete_permissions_and_cleanup(self):
        self.create_bp()
        bp = BurningPlan.objects.get()
        photo = BurningPlanPhoto.objects.create(image=SimpleUploadedFile('f.png', image_bytes()), parcel=self.parcel)
        bp.photos.add(photo)
        self.client.post(f'/acoes/burning/{bp.pk}/eliminar/')
        self.assertTrue(BurningPlan.objects.exists())  # non-staff blocked

        self.client.force_login(self.staff)
        self.client.post(f'/acoes/burning/{bp.pk}/eliminar/')
        self.assertFalse(BurningPlan.objects.exists() or ParcelExecution.objects.exists())
        self.assertFalse(BurningPlanPhoto.objects.exists())
        self.pp.refresh_from_db()
        self.assertEqual((self.pp.status, self.pp.execution_date), ('prevista', None))

    def test_history_tracks_m2m_and_shows_on_pages(self):
        other = FireParcel.objects.create(
            name='P2', geometry='POLYGON((-8 37.2,-7.999 37.2,-7.999 37.201,-8 37.201,-8 37.2))', status='apta')
        self.client.post(f'/acoes/{self.pp.pk}/editar/', {'name': 'PP', 'scheduled_date': '2026-11-05',
                                                            'parcels': [self.parcel.pk, other.pk]})
        last = self.pp.history.order_by('-history_date').first()
        self.assertEqual(last.history_user, self.user)
        self.assertIn('parcels', [c.field for c in last.diff_against(last.prev_record).changes])
        self.assertContains(self.client.get(f'/acoes/{self.pp.pk}/'), 'Histórico de alterações')

        self.create_bp()
        bp = BurningPlan.objects.get()
        self.assertEqual(bp.executions.count(), 2)
        self.assertEqual(bp.history.first().history_user, self.user)
        self.assertContains(self.client.get(f'/acoes/burning/{bp.pk}/'), 'Histórico de alterações')

    # POQ-Execução (Word)

    def test_poq_includes_tables_photos_and_field_sheet(self):
        self.create_bp()
        bp = BurningPlan.objects.get()
        ex = bp.executions.get()
        ExecutionMember.objects.create(execution=ex, operative=self.op, function='ignicao')
        WeatherReading.objects.create(execution=ex, time=time(10, 0), temp=15, rh=60, weather=1, wind_dir='N')
        CostLine.objects.create(execution=ex, description='Sapadores', qty_burn=4, unit_price=Decimal('12'))
        photo = BurningPlanPhoto(caption='Frente de chamas', parcel=self.parcel, moment='durante')
        photo.image.save('big.jpg', ContentFile(image_bytes('JPEG', (2400, 1800))), save=True)
        missing = BurningPlanPhoto.objects.create(image='bp_photos/nao_existe.jpg')
        bp.photos.add(photo, missing)

        r = self.client.get(f'/acoes/burning/{bp.pk}/relatorio/')
        self.assertEqual(r.status_code, 200)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        jpgs = [n for n in z.namelist() if n.endswith('.jpg')]
        self.assertEqual(len(jpgs), 1)
        self.assertLessEqual(max(Image.open(io.BytesIO(z.read(jpgs[0]))).size), 1600)
        xml = z.read('word/document.xml').decode()
        for text in ['POQ - Execução', 'Parcela: P', 'Técnicos envolvidos na queima', 'Meteorologia',
                     'Frente de chamas', 'Sapadores', 'Avaliação económica', 'MATOS']:
            self.assertIn(text, xml)
        self.assertNotIn('Plano de Fogo Controlado n.º', xml)

    def test_poq_without_geometry_or_data(self):
        self.pp.parcels.clear()
        self.create_bp()
        self.assertEqual(generate_poq_execucao(BurningPlan.objects.get())[:2], b'PK')

    def test_poq_incident_section(self):
        self.create_bp(incident='on', incident_circumstances='Projeção de faúlhas', incident_area_ha='0.3')
        xml = docx_text(generate_poq_execucao(BurningPlan.objects.get()))
        self.assertIn('Projeção de faúlhas', xml)
        self.assertIn('Fuga do fogo', xml)
