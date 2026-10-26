"""
Plano de Fogo Controlado (PFC) — Regulamento do Fogo Técnico (Despacho 7511/2014), art. 12.º–14.º —
its parcels with the burning prescription, and the cost estimate (CAOF matrix + ICNF support).
"""
from datetime import date, timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords

from parcelas.models import FireParcel

TACIT_APPROVAL_DAYS = 45      # art. 13.º n.º 3
MAX_VALIDITY_YEARS = 5        # art. 12.º n.º 2
EMERGENCY_PLAN_REQUIRED_HA = 50   # art. 12.º n.º 3 h)


class PFC(models.Model):
    STATUS_PREPARACAO = 'preparacao'
    STATUS_SUBMETIDO  = 'submetido'
    STATUS_APROVADO   = 'aprovado'
    STATUS_SUSPENSO   = 'suspenso'
    STATUS_REVISAO    = 'em_revisao'
    STATUS_CONCLUIDO  = 'concluido'
    STATUS_CHOICES = [
        (STATUS_PREPARACAO, 'Em preparação'),
        (STATUS_SUBMETIDO,  'Submetido à comissão municipal'),
        (STATUS_APROVADO,   'Aprovado'),
        (STATUS_SUSPENSO,   'Suspenso'),
        (STATUS_REVISAO,    'Em revisão'),
        (STATUS_CONCLUIDO,  'Concluído'),
    ]
    DCNF = [('norte', 'DCNF do Norte'), ('centro', 'DCNF do Centro'), ('lvt', 'DCNF de Lisboa e Vale do Tejo'),
            ('alentejo', 'DCNF do Alentejo'), ('algarve', 'DCNF do Algarve')]

    technician    = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='pfcs',
                                      verbose_name='técnico responsável pela elaboração')
    sequence      = models.PositiveIntegerField('n.º sequencial')
    credential_number = models.CharField('n.º de credenciação', max_length=20)
    name          = models.CharField('designação', max_length=200)
    proponent     = models.CharField('entidade proponente', max_length=200)
    proponent_contact = models.CharField('contacto do proponente', max_length=200, blank=True, default='')
    management_unit = models.CharField('Mata Nacional / Perímetro Florestal / Área Protegida / ZIF / OPF',
                                       max_length=200, blank=True, default='')
    dcnf          = models.CharField('DCNF', max_length=10, choices=DCNF, default='algarve')
    military_map_sheets = models.CharField('folhas da Carta Militar 1:25 000', max_length=100, blank=True, default='')
    validity_start = models.DateField('início da validade')
    validity_end  = models.DateField('fim da validade')

    status        = models.CharField('estado', max_length=15, choices=STATUS_CHOICES, default=STATUS_PREPARACAO)
    approval_entity = models.CharField('entidade que aprova', max_length=200, blank=True,
                                       default='Comissão Municipal de Gestão Integrada de Fogos Rurais')
    submitted_on  = models.DateField('data de envio à comissão municipal', null=True, blank=True)
    approved_on   = models.DateField('data de aprovação', null=True, blank=True)
    tacit_approval = models.BooleanField('aprovação tácita', default=False)
    status_notes  = models.TextField('notas sobre o estado (suspensão, revisão…)', blank=True, default='')

    # Mandatory contents (art. 12.º n.º 3 and 4)
    characterization = models.TextField('caracterização da área (orografia, uso do solo, formações vegetais, combustíveis)',
                                        blank=True, default='')
    fire_history  = models.TextField('história do fogo', blank=True, default='')
    dfci_infrastructure = models.TextField('infraestruturas de DFCI', blank=True, default='')
    objectives    = models.TextField('objetivos específicos', blank=True, default='')
    means         = models.TextField('meios humanos e materiais', blank=True, default='')
    emergency_plan = models.TextField('plano de emergência e de contingência', blank=True, default='')
    other_elements = models.TextField('outros elementos pertinentes', blank=True, default='')

    created_at    = models.DateTimeField(auto_now_add=True)
    history       = HistoricalRecords()

    class Meta:
        ordering = ['-created_at']
        unique_together = [('credential_number', 'sequence')]
        verbose_name = 'Plano de Fogo Controlado'
        verbose_name_plural = 'Planos de Fogo Controlado'

    def __str__(self):
        return f'PFC {self.number} — {self.name}'

    # ── Approval ──
    @property
    def tacit_approval_date(self):
        return self.submitted_on + timedelta(days=TACIT_APPROVAL_DAYS) if self.submitted_on else None

    @property
    def effective_approval_date(self):
        """Explicit approval, or tacit approval 45 days after submission without a decision."""
        if self.status == self.STATUS_APROVADO or (self.status in (self.STATUS_SUSPENSO, self.STATUS_CONCLUIDO)
                                                    and self.approved_on):
            return self.approved_on
        if self.status == self.STATUS_SUBMETIDO and self.tacit_approval_date \
                and timezone.localdate() >= self.tacit_approval_date:
            return self.tacit_approval_date
        return None

    @property
    def number(self):
        """N.º sequencial / n.º de credenciação / ano de aprovação."""
        d = self.effective_approval_date
        return f'{self.sequence}/{self.credential_number}/{d.year if d else "—"}'

    @property
    def is_expired(self):
        return timezone.localdate() > self.validity_end

    @property
    def is_in_force(self):
        """Approved (explicitly or tacitly), not suspended and within its validity."""
        return (self.effective_approval_date is not None and self.status != self.STATUS_SUSPENSO
                and self.validity_start <= timezone.localdate() <= self.validity_end)

    def in_force_on(self, d):
        return (self.effective_approval_date is not None and self.status != self.STATUS_SUSPENSO
                and self.validity_start <= d <= self.validity_end)

    @property
    def display_status(self):
        if self.status == self.STATUS_SUBMETIDO and self.effective_approval_date:
            return 'Aprovado tacitamente'
        if self.effective_approval_date and self.is_expired:
            return 'Expirado'
        return self.get_status_display()

    # ── Area / location ──
    @property
    def total_area_ha(self):
        return round(sum(p.parcel.area_ha or 0 for p in self.plan_parcels.select_related('parcel')), 2)

    @property
    def emergency_plan_required(self):
        return self.total_area_ha >= EMERGENCY_PLAN_REQUIRED_HA

    @property
    def location(self):
        parcels = [p.parcel for p in self.plan_parcels.select_related('parcel')]
        uniq = lambda vals: sorted({v for v in vals if v})
        freguesias = uniq(f.strip() for p in parcels for f in (p.freguesia or '').split(';'))
        return {'concelhos': uniq(p.concelho for p in parcels), 'freguesias': freguesias,
                'distritos': uniq(p.distrito for p in parcels)}

    def seasons(self):
        """Burning seasons (October → May) covered by the validity period, e.g. '2026-2027'."""
        first = self.validity_start.year - (1 if self.validity_start.month < 10 else 0)
        last = self.validity_end.year - (1 if self.validity_end.month < 10 else 0)
        return [f'{y}-{y + 1}' for y in range(first, last + 1)]

    @property
    def missing_contents(self):
        labels = [('characterization', 'caracterização da área'), ('fire_history', 'história do fogo'),
                  ('dfci_infrastructure', 'infraestruturas de DFCI'), ('objectives', 'objetivos específicos'),
                  ('means', 'meios humanos e materiais')]
        missing = [label for f, label in labels if not getattr(self, f).strip()]
        if self.emergency_plan_required and not self.emergency_plan.strip():
            missing.append(f'plano de emergência (obrigatório a partir de {EMERGENCY_PLAN_REQUIRED_HA} ha)')
        if not self.plan_parcels.exists():
            missing.append('parcelas')
        return missing


class PFCParcel(models.Model):
    """A parcel of the PFC with its burning prescription (Anexo 3 — quadro de identificação das parcelas)."""
    IGNITION = [('contra_vento', 'Contra o vento / descendente'), ('linhas', 'Por linhas sucessivas'),
                ('perimetral', 'Perimetral'), ('flanco', 'De flanco'), ('pontos', 'Por pontos'), ('outra', 'Outra')]
    TYPE = [('mato', 'Matos'), ('povoamento', 'Povoamento')]
    SLOPE = [('0-10', '0–10 %'), ('10-25', '10–25 %'), ('>25', '> 25 %')]
    LOAD = [('baixa', '< 12 t/ha'), ('alta', '≥ 12 t/ha')]

    pfc        = models.ForeignKey(PFC, on_delete=models.CASCADE, related_name='plan_parcels')
    parcel     = models.ForeignKey(FireParcel, on_delete=models.PROTECT, related_name='pfc_entries')
    number     = models.PositiveIntegerField('n.º da parcela no PFC')
    season     = models.CharField('época de queima', max_length=9, blank=True, default='')
    occupation = models.TextField('ocupação (espécies, %, idade/altura)', blank=True, default='')
    objective  = models.CharField('objetivo', max_length=200, blank=True, default='')

    # Prescription (min–max)
    dry_days_min = models.PositiveSmallIntegerField('dias sem chuva (mín.)', null=True, blank=True)
    dry_days_max = models.PositiveSmallIntegerField('dias sem chuva (máx.)', null=True, blank=True)
    temp_min   = models.FloatField('temperatura mín. (°C)', null=True, blank=True)
    temp_max   = models.FloatField('temperatura máx. (°C)', null=True, blank=True)
    rh_min     = models.FloatField('humidade relativa mín. (%)', null=True, blank=True)
    rh_max     = models.FloatField('humidade relativa máx. (%)', null=True, blank=True)
    fuel_moisture = models.FloatField('humidade do combustível (%)', null=True, blank=True)
    litter_moisture_min = models.FloatField('humidade da folhada mín. (%)', null=True, blank=True)
    litter_moisture_max = models.FloatField('humidade da folhada máx. (%)', null=True, blank=True)
    wind_min   = models.FloatField('vento mín. (km/h)', null=True, blank=True)
    wind_max   = models.FloatField('vento máx. (km/h)', null=True, blank=True)
    spread_min = models.FloatField('velocidade de propagação mín. (m/min)', null=True, blank=True)
    spread_max = models.FloatField('velocidade de propagação máx. (m/min)', null=True, blank=True)
    flame_min  = models.FloatField('comprimento de chama mín. (m)', null=True, blank=True)
    flame_max  = models.FloatField('comprimento de chama máx. (m)', null=True, blank=True)
    ignition   = models.CharField('técnica de ignição', max_length=20, choices=IGNITION, blank=True, default='')

    # Means
    n_tecnicos    = models.PositiveSmallIntegerField('n.º de técnicos FC', null=True, blank=True)
    n_operacionais = models.PositiveSmallIntegerField('n.º de operacionais de queima', null=True, blank=True)
    n_equipas     = models.PositiveSmallIntegerField('n.º de equipas de apoio', null=True, blank=True)
    n_elementos   = models.PositiveSmallIntegerField('n.º de elementos de apoio', null=True, blank=True)
    n_vfci        = models.PositiveSmallIntegerField('n.º de VFCI', null=True, blank=True)

    # CAOF cost inputs (pre-filled from the parcel and its evaluation)
    cost_type  = models.CharField('tipo (custo)', max_length=12, choices=TYPE, default='mato')
    cost_slope = models.CharField('declive (custo)', max_length=6, choices=SLOPE, default='0-10')
    cost_load  = models.CharField('carga de combustível (custo)', max_length=6, choices=LOAD, default='baixa')

    class Meta:
        ordering = ['number']
        unique_together = [('pfc', 'parcel'), ('pfc', 'number')]
        verbose_name = 'Parcela do PFC'

    def __str__(self):
        return f'{self.number} — {self.parcel}'

    @property
    def prescription_rows(self):
        """[(label, 'min – max', unit)] for the filled prescription items."""
        def rng(a, b):
            if a is None and b is None:
                return None
            fmt = lambda v: f'{v:g}' if v is not None else '…'
            return f'{fmt(a)} – {fmt(b)}'
        rows = [('Dias sem chuva', rng(self.dry_days_min, self.dry_days_max), ''),
                ('Temperatura', rng(self.temp_min, self.temp_max), '°C'),
                ('Humidade relativa', rng(self.rh_min, self.rh_max), '%'),
                ('Humidade do combustível', f'{self.fuel_moisture:g}' if self.fuel_moisture is not None else None, '%'),
                ('Humidade da folhada', rng(self.litter_moisture_min, self.litter_moisture_max), '%'),
                ('Velocidade do vento', rng(self.wind_min, self.wind_max), 'km/h'),
                ('Velocidade de propagação', rng(self.spread_min, self.spread_max), 'm/min'),
                ('Comprimento de chama', rng(self.flame_min, self.flame_max), 'm')]
        return [(label, value, unit) for label, value, unit in rows if value]


class CostSettings(models.Model):
    """Single row with the CAOF / ICNF reference values (editable in the admin)."""
    jorna_eur        = models.DecimalField('valor da jorna CAOF (€)', max_digits=8, decimal_places=2, default=127.99)
    base_jornas      = models.FloatField('jornas/ha nas condições mais fáceis', default=1)
    slope_mid_jornas = models.FloatField('+ jornas com declive 10–25 %', default=1)
    slope_high_jornas = models.FloatField('+ jornas com declive > 25 %', default=2)
    area_mid_jornas  = models.FloatField('+ jornas com área intermédia', default=0.5)
    area_small_jornas = models.FloatField('+ jornas com área < 2 ha', default=1)
    load_high_jornas = models.FloatField('+ jornas com carga ≥ 12 t/ha (povoamentos)', default=1)
    max_jornas_mato  = models.FloatField('máximo de jornas/ha em matos', default=4)
    max_jornas_povoamento = models.FloatField('máximo de jornas/ha em povoamentos', default=5)
    large_area_mato_ha = models.FloatField('área "grande" em matos (ha)', default=6)
    large_area_povoamento_ha = models.FloatField('área "grande" em povoamentos (ha)', default=4)
    small_area_ha    = models.FloatField('área "pequena" (ha)', default=2)
    plan_jornas      = models.FloatField('jornas para elaborar o plano (por PFC)', default=2)
    strip_eur_per_m  = models.DecimalField('custo da faixa de contenção (€/m)', max_digits=6, decimal_places=2,
                                           default=0.30)
    strip_fraction   = models.FloatField('fração do perímetro a precisar de faixa nova', default=0.5)
    support_mato_eur_ha = models.DecimalField('apoio ICNF matos (€/ha)', max_digits=8, decimal_places=2, default=304)
    support_povoamento_eur_ha = models.DecimalField('apoio ICNF povoamentos (€/ha)', max_digits=8, decimal_places=2,
                                                    default=365)
    source_note      = models.CharField('fonte', max_length=200, blank=True,
                                        default='CAOF, Matriz de Beneficiação 2026; apoio ICNF 2026')

    class Meta:
        verbose_name = 'Valores de referência de custos'
        verbose_name_plural = 'Valores de referência de custos'

    def __str__(self):
        return 'Valores de referência de custos (CAOF / ICNF)'

    @classmethod
    def current(cls):
        obj = cls.objects.first()
        if obj is None:
            obj = cls.objects.create()
            obj.refresh_from_db()   # decimal defaults come back as Decimal
        return obj
