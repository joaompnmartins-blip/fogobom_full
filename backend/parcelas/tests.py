import json

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from fire_actions.models import FireAction, BurningPlan
from .models import FireParcel
from .views import parcel_centroids


def ring(x0, y0, dx, dy):
    return [[x0, y0], [x0 + dx, y0], [x0 + dx, y0 + dy], [x0, y0 + dy], [x0, y0]]


def wkt(x0, y0, dx, dy):
    return 'POLYGON((' + ','.join(f'{x} {y}' for x, y in ring(x0, y0, dx, dy)) + '))'


SQUARE = json.dumps({'type': 'Polygon', 'coordinates': [ring(-8.0, 37.1, 0.001, 0.0009)]})


@override_settings(SECURE_SSL_REDIRECT=False)
class ParcelaTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='x')
        self.client.force_login(self.user)

    def post_parcela(self, url='/parcelas/nova/', **overrides):
        data = {'name': 'Parcela A', 'concelho': 'Loulé', 'vegetation_type': 'matos',
                'infrastructure': 'no_info', 'owner_info': 'no', 'geometry': SQUARE, **overrides}
        return self.client.post(url, data)

    def test_create_computes_area(self):
        r = self.post_parcela()
        self.assertRedirects(r, '/parcelas/', fetch_redirect_response=False)
        p = FireParcel.objects.get(name='Parcela A')
        self.assertAlmostEqual(p.area_ha, 0.888, places=2)

    def test_multipolygon_keeps_largest_part(self):
        geom = json.dumps({'type': 'MultiPolygon', 'coordinates': [[ring(-8.01, 37.1, 0.001, 0.001)],
                                                                    [ring(-8.02, 37.1, 0.0002, 0.0002)]]})
        self.post_parcela(geometry=geom)
        self.assertGreater(FireParcel.objects.get().area_ha, 0.8)

    def test_invalid_geometries_rejected(self):
        bowtie = json.dumps({'type': 'Polygon', 'coordinates': [[[-8, 37.1], [-7.99, 37.11], [-7.99, 37.1],
                                                                 [-8, 37.11], [-8, 37.1]]]})
        point = json.dumps({'type': 'Point', 'coordinates': [-8, 37.1]})
        for geom in ['', 'lixo', point, bowtie]:
            r = self.post_parcela(geometry=geom)
            self.assertEqual(r.status_code, 200, geom)
        self.assertFalse(FireParcel.objects.exists())

    def test_invalid_choice_rejected_and_input_kept(self):
        r = self.post_parcela(vegetation_type='xpto', resp_email='mau-email')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(FireParcel.objects.exists())
        self.assertContains(r, 'mau-email')

    def test_edit_without_geometry_keeps_shape(self):
        self.post_parcela()
        p = FireParcel.objects.get()
        self.post_parcela(url=f'/parcelas/{p.pk}/editar/', name='Parcela B', geometry='')
        p.refresh_from_db()
        self.assertEqual(p.name, 'Parcela B')
        self.assertAlmostEqual(p.area_ha, 0.888, places=2)

    def test_list_last_burn_single_query_per_page(self):
        p1 = FireParcel.objects.create(name='P1', geometry=wkt(-8, 37.1, .001, .001))
        p2 = FireParcel.objects.create(name='P2', geometry=wkt(-8.1, 37.2, .001, .001))
        for i, (date, parcels) in enumerate([('2026-01-11', [p1, p2]), ('2026-03-12', [p1])]):
            a = FireAction.objects.create(name=f'A{i}', scheduled_date=date)
            a.parcels.set(parcels)
            BurningPlan.objects.create(pre_plan=a, execution_date=date)
        with self.assertNumQueries(3):  # session, user, parcels
            r = self.client.get('/parcelas/')
        burns = {p.name: str(p.last_burn) for p in r.context['parcelas']}
        self.assertEqual(burns, {'P1': '2026-03-12', 'P2': '2026-01-11'})

    def test_names_are_escaped(self):
        FireParcel.objects.create(name='<b>x</b>', geometry=wkt(-8, 37.1, .001, .001))
        r = self.client.get('/parcelas/')
        self.assertNotContains(r, '<b>x</b>')
        self.assertContains(r, '&lt;b&gt;x&lt;/b&gt;')

    def test_centroids(self):
        p = FireParcel.objects.create(name='P', geometry=wkt(-8, 37.1, .002, .002))
        self.assertEqual(parcel_centroids(), [{'id': str(p.pk), 'name': 'P', 'lat': 37.101, 'lng': -7.999}])
        self.assertEqual(self.client.get('/parcelas/api/centroids/').json()[0]['name'], 'P')

    def test_only_staff_can_delete(self):
        p = FireParcel.objects.create(name='P', geometry=wkt(-8, 37.1, .001, .001))
        self.client.post(f'/parcelas/{p.pk}/eliminar/')
        self.assertTrue(FireParcel.objects.filter(pk=p.pk).exists())
        self.client.force_login(User.objects.create_user('s', password='x', is_staff=True))
        self.client.post(f'/parcelas/{p.pk}/eliminar/')
        self.assertFalse(FireParcel.objects.filter(pk=p.pk).exists())
