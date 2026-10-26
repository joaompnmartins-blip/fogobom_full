import io
import json
from datetime import date
from unittest import mock

from django.contrib.auth.models import User
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon, Polygon
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from PIL import Image

from fire_actions.models import BurningPlan, FireAction, ParcelExecution
from operatives.models import Operative
from . import geo
from .models import FireParcel, Freguesia, ParcelEvaluation
from .views import parcel_centroids


def ring(x0, y0, dx, dy):
    return [[x0, y0], [x0 + dx, y0], [x0 + dx, y0 + dy], [x0, y0 + dy], [x0, y0]]


def wkt(x0, y0, dx, dy):
    return 'POLYGON((' + ','.join(f'{x} {y}' for x, y in ring(x0, y0, dx, dy)) + '))'


SQUARE = json.dumps({'type': 'Polygon', 'coordinates': [ring(-8.0, 37.1, 0.001, 0.0009)]})


def make_tecnico(username='tec'):
    user = User.objects.create_user(username, email=f'{username}@example.com', password='x')
    Operative.objects.create(user=user, name='Técnico Teste', email=user.email, phone='', certification_level='',
                             credential_type=Operative.CRED_TECNICO, credential_number='1-2020',
                             credential_status=Operative.STATUS_VALIDADA, credential_lifetime=True)
    return user


def add_freguesia(code, name, concelho, x0, y0, dx, dy):
    """CAOP-like parish polygon given in WGS84 degrees, stored in PT-TM06."""
    g = GEOSGeometry(wkt(x0, y0, dx, dy), srid=4326).transform(3763, clone=True)
    Freguesia.objects.create(dicofre=code, freguesia=name, concelho=concelho, distrito='Faro',
                             geom=MultiPolygon(g, srid=3763))


NO_TERRAIN = mock.patch('parcelas.views.terrain', return_value=None)
NO_MAIL = mock.patch('parcelas.views.send_async')


@override_settings(SECURE_SSL_REDIRECT=False)
class ProposalTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='x')
        self.client.force_login(self.user)

    def post_parcela(self, url='/parcelas/nova/', **overrides):
        data = {'name': 'Parcela A', 'vegetation_type': 'matos', 'infrastructure': 'no_info',
                'owner_info': 'no', 'geometry': SQUARE, **overrides}
        with NO_MAIL:
            return self.client.post(url, data)

    def test_proposal_is_pending_and_computes_area(self):
        r = self.post_parcela()
        p = FireParcel.objects.get(name='Parcela A')
        self.assertRedirects(r, f'/parcelas/{p.pk}/', fetch_redirect_response=False)
        self.assertEqual((p.status, p.proposed_by), ('proposta', self.user))
        self.assertAlmostEqual(p.area_ha, 0.888, places=2)

    def test_location_from_caop(self):
        add_freguesia('080801', 'Almancil', 'Loulé', -8.01, 37.09, 0.0108, 0.02)    # ~80% of the parcel
        add_freguesia('080802', 'Quarteira', 'Loulé', -7.9992, 37.09, 0.01, 0.02)   # ~20% slice
        self.post_parcela()
        p = FireParcel.objects.get()
        self.assertEqual((p.concelho, p.distrito), ('Loulé', 'Faro'))
        self.assertEqual(p.freguesia, 'Almancil; Quarteira')

    def test_location_empty_without_caop(self):
        self.post_parcela()
        self.assertEqual(FireParcel.objects.get().concelho, '')

    def test_new_proposal_notifies_tecnicos(self):
        make_tecnico()
        with mock.patch('parcelas.views.send_async') as send:
            self.client.post('/parcelas/nova/', {'name': 'X', 'vegetation_type': 'matos', 'infrastructure': 'no_info',
                                                 'owner_info': 'no', 'geometry': SQUARE})
        self.assertEqual(send.call_args.args[2], ['tec@example.com'])

    def test_overlap_requires_confirmation(self):
        FireParcel.objects.create(name='Existente', geometry=wkt(-8.0, 37.1, 0.001, 0.0009), status='apta')
        r = self.post_parcela(name='Nova')
        self.assertContains(r, 'sobrepõe-se a parcelas existentes')
        self.assertFalse(FireParcel.objects.filter(name='Nova').exists())
        self.post_parcela(name='Nova', confirm_overlap='1')
        self.assertTrue(FireParcel.objects.filter(name='Nova').exists())

    def test_touching_parcels_are_not_overlaps(self):
        FireParcel.objects.create(name='Vizinha', geometry=wkt(-7.999, 37.1, 0.001, 0.0009), status='apta')
        self.post_parcela()
        self.assertTrue(FireParcel.objects.filter(name='Parcela A').exists())

    def test_preview_api(self):
        add_freguesia('080801', 'Almancil', 'Loulé', -8.01, 37.09, 0.02, 0.02)
        FireParcel.objects.create(name='Existente', geometry=wkt(-8.0, 37.1, 0.001, 0.0009), status='apta')
        r = self.client.post('/parcelas/api/preview/', json.loads(json.dumps({'geometry': json.loads(SQUARE)})),
                             content_type='application/json')
        d = r.json()
        self.assertAlmostEqual(d['area_ha'], 0.888, places=2)
        self.assertEqual(d['location']['concelho'], 'Loulé')
        self.assertEqual(d['overlaps'][0]['name'], 'Existente')

    def test_invalid_geometries_rejected(self):
        bowtie = json.dumps({'type': 'Polygon', 'coordinates': [[[-8, 37.1], [-7.99, 37.11], [-7.99, 37.1],
                                                                 [-8, 37.11], [-8, 37.1]]]})
        point = json.dumps({'type': 'Point', 'coordinates': [-8, 37.1]})
        for g in ['', 'lixo', point, bowtie]:
            self.assertEqual(self.post_parcela(geometry=g).status_code, 200, g)
        self.assertFalse(FireParcel.objects.exists())

    def test_invalid_choice_rejected_and_input_kept(self):
        r = self.post_parcela(vegetation_type='xpto', resp_email='mau-email')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(FireParcel.objects.exists())
        self.assertContains(r, 'mau-email')

    def test_multipolygon_keeps_largest_part(self):
        geom = json.dumps({'type': 'MultiPolygon', 'coordinates': [[ring(-8.01, 37.1, 0.001, 0.001)],
                                                                    [ring(-8.02, 37.1, 0.0002, 0.0002)]]})
        self.post_parcela(geometry=geom)
        self.assertGreater(FireParcel.objects.get().area_ha, 0.8)

    def test_edit_permissions(self):
        self.post_parcela()
        p = FireParcel.objects.get()
        # proposer can edit while it is a proposal (empty geometry keeps the shape)
        self.post_parcela(url=f'/parcelas/{p.pk}/editar/', name='Parcela B', geometry='')
        p.refresh_from_db()
        self.assertEqual(p.name, 'Parcela B')
        self.assertAlmostEqual(p.area_ha, 0.888, places=2)
        # another user cannot
        self.client.force_login(User.objects.create_user('outro', password='x'))
        self.post_parcela(url=f'/parcelas/{p.pk}/editar/', name='Hack', geometry='')
        p.refresh_from_db()
        self.assertEqual(p.name, 'Parcela B')
        # once evaluated, not even the proposer
        FireParcel.objects.filter(pk=p.pk).update(status='apta')
        self.client.force_login(self.user)
        self.post_parcela(url=f'/parcelas/{p.pk}/editar/', name='Depois', geometry='')
        p.refresh_from_db()
        self.assertEqual(p.name, 'Parcela B')

    def test_history_records_user_and_changed_fields(self):
        self.post_parcela()
        p = FireParcel.objects.get()
        self.post_parcela(url=f'/parcelas/{p.pk}/editar/', name='Parcela B', geometry='')
        records = list(p.history.order_by('history_date'))
        self.assertEqual([r.history_type for r in records], ['+', '~'])
        self.assertTrue(all(r.history_user == self.user for r in records))
        r = self.client.get(f'/parcelas/{p.pk}/')
        self.assertContains(r, 'Histórico de alterações')
        self.assertContains(r, 'Nome')

    def test_only_staff_can_delete(self):
        p = FireParcel.objects.create(name='P', geometry=wkt(-8, 37.1, .001, .001))
        self.client.post(f'/parcelas/{p.pk}/eliminar/')
        self.assertTrue(FireParcel.objects.filter(pk=p.pk).exists())
        self.client.force_login(User.objects.create_user('s', password='x', is_staff=True))
        self.client.post(f'/parcelas/{p.pk}/eliminar/')
        self.assertFalse(FireParcel.objects.filter(pk=p.pk).exists())


@override_settings(SECURE_SSL_REDIRECT=False)
class ListTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user('u', password='x'))

    def test_list_last_burn_and_constant_queries(self):
        p1 = FireParcel.objects.create(name='P1', geometry=wkt(-8, 37.1, .001, .001), status='apta')
        p2 = FireParcel.objects.create(name='P2', geometry=wkt(-8.1, 37.2, .001, .001), status='apta')
        for i, (d, parcels) in enumerate([('2026-01-11', [p1, p2]), ('2026-03-12', [p1])]):
            a = FireAction.objects.create(name=f'A{i}', scheduled_date=d)
            a.parcels.set(parcels)
            plan = BurningPlan.objects.create(pre_plan=a, execution_date=d)
            for parcel in parcels:
                ParcelExecution.objects.create(plan=plan, parcel=parcel, date=d)
        with CaptureQueriesContext(connection) as q2:
            r = self.client.get('/parcelas/')
        self.assertEqual({p.name: str(p.last_burn) for p in r.context['parcelas']},
                         {'P1': '2026-03-12', 'P2': '2026-01-11'})
        for i in range(5):
            FireParcel.objects.create(name=f'X{i}', geometry=wkt(-8.3, 37.3 + i / 100, .001, .001))
        with CaptureQueriesContext(connection) as q7:
            self.client.get('/parcelas/')
        self.assertEqual(len(q2), len(q7))  # no per-parcel queries

    def test_filters(self):
        FireParcel.objects.create(name='A', geometry=wkt(-8, 37.1, .001, .001), status='apta', concelho='Loulé')
        FireParcel.objects.create(name='B', geometry=wkt(-8.1, 37.1, .001, .001), status='proposta', concelho='Faro')
        names = lambda q: [p.name for p in self.client.get('/parcelas/' + q).context['parcelas']]
        self.assertEqual(names('?status=apta'), ['A'])
        self.assertEqual(names('?concelho=Faro'), ['B'])

    def test_names_are_escaped(self):
        FireParcel.objects.create(name='<b>x</b>', geometry=wkt(-8, 37.1, .001, .001))
        r = self.client.get('/parcelas/')
        self.assertNotContains(r, '<b>x</b>')
        self.assertContains(r, '&lt;b&gt;x&lt;/b&gt;')

    def test_centroids(self):
        p = FireParcel.objects.create(name='P', geometry=wkt(-8, 37.1, .002, .002))
        self.assertEqual(parcel_centroids(), [{'id': str(p.pk), 'name': 'P', 'lat': 37.101, 'lng': -7.999}])
        self.assertEqual(self.client.get('/parcelas/api/centroids/').json()[0]['name'], 'P')

    def test_geojson_includes_status(self):
        FireParcel.objects.create(name='P', geometry=wkt(-8, 37.1, .001, .001), status='apta')
        self.assertEqual(self.client.get('/parcelas/api/geojson/').json()['features'][0]['properties']['status'], 'apta')


@override_settings(SECURE_SSL_REDIRECT=False)
class EvaluationTests(TestCase):
    def setUp(self):
        self.proposer = User.objects.create_user('prop', email='prop@example.com', password='x')
        self.parcel = FireParcel.objects.create(name='P', geometry=wkt(-8, 37.1, .001, .001),
                                                proposed_by=self.proposer, area_ha=1)
        self.tec = make_tecnico()

    def start(self, user=None):
        self.client.force_login(user or self.tec)
        with mock.patch('parcelas.views.terrain',
                        return_value={'altitude_m': 120, 'slope_pct': 14.5, 'aspect': 'SW', 'source': 'teste'}):
            return self.client.post(f'/parcelas/{self.parcel.pk}/avaliar/')

    def submit(self, ev, action='save', **data):
        base = {'action': action, 'veg-TOTAL_FORMS': '1', 'veg-INITIAL_FORMS': '0', 'veg-MIN_NUM_FORMS': '0',
                'veg-MAX_NUM_FORMS': '1000', 'veg-0-species': 'Tojo', 'veg-0-cover_pct': '70', 'veg-0-height_m': '0.5'}
        with NO_MAIL as send:
            r = self.client.post(f'/parcelas/avaliacao/{ev.pk}/', {**base, **data})
        return r, send

    def test_only_tecnicos_can_evaluate(self):
        self.start(user=self.proposer)
        self.assertFalse(ParcelEvaluation.objects.exists())
        self.parcel.refresh_from_db()
        self.assertEqual(self.parcel.status, 'proposta')

    def test_start_prefills_terrain_and_marks_in_evaluation(self):
        r = self.start()
        ev = ParcelEvaluation.objects.get()
        self.assertRedirects(r, f'/parcelas/avaliacao/{ev.pk}/', fetch_redirect_response=False)
        self.assertEqual((ev.altitude_m, ev.slope_pct, ev.aspect, ev.evaluator), (120, 14.5, 'SW', self.tec))
        self.parcel.refresh_from_db()
        self.assertEqual(self.parcel.status, 'em_avaliacao')
        self.assertContains(self.client.get(f'/parcelas/avaliacao/{ev.pk}/'), 'Classificação da dificuldade')

    def test_draft_then_conclude(self):
        self.start()
        ev = ParcelEvaluation.objects.get()
        r, _ = self.submit(ev, 'save', fuel_load='alta', objectives=['prevencao', 'pastoreio'])
        ev.refresh_from_db()
        self.assertEqual((ev.fuel_load, ev.objectives, ev.vegetation.count()), ('alta', 'prevencao,pastoreio', 1))
        self.assertFalse(ev.is_complete)

        r, _ = self.submit(ev, 'conclude', **{'veg-INITIAL_FORMS': '0'})   # missing visit/decision/justification
        self.assertEqual(r.status_code, 200)
        self.parcel.refresh_from_db()
        self.assertEqual(self.parcel.status, 'em_avaliacao')

        r, _ = self.submit(ev, 'conclude', visit_date='2026-10-20', decision='apta_condicionantes',
                           justification='Bom acesso')
        self.assertEqual(r.status_code, 200)   # conditions required for this decision

        r, send = self.submit(ev, 'conclude', visit_date='2026-10-20', decision='apta_condicionantes',
                              justification='Bom acesso', conditions='Abrir faixa a sul',
                              **{f: '3' for f, _, _ in ParcelEvaluation.DIFFICULTY_ELEMENTS})
        self.assertRedirects(r, f'/parcelas/{self.parcel.pk}/', fetch_redirect_response=False)
        self.parcel.refresh_from_db()
        ev.refresh_from_db()
        self.assertEqual(self.parcel.status, 'apta_condicionantes')
        self.assertTrue(ev.is_complete)
        self.assertEqual((ev.difficulty_total, ev.difficulty_class), (45, 'Normal'))
        self.assertEqual(send.call_args.args[2], ['prop@example.com'])
        page = self.client.get(f'/parcelas/{self.parcel.pk}/')
        self.assertContains(page, 'Abrir faixa a sul')
        self.assertContains(page, 'Normal (45 pontos)')

    def test_cancel_returns_to_proposal(self):
        self.start()
        ev = ParcelEvaluation.objects.get()
        self.client.post(f'/parcelas/avaliacao/{ev.pk}/', {'action': 'cancel'})
        self.assertFalse(ParcelEvaluation.objects.exists())
        self.parcel.refresh_from_db()
        self.assertEqual(self.parcel.status, 'proposta')

    def test_reevaluation_copies_previous_and_keeps_status(self):
        self.start()
        ev = ParcelEvaluation.objects.get()
        self.submit(ev, 'conclude', visit_date='2026-10-20', decision='apta', justification='OK', access='Estrada')
        self.start()
        new = ParcelEvaluation.objects.exclude(pk=ev.pk).get()
        self.assertEqual((new.access, new.vegetation.count(), new.decision), ('Estrada', 1, ''))
        self.parcel.refresh_from_db()
        self.assertEqual(self.parcel.status, 'apta')   # stays usable while re-evaluating


@override_settings(SECURE_SSL_REDIRECT=False)
class ActionParcelSelectionTests(TestCase):
    def test_only_apta_parcels_selectable(self):
        self.client.force_login(User.objects.create_user('u', password='x'))
        apta = FireParcel.objects.create(name='Apta', geometry=wkt(-8, 37.1, .001, .001), status='apta')
        prop = FireParcel.objects.create(name='Proposta', geometry=wkt(-8.1, 37.1, .001, .001))
        page = self.client.get('/acoes/novo/')
        self.assertContains(page, 'Apta')
        self.assertNotContains(page, 'value="%d"' % prop.pk)
        self.client.post('/acoes/novo/', {'name': 'A1', 'scheduled_date': '2026-11-05', 'parcels': [prop.pk]})
        self.assertFalse(FireAction.objects.filter(name='A1').exists())
        self.client.post('/acoes/novo/', {'name': 'A2', 'scheduled_date': '2026-11-05', 'parcels': [apta.pk]})
        self.assertEqual(list(FireAction.objects.get(name='A2').parcels.all()), [apta])


class TerrainTests(TestCase):
    """Terrain from a synthetic MapTiler tile: elevation rises 1.5 m per pixel to the east."""

    def tile_png(self, size, per_px=1.5):
        img = Image.new('RGB', (size, size))
        px = img.load()
        for i in range(size):
            v = int(round((100 + i * per_px + 10000) / 0.1))
            for j in range(size):
                px[i, j] = (v >> 16 & 255, v >> 8 & 255, v & 255)
        buf = io.BytesIO()
        img.save(buf, 'PNG')
        return buf.getvalue()

    @override_settings(MAPTILER_API_KEY='k')
    def test_maptiler_slope_and_aspect(self):
        geom = GEOSGeometry(wkt(-8.02, 37.1, 0.004, 0.003), srid=4326)   # inside a single z13 tile
        for size in (256, 512):   # terrain-rgb-v2 serves 512 px tiles; the size is read from the image
            with mock.patch('parcelas.geo._fetch', return_value=self.tile_png(size)):
                t = geo.terrain_maptiler(geom)
            cell = geo.math.cos(geo.math.radians(37.1015)) * 2 * geo.math.pi * 6378137 / (size * 2 ** geo.TERRAIN_ZOOM)
            self.assertAlmostEqual(t['slope_pct'], 1.5 / cell * 100, delta=0.4, msg=size)
            self.assertEqual(t['aspect'], 'W', msg=size)   # rises to the east → faces west

    @override_settings(MAPTILER_API_KEY='k')
    def test_maptiler_altitude_reads_the_right_pixel(self):
        # Elevation = 100 + 1.5 * column; the parcel sits at a known column of a 512 px tile
        geom = GEOSGeometry(wkt(-8.02, 37.1, 0.004, 0.003), srid=4326)
        with mock.patch('parcelas.geo._fetch', return_value=self.tile_png(512)):
            t = geo.terrain_maptiler(geom)
        x, _ = geo._tile_xy(37.1015, -8.018, geo.TERRAIN_ZOOM)
        expected = 100 + 1.5 * (x - int(x)) * 512
        self.assertAlmostEqual(t['altitude_m'], expected, delta=3)

    def test_flat_is_plano(self):
        self.assertEqual(geo._summary([10, 10], [0.5], 0, 0, 'x')['aspect'], 'plano')
        self.assertEqual(geo._aspect_name(0), 'N')
        self.assertEqual(geo._aspect_name(225), 'SW')

    def test_open_meteo_plane_fit(self):
        geom = GEOSGeometry(wkt(-8.0, 37.1, 0.01, 0.01), srid=4326)

        def fake_fetch(url):
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(url).query)
            lats = [float(v) for v in q['latitude'][0].split(',')]
            # rises 10 m per 0.001° of latitude to the north → faces south
            return json.dumps({'elevation': [100 + (lat - 37.1) * 10000 for lat in lats]}).encode()
        with mock.patch('parcelas.geo._fetch', side_effect=fake_fetch):
            t = geo.terrain_open_meteo(geom)
        self.assertEqual(t['aspect'], 'S')
        self.assertAlmostEqual(t['slope_pct'], 9.0, delta=0.6)   # 10 m / ~111 m

    def test_terrain_returns_none_when_all_fail(self):
        with mock.patch('parcelas.geo._fetch', side_effect=OSError('offline')):
            self.assertIsNone(geo.terrain(GEOSGeometry(wkt(-8, 37.1, .001, .001), srid=4326)))
