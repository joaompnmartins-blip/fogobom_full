import io
import json
import shutil
import tempfile
import zipfile

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from operatives.models import Operative
from parcelas.models import FireParcel
from .models import FireAction, BurningPlan, BurningPlanPhoto
from .report import generate_bp_docx

MEDIA = tempfile.mkdtemp()


def image_bytes(fmt='PNG', size=(40, 30)):
    buf = io.BytesIO()
    Image.new('RGB', size, 'orange').save(buf, fmt)
    return buf.getvalue()


@override_settings(SECURE_SSL_REDIRECT=False, MEDIA_ROOT=MEDIA)
class FireActionTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.user = User.objects.create_user('u', password='x')
        self.staff = User.objects.create_user('s', password='x', is_staff=True)
        self.client.force_login(self.user)
        self.parcel = FireParcel.objects.create(
            name='P', geometry='POLYGON((-8 37.1,-7.999 37.1,-7.999 37.101,-8 37.101,-8 37.1))', status='apta')
        self.op = Operative.objects.create(name='Op', email='o@example.com', phone='1', certification_level='A')
        self.pp = FireAction.objects.create(name='PP', scheduled_date='2026-11-05', created_by=self.user)
        self.pp.parcels.set([self.parcel])

    def bp_data(self, **overrides):
        return {'pre_plan': self.pp.pk, 'execution_date': '2026-11-06', 'num_men': '5', 'vfci': '2',
                'vfcm': '1', 'other_veh': 'Trator', 'operatives': [self.op.pk], 'fire_conduct': '3',
                **overrides}

    def create_bp(self, **overrides):
        return self.client.post(f'/acoes/burning/novo/{self.pp.pk}/', self.bp_data(**overrides))

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

    # Burning plans

    def test_create_burning_plan(self):
        photo = SimpleUploadedFile('f.png', image_bytes(), content_type='image/png')
        r = self.create_bp(photos=[photo])
        bp = BurningPlan.objects.get()
        self.assertRedirects(r, f'/acoes/burning/{bp.pk}/', fetch_redirect_response=False)
        self.assertEqual(json.loads(bp.vehicles), {'VFCI': 2, 'VFCM': 1, 'Outro': 'Trator'})
        self.assertEqual(list(bp.operatives.all()), [self.op])
        self.assertEqual(bp.photos.count(), 1)
        self.pp.refresh_from_db()
        self.assertEqual((self.pp.status, str(self.pp.execution_date)), ('realizada', '2026-11-06'))

    def test_invalid_inputs_save_nothing(self):
        bad_photo = SimpleUploadedFile('x.png', b'not an image', content_type='image/png')
        for overrides in [{'num_men': '-3'}, {'photos': [bad_photo]}, {'execution_date': ''}]:
            r = self.create_bp(**overrides)
            self.assertEqual(r.status_code, 200, overrides)
        self.assertFalse(BurningPlan.objects.exists())
        self.assertContains(r, 'value="Trator"')
        self.assertEqual(r.context['selected_operatives'], [self.op.pk])

    def test_second_plan_for_same_preplan_rejected(self):
        self.create_bp()
        r = self.client.post('/acoes/burning/novo/', self.bp_data())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(BurningPlan.objects.count(), 1)

    def test_edit_syncs_preplan_date(self):
        self.create_bp()
        bp = BurningPlan.objects.get()
        self.assertContains(self.client.get(f'/acoes/burning/{bp.pk}/editar/'), 'value="2026-11-06"')
        self.client.post(f'/acoes/burning/{bp.pk}/editar/', self.bp_data(execution_date='2026-11-08'))
        self.pp.refresh_from_db()
        self.assertEqual(str(self.pp.execution_date), '2026-11-08')

    def test_delete_permissions_and_cleanup(self):
        self.create_bp(photos=[SimpleUploadedFile('f.png', image_bytes(), content_type='image/png')])
        bp = BurningPlan.objects.get()
        self.client.post(f'/acoes/burning/{bp.pk}/eliminar/')
        self.assertTrue(BurningPlan.objects.exists())  # non-staff blocked

        self.client.force_login(self.staff)
        self.client.post(f'/acoes/burning/{bp.pk}/eliminar/')
        self.assertFalse(BurningPlan.objects.exists())
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
        self.assertEqual(bp.history.first().history_user, self.user)
        self.assertContains(self.client.get(f'/acoes/burning/{bp.pk}/'), 'Histórico de alterações')

    # Report

    def test_report_includes_photos_and_vfcm(self):
        self.create_bp()
        bp = BurningPlan.objects.get()
        photo = BurningPlanPhoto(caption='Frente de chamas')
        photo.image.save('big.jpg', ContentFile(image_bytes('JPEG', (2400, 1800))), save=True)
        missing = BurningPlanPhoto.objects.create(image='bp_photos/nao_existe.jpg')
        bp.photos.add(photo, missing)

        r = self.client.get(f'/acoes/burning/{bp.pk}/relatorio/')
        self.assertEqual(r.status_code, 200)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        xml = z.read('word/document.xml').decode()
        jpgs = [n for n in z.namelist() if n.endswith('.jpg')]
        self.assertEqual(len(jpgs), 1)
        self.assertLessEqual(max(Image.open(io.BytesIO(z.read(jpgs[0]))).size), 1600)
        for text in ['Frente de chamas', '1 fotografia(s) indisponível', 'VFCM', '10. Assinaturas']:
            self.assertIn(text, xml)
        self.assertNotIn('VLCI', xml)

    def test_report_without_geometry(self):
        self.pp.parcels.clear()
        self.create_bp()
        self.assertTrue(generate_bp_docx(BurningPlan.objects.get())[:2] == b'PK')
