import io
import json
import sqlite3
import tempfile
import zipfile
from datetime import date, time
from decimal import Decimal
from unittest import skipUnless

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from fire_actions.models import BurningPlan, CostLine, FireAction, ParcelExecution, WeatherReading
from parcelas.models import FireParcel
from . import gis
from .stats import compute

SQUARE = 'POLYGON((-8.46 37.37,-8.459 37.37,-8.459 37.371,-8.46 37.371,-8.46 37.37))'


@override_settings(SECURE_SSL_REDIRECT=False)
class AnaliseTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='x')
        self.client.force_login(self.user)
        self.parcel = FireParcel.objects.create(name='Cerro', geometry=SQUARE, status='apta', area_ha=2.5,
                                                concelho='Monchique', freguesia='Alferce', distrito='Faro',
                                                resp_name='Dono', resp_email='dono@example.com')
        FireParcel.objects.create(name='Outra', geometry=SQUARE, status='proposta', concelho='Loulé')
        action = FireAction.objects.create(name='Queimada A', scheduled_date=date(2026, 1, 20), status='realizada')
        action.parcels.set([self.parcel])
        self.plan = BurningPlan.objects.create(pre_plan=action, execution_date=date(2026, 1, 20))
        self.ex = ParcelExecution.objects.create(plan=self.plan, parcel=self.parcel, date=date(2026, 1, 20),
                                                 start_time=time(9), end_time=time(12), area_treated_ha=2,
                                                 formation='mato', problems='fumo', rating_objectives=4)
        WeatherReading.objects.create(execution=self.ex, time=time(9, 30), temp=14, rh=60, wind_kmh=8)
        CostLine.objects.create(execution=self.ex, qty_burn=10, unit_price=Decimal('12.5'))

    def test_stats(self):
        s = compute(2026)
        k = s['kpis']
        self.assertEqual((k['area'], k['actions_done'], k['burn_days'], k['real']), (2, 1, 1, Decimal('125.00')))
        self.assertEqual([(r['label'], r['pct']) for r in s['area_by_concelho']], [('Monchique', 100.0)])
        self.assertEqual([r['label'] for r in s['problems']], ['Deficiente dispersão do fumo'])
        self.assertEqual(s['weather']['t_max'], 14)
        self.assertEqual(compute(2025)['kpis']['area'], 0)
        r = self.client.get('/estatisticas/?ano=2026')
        self.assertContains(r, 'hectares tratados')
        self.assertContains(r, 'Monchique')

    def test_csv(self):
        r = self.client.get('/estatisticas/execucoes.csv')
        text = r.content.decode('utf-8-sig')
        header, row = text.splitlines()[:2]
        self.assertIn('area_tratada_ha', header)
        self.assertIn('Cerro;Monchique;Alferce;Mato;2', row)
        self.assertIn('Deficiente dispersão do fumo', row)

    def test_geojson_exports_without_contacts(self):
        r = self.client.get('/gis/parcelas.geojson?estado=apta')
        data = json.loads(r.content)
        self.assertEqual(len(data['features']), 1)
        props = data['features'][0]['properties']
        self.assertEqual((props['nome'], props['n_queimas'], props['ult_queima']), ('Cerro', 1, '2026-01-20'))
        self.assertNotIn('dono', r.content.decode().lower())
        data = json.loads(self.client.get(f'/gis/execucao/{self.plan.pk}.geojson').content)
        self.assertEqual(data['features'][0]['properties']['id_parc'], 'Cerro')
        self.assertEqual(self.client.get('/gis/parcelas.xyz').status_code, 302)   # unknown format
        self.assertEqual(self.client.get('/gis/areas-tratadas.geojson?ano=1999').status_code, 302)   # nothing
        self.assertContains(self.client.get('/gis/'), 'PT-TM06')

    @skipUnless(gis.ogr2ogr_available(), 'ogr2ogr not installed')
    def test_shapefile_geopackage_kml(self):
        r = self.client.get(f'/gis/execucao/{self.plan.pk}.shp')
        names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
        self.assertTrue({n.rsplit('.', 1)[1] for n in names} >= {'shp', 'shx', 'dbf', 'prj'})
        prj = zipfile.ZipFile(io.BytesIO(r.content)).read([n for n in names if n.endswith('.prj')][0]).decode()
        self.assertIn('TM06', prj.replace('_', '-').replace(' ', '-'))
        r = self.client.get('/gis/parcelas.gpkg')
        with tempfile.NamedTemporaryFile(suffix='.gpkg') as f:
            f.write(r.content)
            f.flush()
            con = sqlite3.connect(f.name)
            srs = con.execute('select srs_id from gpkg_contents').fetchone()[0]
            con.close()
        self.assertEqual(srs, 3763)
        r = self.client.get('/gis/areas-tratadas.kml')
        self.assertIn(b'<kml', r.content)
        self.assertIn(b'Cerro', r.content)
