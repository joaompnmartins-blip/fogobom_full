import io
import zipfile
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from fire_actions.forms import PrePlanForm
from fire_actions.models import FireAction
from fire_actions.outlook import prescription_issues
from operatives.models import Operative
from parcelas.models import FireParcel, ParcelEvaluation, EvaluationVegetation
from .costs import jornas_per_ha, parcel_estimate, pfc_estimate
from .document import generate_pfc_docx
from .models import PFC, CostSettings, PFCParcel

TODAY = timezone.localdate


def make_tecnico(username='tec', number='552-2026'):
    user = User.objects.create_user(username, email=f'{username}@example.com', password='x')
    Operative.objects.create(user=user, name='Técnico Teste', email=user.email, phone='', certification_level='',
                             credential_type=Operative.CRED_TECNICO, credential_number=number,
                             credential_status=Operative.STATUS_VALIDADA, credential_lifetime=True)
    return user


def square(x0, y0, d):
    return f'POLYGON(({x0} {y0},{x0 + d} {y0},{x0 + d} {y0 + d},{x0} {y0 + d},{x0} {y0}))'


def make_pfc(tec, **kw):
    base = dict(technician=tec, sequence=1, credential_number='552-2026', name='Serra', proponent='Junta',
                validity_start=date(2026, 10, 1), validity_end=date(2030, 9, 30))
    return PFC.objects.create(**{**base, **kw})


COMPLETE = dict(characterization='Matos', fire_history='Incêndio 2018', dfci_infrastructure='Faixas',
                objectives='Prevenção', means='1 técnico, 4 operacionais')


@override_settings(SECURE_SSL_REDIRECT=False)
class PFCViewsTests(TestCase):
    def setUp(self):
        self.tec = make_tecnico()
        self.client.force_login(self.tec)

    def form_data(self, **kw):
        return {'sequence': 7, 'name': 'Serra de Monchique', 'proponent': 'Junta de Freguesia', 'dcnf': 'algarve',
                'validity_start': '2026-10-01', 'validity_end': '2030-09-30', **kw}

    def test_only_tecnicos_create(self):
        self.client.force_login(User.objects.create_user('normal', password='x'))
        self.client.post('/pfc/novo/', self.form_data())
        self.assertFalse(PFC.objects.exists())

    def test_create_numbering_and_validity(self):
        r = self.client.get('/pfc/novo/')
        self.assertEqual(r.context['form'].initial['sequence'], 1)
        r = self.client.post('/pfc/novo/', self.form_data(validity_end='2031-10-02'))   # > 5 years
        self.assertFalse(PFC.objects.exists())
        self.client.post('/pfc/novo/', self.form_data())
        pfc = PFC.objects.get()
        self.assertEqual((pfc.technician, pfc.credential_number, pfc.number), (self.tec, '552-2026', '7/552-2026/—'))
        self.client.post('/pfc/novo/', self.form_data(name='Outro'))   # same sequence for this technician
        self.assertEqual(PFC.objects.count(), 1)
        self.assertEqual(self.client.get('/pfc/novo/').context['form'].initial['sequence'], 8)

    def test_submit_requires_contents_then_tacit_approval(self):
        pfc = make_pfc(self.tec)
        p = FireParcel.objects.create(name='P', geometry=square(-8.46, 37.37, 0.002), status='apta', area_ha=3)
        self.client.post(f'/pfc/{pfc.pk}/estado/', {'action': 'submeter'})
        pfc.refresh_from_db()
        self.assertEqual(pfc.status, 'preparacao')
        PFC.objects.filter(pk=pfc.pk).update(**COMPLETE)
        PFCParcel.objects.create(pfc=pfc, parcel=p, number=1)
        sent = TODAY() - timedelta(days=50)
        self.client.post(f'/pfc/{pfc.pk}/estado/', {'action': 'submeter', 'date': sent.isoformat()})
        pfc.refresh_from_db()
        self.assertEqual(pfc.status, 'submetido')
        self.assertEqual(pfc.display_status, 'Aprovado tacitamente')
        self.assertEqual(pfc.effective_approval_date, sent + timedelta(days=45))
        self.assertEqual(pfc.number, f'1/552-2026/{(sent + timedelta(days=45)).year}')
        self.client.post(f'/pfc/{pfc.pk}/estado/', {'action': 'tacita'})
        pfc.refresh_from_db()
        self.assertEqual((pfc.status, pfc.tacit_approval), ('aprovado', True))

    def test_not_yet_tacit(self):
        pfc = make_pfc(self.tec, status='submetido', submitted_on=TODAY() - timedelta(days=10))
        self.assertIsNone(pfc.effective_approval_date)
        self.assertFalse(pfc.is_in_force)

    def test_other_users_cannot_change(self):
        pfc = make_pfc(self.tec)
        self.client.force_login(make_tecnico('outro', '1-2020'))
        self.client.post(f'/pfc/{pfc.pk}/estado/', {'action': 'aprovar'})
        pfc.refresh_from_db()
        self.assertEqual(pfc.status, 'preparacao')

    def test_add_parcel_prefilled_from_evaluation(self):
        pfc = make_pfc(self.tec)
        p = FireParcel.objects.create(name='P', geometry=square(-8.46, 37.37, 0.002), status='apta', area_ha=3,
                                      vegetation_type='pinhal')
        prop = FireParcel.objects.create(name='Proposta', geometry=square(-8.5, 37.37, 0.002))
        ev = ParcelEvaluation.objects.create(parcel=p, evaluator=self.tec, decision='apta', slope_pct=30,
                                             fuel_load='alta', objectives='prevencao', completed_at=timezone.now())
        EvaluationVegetation.objects.create(evaluation=ev, species='Pinheiro-bravo', cover_pct=80, age_years=28)
        r = self.client.get(f'/pfc/{pfc.pk}/parcelas/nova/?parcel={p.pk}')
        init = r.context['form'].initial
        self.assertEqual((init['cost_type'], init['cost_slope'], init['cost_load'], init['number']),
                         ('povoamento', '>25', 'alta', 1))
        self.assertIn('80% Pinheiro-bravo, 28 anos', init['occupation'])
        self.assertNotIn(prop, r.context['form'].fields['parcel'].queryset)
        r = self.client.post(f'/pfc/{pfc.pk}/parcelas/nova/', {'parcel': p.pk, 'number': 1, 'season': '2026-2027',
                             'temp_min': 15, 'temp_max': 5, 'cost_type': 'povoamento', 'cost_slope': '>25',
                             'cost_load': 'alta'})
        self.assertFalse(PFCParcel.objects.exists())   # min > max
        self.client.post(f'/pfc/{pfc.pk}/parcelas/nova/', {'parcel': p.pk, 'number': 1, 'season': '2026-2027',
                         'temp_min': 5, 'temp_max': 15, 'rh_min': 40, 'cost_type': 'povoamento', 'cost_slope': '>25',
                         'cost_load': 'alta'})
        pp = PFCParcel.objects.get()
        self.assertEqual((pp.season, pp.prescription_rows[0][0]), ('2026-2027', 'Temperatura'))
        page = self.client.get(f'/pfc/{pfc.pk}/')
        self.assertContains(page, 'Estimativa de custos')

    def test_docx(self):
        pfc = make_pfc(self.tec, **COMPLETE)
        p = FireParcel.objects.create(name='Benafátima', geometry=square(-8.46, 37.37, 0.002), status='apta',
                                      area_ha=2.54, concelho='Monchique', freguesia='Alferce')
        PFCParcel.objects.create(pfc=pfc, parcel=p, number=1, season='2026-2027', temp_min=5, temp_max=15,
                                 ignition='contra_vento', n_tecnicos=1)
        r = self.client.get(f'/pfc/{pfc.pk}/documento.docx')
        self.assertEqual(r.status_code, 200)
        xml = zipfile.ZipFile(io.BytesIO(r.content)).read('word/document.xml').decode()
        for text in ['PLANO DE FOGO CONTROLADO', 'PFC 1/552-2026/—', 'Monchique', 'Alferce',
                     'Anexo 3 – Quadro de identificação das parcelas individuais', 'Temperatura: 5 – 15 °C',
                     'Contra o vento', '2026-2027']:
            self.assertIn(text, xml)


class PFCModelTests(TestCase):
    def setUp(self):
        self.tec = make_tecnico()

    def test_seasons(self):
        pfc = PFC(validity_start=date(2026, 3, 1), validity_end=date(2030, 12, 31))
        self.assertEqual(pfc.seasons(), ['2025-2026', '2026-2027', '2027-2028', '2028-2029', '2029-2030', '2030-2031'])

    def test_emergency_plan_required_from_50_ha(self):
        pfc = make_pfc(self.tec, **COMPLETE)
        p = FireParcel.objects.create(name='Grande', geometry=square(-8.46, 37.37, 0.01), status='apta', area_ha=60)
        PFCParcel.objects.create(pfc=pfc, parcel=p, number=1)
        self.assertTrue(pfc.emergency_plan_required)
        self.assertIn('plano de emergência (obrigatório a partir de 50 ha)', pfc.missing_contents)


class CostTests(TestCase):
    def setUp(self):
        self.tec = make_tecnico()
        self.pfc = make_pfc(self.tec)
        self.cfg = CostSettings.current()

    def pp(self, area, **kw):
        p = FireParcel.objects.create(name=f'P{area}{kw}', geometry=square(-8.46, 37.37, 0.001), area_ha=area,
                                      status='apta')
        return PFCParcel(pfc=self.pfc, parcel=p, number=1, **kw)

    def test_caof_extremes(self):
        easy_pov = self.pp(5, cost_type='povoamento', cost_slope='0-10', cost_load='baixa')
        hard_pov = self.pp(1, cost_type='povoamento', cost_slope='>25', cost_load='alta')
        easy_mato = self.pp(7, cost_type='mato', cost_slope='0-10')
        hard_mato = self.pp(1, cost_type='mato', cost_slope='>25', cost_load='alta')   # load ignored in matos
        self.assertEqual([jornas_per_ha(x, self.cfg) for x in (easy_pov, hard_pov, easy_mato, hard_mato)], [1, 5, 1, 4])
        self.assertEqual(parcel_estimate(hard_pov, self.cfg)['eur_ha'], Decimal('639.95'))
        self.assertEqual(parcel_estimate(hard_mato, self.cfg)['eur_ha'], Decimal('511.96'))
        self.assertEqual(parcel_estimate(easy_mato, self.cfg)['eur_ha'], Decimal('127.99'))

    def test_intermediate_and_settings(self):
        mid = self.pp(3, cost_type='mato', cost_slope='10-25')          # 1 + 1 + 0.5
        self.assertEqual(jornas_per_ha(mid, self.cfg), 2.5)
        self.cfg.area_mid_jornas = 1
        self.assertEqual(jornas_per_ha(mid, self.cfg), 3)

    def test_estimate_totals_and_support(self):
        p = FireParcel.objects.create(name='P', geometry=square(-8.46, 37.37, 0.001), area_ha=2.0, status='apta')
        PFCParcel.objects.create(pfc=self.pfc, parcel=p, number=1, cost_type='mato', cost_slope='>25')
        est = pfc_estimate(self.pfc)
        row = est['rows'][0]
        self.assertEqual(row['jornas_ha'], 3.5)                         # 1 + 2 + 0.5 (2 ha is intermediate)
        self.assertEqual(row['support'], Decimal('608.00'))             # 304 €/ha × 2 ha
        self.assertGreater(row['perimeter_m'], 300)
        self.assertEqual(est['plan'], Decimal('255.98'))                # 2 jornas
        self.assertEqual(est['total'], row['total'] + est['plan'])
        self.assertLess(row['coverage_pct'], 100)


@override_settings(SECURE_SSL_REDIRECT=False)
class ActionPFCTests(TestCase):
    def setUp(self):
        self.tec = make_tecnico()
        self.p_in = FireParcel.objects.create(name='Dentro', geometry=square(-8.46, 37.37, 0.002), status='apta')
        self.p_out = FireParcel.objects.create(name='Fora', geometry=square(-8.5, 37.37, 0.002), status='apta')
        self.pfc = make_pfc(self.tec, status='aprovado', approved_on=date(2026, 9, 1),
                            validity_start=TODAY() - timedelta(days=30), validity_end=TODAY() + timedelta(days=700))
        self.pp = PFCParcel.objects.create(pfc=self.pfc, parcel=self.p_in, number=1, rh_min=40, wind_max=15)

    def form(self, **kw):
        data = {'name': 'FC', 'action_type': 'fogo_controlado', 'scheduled_date': (TODAY() + timedelta(days=5)).isoformat(),
                'responsible_user': self.tec.pk, 'pfc': self.pfc.pk, 'parcels': [self.p_in.pk], **kw}
        return PrePlanForm(data)

    def test_only_in_force_pfc_and_its_parcels(self):
        self.assertTrue(self.form().is_valid(), self.form().errors)
        self.assertIn('parcels', self.form(parcels=[self.p_in.pk, self.p_out.pk]).errors)
        self.assertIn('pfc', self.form(scheduled_date=(TODAY() + timedelta(days=800)).isoformat()).errors)
        draft = make_pfc(self.tec, sequence=2)
        self.assertNotIn(draft, self.form().fields['pfc'].queryset)

    def test_legal_framework_uses_pfc(self):
        a = FireAction(name='FC', action_type='fogo_controlado', scheduled_date=TODAY() + timedelta(days=5),
                       pfc=self.pfc)
        self.assertEqual(a.legal_missing, [])
        a.scheduled_date = TODAY() + timedelta(days=800)
        self.assertTrue(a.legal_missing)

    def test_prescription_issues(self):
        a = FireAction(name='FC', action_type='fogo_controlado', scheduled_date=TODAY(), pfc=self.pfc)
        fuel = {'t_max': 20, 'rh_min': 30, 'wind_max': 10, 'dry_days': 5}
        self.assertEqual(prescription_issues(a, [self.p_in], fuel), ['HR mín. 30% < 40%'])
        self.assertEqual(prescription_issues(a, [self.p_out], fuel), [])
