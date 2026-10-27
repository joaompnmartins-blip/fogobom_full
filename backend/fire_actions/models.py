from django.conf import settings
from django.contrib.gis.db import models as gis_models
from decimal import Decimal

from django.db import models
from simple_history.models import HistoricalRecords
from parcelas.models import FireParcel
from operatives.models import Operative


class FireAction(models.Model):
    """A burning action (fogo controlado or queimada): announced, prepared, executed."""
    STATUS_PREVISTA   = 'prevista'
    STATUS_CONFIRMADA = 'confirmada'
    STATUS_ADIADA     = 'adiada'
    STATUS_CANCELADA  = 'cancelada'
    STATUS_REALIZADA  = 'realizada'
    STATUS_CHOICES = [
        (STATUS_PREVISTA,   'Prevista'),
        (STATUS_CONFIRMADA, 'Confirmada'),
        (STATUS_ADIADA,     'Adiada'),
        (STATUS_CANCELADA,  'Cancelada'),
        (STATUS_REALIZADA,  'Realizada'),
    ]
    OPEN_STATUSES = (STATUS_PREVISTA, STATUS_CONFIRMADA, STATUS_ADIADA)

    TYPE_FOGO_CONTROLADO = 'fogo_controlado'
    TYPE_QUEIMADA        = 'queimada'
    TYPE_CHOICES = [(TYPE_FOGO_CONTROLADO, 'Fogo controlado'), (TYPE_QUEIMADA, 'Queimada')]
    QUEIMADA_PURPOSE = [('pastagens', 'Renovação de pastagens'), ('restolho', 'Eliminação de restolho'),
                        ('sobrantes', 'Eliminação de sobrantes cortados (não amontoados)')]
    OBJECTIVES = [('prevencao', 'Prevenção'), ('silvicola', 'Silvícola'), ('pastoreio', 'Pastoreio'),
                  ('cinegetico', 'Cinegético'), ('ecologico', 'Ecológico'), ('fitossanitario', 'Fitossanitário'),
                  ('agricola', 'Agrícola'), ('outro', 'Outro')]
    PROBABILITY = [('alta', 'Alta'), ('media', 'Média'), ('baixa', 'Baixa')]
    LEGAL_MODES = [('comunicacao_previa', 'Comunicação prévia ao município (técnico credenciado)'),
                   ('autorizacao', 'Autorização do município')]

    name           = models.CharField('nome da ação', max_length=200)
    action_type    = models.CharField('tipo', max_length=20, choices=TYPE_CHOICES, default=TYPE_QUEIMADA)
    training       = models.BooleanField('ação de formação', default=False)
    purpose        = models.CharField('finalidade (queimada)', max_length=20, choices=QUEIMADA_PURPOSE,
                                      blank=True, default='')
    objectives     = models.CharField('objetivos', max_length=200, blank=True, default='')  # comma-separated
    responsible    = models.CharField(max_length=200, blank=True, default='')  # legacy free text
    responsible_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                         blank=True, related_name='responsible_actions',
                                         verbose_name='técnico responsável')
    created_by     = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                       blank=True, related_name='created_actions')
    scheduled_date = models.DateField('data prevista')
    alt_date_1     = models.DateField('data alternativa 1', null=True, blank=True)
    alt_date_2     = models.DateField('data alternativa 2', null=True, blank=True)
    start_time     = models.TimeField('hora de início', null=True, blank=True)
    meeting_point  = gis_models.PointField('ponto de encontro', srid=4326, null=True, blank=True)
    meeting_notes  = models.CharField('indicações do ponto de encontro', max_length=300, blank=True, default='')
    requirements   = models.TextField('o que levar / requisitos', blank=True, default='')
    slots          = models.PositiveSmallIntegerField('vagas para participantes', null=True, blank=True)
    probability_manual = models.CharField('probabilidade (definida pelo técnico)', max_length=10,
                                          choices=PROBABILITY, blank=True, default='')
    notes          = models.TextField('notas', blank=True, default='')
    parcels        = models.ManyToManyField(FireParcel, related_name='fire_actions')
    status         = models.CharField('estado', max_length=20, choices=STATUS_CHOICES, default=STATUS_PREVISTA)
    status_reason  = models.CharField('motivo (adiamento / cancelamento)', max_length=300, blank=True, default='')
    execution_date = models.DateField(null=True, blank=True)

    # Legal framework (DL 82/2021 art. 63.º / 65.º; Regulamento do Fogo Técnico)
    legal_mode     = models.CharField('enquadramento municipal', max_length=20, choices=LEGAL_MODES,
                                      blank=True, default='')
    legal_reference = models.CharField('n.º / referência da comunicação ou autorização', max_length=100,
                                       blank=True, default='')
    legal_date     = models.DateField('data da comunicação ou autorização', null=True, blank=True)
    legal_document = models.FileField('documento', upload_to='action_documents/', null=True, blank=True)
    accompaniment  = models.CharField('acompanhamento (se não houver técnico credenciado)', max_length=200,
                                      blank=True, default='')
    pfc            = models.ForeignKey('pfc.PFC', on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='actions', verbose_name='PFC')
    pfc_reference  = models.CharField('n.º do PFC (se não estiver na plataforma)', max_length=50, blank=True,
                                      default='')

    # Communications to civil protection (start / end of the operation)
    comm_start_at  = models.DateTimeField('início comunicado em', null=True, blank=True)
    comm_start_by  = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                       blank=True, related_name='+')
    comm_end_at    = models.DateTimeField('fim comunicado em', null=True, blank=True)
    comm_end_by    = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                       blank=True, related_name='+')

    created_at     = models.DateTimeField(auto_now_add=True)
    history        = HistoricalRecords(m2m_fields=[parcels])

    class Meta:
        ordering = ['-scheduled_date']
        verbose_name = 'Ação'
        verbose_name_plural = 'Ações'

    def __str__(self):
        return f"{self.name} ({self.scheduled_date})"

    @property
    def is_open(self):
        return self.status in self.OPEN_STATUSES

    @property
    def objectives_list(self):
        return [c for c in self.objectives.split(',') if c]

    @property
    def objectives_display(self):
        labels = dict(self.OBJECTIVES)
        return ', '.join(labels.get(c, c) for c in self.objectives_list)

    @property
    def legal_missing(self):
        """What is still missing from the legal framework (empty list = complete)."""
        if self.action_type == self.TYPE_FOGO_CONTROLADO:
            if self.pfc_id:
                return [] if self.pfc.in_force_on(self.scheduled_date) else \
                    [f'PFC {self.pfc.number} em vigor na data da ação']
            return [] if self.pfc_reference else ['n.º do PFC aprovado']
        missing = []
        if not self.legal_mode:
            missing.append('comunicação prévia ou autorização do município')
        elif not (self.legal_reference or self.legal_date or self.legal_document):
            missing.append('referência/data da comunicação ou autorização')
        if self.legal_mode == 'autorizacao' and not self.accompaniment and not self.responsible_user_id:
            missing.append('acompanhamento (técnico credenciado, bombeiros, sapadores…)')
        return missing

    def participants(self):
        return self.participations.exclude(intent=Participation.INTENT_NAO)

    def confirmed_participants(self):
        return self.participations.filter(confirmed=True)


class Participation(models.Model):
    """A user's sign-up to an announced action."""
    INTENT_VOU    = 'vou'
    INTENT_TALVEZ = 'talvez'
    INTENT_NAO    = 'nao'
    INTENTS = [(INTENT_VOU, 'Vou participar'), (INTENT_TALVEZ, 'Talvez'), (INTENT_NAO, 'Não vou')]
    ROLES = [('', '—'), ('responsavel', 'Responsável de queima'), ('ignicao', 'Ignição (pinga-lume)'),
             ('seguranca', 'Segurança'), ('vigia', 'Vigia'), ('apoio', 'Apoio'), ('observador', 'Observador / formação')]

    action    = models.ForeignKey(FireAction, on_delete=models.CASCADE, related_name='participations')
    user      = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='participations')
    intent    = models.CharField('intenção', max_length=10, choices=INTENTS, default=INTENT_VOU)
    role      = models.CharField('função pretendida', max_length=20, choices=ROLES, blank=True, default='')
    note      = models.CharField('nota', max_length=200, blank=True, default='')
    confirmed = models.BooleanField('confirmado pelo técnico', null=True, blank=True)  # None = por confirmar
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('action', 'user')]
        ordering = ['created_at']

    def __str__(self):
        return f'{self.user} → {self.action}'


class BurningPlanPhoto(models.Model):
    MOMENTS = [('antes', 'Antes da queima'), ('durante', 'Durante a queima'), ('depois', 'Depois da queima')]
    image      = models.ImageField(upload_to='bp_photos/')
    caption    = models.CharField('legenda', max_length=200, blank=True)
    parcel     = models.ForeignKey(FireParcel, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='execution_photos', verbose_name='parcela')
    moment     = models.CharField('momento', max_length=10, choices=MOMENTS, blank=True, default='')
    taken_on   = models.DateField('data', null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Foto {self.pk}"


class PrePlanPhoto(models.Model):
    fire_action = models.ForeignKey('BurningPlan', on_delete=models.CASCADE,
                                    related_name='preplan_photos', null=True, blank=True)
    image       = models.ImageField(upload_to='preplan_photos/')
    caption     = models.CharField(max_length=200, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)


class BurningPlan(models.Model):
    FIRE_CONDUCT_CHOICES = [
        ('1', '1 — Contra o vento / contra o declive'),
        ('2', '2 — Por linhas sucessivas'),
        ('3', '3 — Perimetral'),
        ('4', '4 — De flanco'),
        ('5', '5 — Outro'),
    ]

    pre_plan       = models.OneToOneField(FireAction, on_delete=models.PROTECT,
                                          related_name='burningplan')
    execution_date = models.DateField()

    operatives = models.ManyToManyField(Operative, related_name='burning_plans', blank=True)
    num_men    = models.IntegerField(null=True, blank=True)
    vehicles   = models.TextField(blank=True, default='{}')  # JSON

    problems   = models.TextField(blank=True, default='')

    fuel_superficial = models.CharField(max_length=20, blank=True, default='')
    fuel_manta_f     = models.CharField(max_length=20, blank=True, default='')
    fuel_manta_h     = models.CharField(max_length=20, blank=True, default='')

    weather_state       = models.CharField(max_length=80, blank=True, default='')
    wind_speed_beaufort = models.CharField(max_length=10, blank=True, default='')
    wind_speed_kmh      = models.CharField(max_length=20, blank=True, default='')
    wind_direction      = models.CharField(max_length=20, blank=True, default='')

    fire_conduct       = models.CharField(max_length=2, choices=FIRE_CONDUCT_CHOICES,
                                          blank=True, default='')
    fire_conduct_other = models.TextField(blank=True, default='')

    burn_effects    = models.TextField(blank=True, default='')
    burn_efficiency = models.TextField(blank=True, default='')
    notes           = models.TextField(blank=True, default='')

    photos          = models.ManyToManyField(BurningPlanPhoto, blank=True)
    tactical_schema = models.ImageField(upload_to='tactical_schemas/', null=True, blank=True)

    # Fire escape that required complementary teams (Regulamento, art. 15.º n.º 2 b) ii) and n.º 5)
    incident             = models.BooleanField('o fogo ultrapassou os limites e originou um incêndio', default=False)
    incident_date        = models.DateField('data do incidente', null=True, blank=True)
    incident_circumstances = models.TextField('circunstâncias', blank=True, default='')
    incident_entities    = models.TextField('entidades contactadas', blank=True, default='')
    incident_teams       = models.TextField('equipas complementares que intervieram', blank=True, default='')
    incident_commander   = models.CharField('responsável pelas operações de combate', max_length=200, blank=True,
                                            default='')
    incident_strategy    = models.TextField('estratégia adotada para o controlo do fogo', blank=True, default='')
    incident_area_ha     = models.FloatField('área afetada (ha)', null=True, blank=True)
    incident_damages     = models.TextField('possíveis prejuízos', blank=True, default='')

    # Submission to ICNF (Regulamento, art. 14.º n.os 3 a 5)
    poq_sent_on    = models.DateField('POQ-Execução enviado ao ICNF em', null=True, blank=True)
    impact_sent_on = models.DateField('POQ-Impacto enviado ao ICNF em', null=True, blank=True)

    created_at      = models.DateTimeField(auto_now_add=True)
    history         = HistoricalRecords(m2m_fields=[operatives])

    class Meta:
        ordering = ['-execution_date']
        verbose_name = 'Execução (POQ)'
        verbose_name_plural = 'Execuções (POQ)'

    def __str__(self):
        return f"Execução — {self.pre_plan.name} ({self.execution_date})"


# ── POQ-Execução: one row per parcel and date ───────────────────────────────

WEATHER_CODES = [(0, '0 — limpo (< 10 %)'), (1, '1 — nuvens dispersas (10–50 %)'), (2, '2 — bastante nublado (60–90 %)'),
                 (3, '3 — muito nublado (> 90 %)'), (4, '4 — nevoeiro'), (5, '5 — chuviscos'), (6, '6 — chuva'),
                 (7, '7 — neve ou granizo'), (8, '8 — aguaceiros')]
WIND_DIRECTIONS = [(d, d) for d in ('N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW')] + [('V', 'V — variável')]
CONDUCT = [(1, '1 — contra o vento, contra o declive'), (2, '2 — por linhas sucessivas'), (3, '3 — perimetral'),
           (4, '4 — de flanco'), (5, '5 — outro')]
RATINGS = [(1, 'Muito insatisfatória'), (2, 'Insatisfatória'), (3, 'Razoável'), (4, 'Boa'), (5, 'Muito boa')]


class ParcelExecution(models.Model):
    FUEL_METHODS = [('A', 'A — amostra'), ('B', 'B — tabela do guia'), ('C', 'C — BEHAVE'),
                    ('D', 'D — índice do Sistema Canadiano')]
    FORMATIONS = [('mato', 'Mato'), ('pov', 'Povoamento'), ('res', 'Resíduos')]
    PROBLEMS = [('ignicao', 'Dificuldade de ignição'), ('rescaldo', 'Necessidade de rescaldo'),
                ('organizacao', 'Organização deficiente'), ('meios_humanos', 'Meios humanos insuficientes'),
                ('equipamento', 'Equipamento insuficiente'), ('intenso', 'Fogo demasiado intenso'),
                ('fumo', 'Deficiente dispersão do fumo'), ('seguranca', 'Deficiente segurança dos operadores'),
                ('fuga', 'Fuga do fogo')]

    plan       = models.ForeignKey(BurningPlan, on_delete=models.CASCADE, related_name='executions')
    parcel     = models.ForeignKey(FireParcel, on_delete=models.PROTECT, related_name='executions',
                                   verbose_name='parcela')
    date       = models.DateField('data')
    start_time = models.TimeField('início', null=True, blank=True)
    end_time   = models.TimeField('fim', null=True, blank=True)
    area_treated_ha = models.FloatField('área tratada (ha)', null=True, blank=True)
    formation  = models.CharField('formação (registo ICNF)', max_length=4, choices=FORMATIONS, default='mato')

    # Means
    n_tecnicos = models.PositiveSmallIntegerField('técnicos (n.º)', null=True, blank=True)
    n_vlci     = models.PositiveSmallIntegerField('VLCI (< 500 l)', null=True, blank=True)
    n_vfci     = models.PositiveSmallIntegerField('VFCI', null=True, blank=True)
    vfci_capacity_l = models.PositiveIntegerField('capacidade do VFCI (l)', null=True, blank=True)
    n_men      = models.PositiveSmallIntegerField('homens', null=True, blank=True)

    # Fine dead fuel moisture
    fuel_method      = models.CharField('metodologia', max_length=1, choices=FUEL_METHODS, blank=True, default='')
    fuel_superficial = models.CharField('superficial (% / classe A–E / FFMC)', max_length=20, blank=True, default='')
    fuel_manta_f     = models.CharField('manta morta F (% / classe / DMC)', max_length=20, blank=True, default='')
    fuel_manta_h     = models.CharField('manta morta H (% / classe / DMC)', max_length=20, blank=True, default='')
    litter_thickness_cm = models.FloatField('espessura da manta morta (cm)', null=True, blank=True)
    dry_days   = models.PositiveSmallIntegerField('n.º de dias sem chuva', null=True, blank=True)
    fwi  = models.FloatField('FWI', null=True, blank=True)
    isi  = models.FloatField('ISI', null=True, blank=True)
    ffmc = models.FloatField('FFMC', null=True, blank=True)
    bui  = models.FloatField('BUI', null=True, blank=True)
    dmc  = models.FloatField('DMC', null=True, blank=True)
    dc   = models.FloatField('DC', null=True, blank=True)

    # Operation
    ignition_techniques = models.TextField('técnica(s) de ignição utilizada(s)', blank=True, default='')
    operation_notes = models.TextField('descrição operacional (faixas, progressão do fogo, vento, linha de ignição…)',
                                       blank=True, default='')
    problems   = models.CharField('problemas operacionais', max_length=200, blank=True, default='')  # comma-separated
    problems_description = models.TextField('descrição dos problemas', blank=True, default='')
    schema     = models.ImageField('esquema de condução', upload_to='execution_schemas/', null=True, blank=True)

    # Immediate effects
    eff_veg_area_pct    = models.FloatField('vegetação — área percorrida (%)', null=True, blank=True)
    eff_crowns_pct      = models.FloatField('vegetação — copas consumidas (%)', null=True, blank=True)
    eff_diameter_mm     = models.FloatField('vegetação — diâmetro calcinado (mm)', null=True, blank=True)
    eff_litter_area_pct = models.FloatField('manta morta — área percorrida (%)', null=True, blank=True)
    eff_litter_reduction_pct = models.FloatField('manta morta — redução da espessura (%)', null=True, blank=True)

    # Efficacy
    rating_objectives = models.PositiveSmallIntegerField('resposta aos objetivos', choices=RATINGS, null=True, blank=True)
    rating_fuel       = models.PositiveSmallIntegerField('redução de combustível', choices=RATINGS, null=True, blank=True)
    rating_weather    = models.PositiveSmallIntegerField('condições meteorológicas', choices=RATINGS, null=True,
                                                         blank=True)
    rating_why        = models.TextField('porquê?', blank=True, default='')

    # Validation of the action for the livro de campo (Regulamento, art. 7.º n.º 4)
    VALIDATOR_ROLES = [('proprietario', 'Proprietário'), ('representante', 'Representante do proprietário'),
                       ('proponente', 'Proponente do PFC'), ('icnf', 'ICNF')]
    validator_role = models.CharField('quem valida a ação', max_length=15, choices=VALIDATOR_ROLES, blank=True,
                                      default='')
    validator_name = models.CharField('nome de quem valida', max_length=120, blank=True, default='')
    validated_on   = models.DateField('data da validação', null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    history    = HistoricalRecords()

    class Meta:
        ordering = ['date', 'parcel__name']
        unique_together = [('plan', 'parcel', 'date')]
        verbose_name = 'Execução de parcela'
        verbose_name_plural = 'Execuções de parcela'

    def __str__(self):
        return f'{self.parcel} — {self.date:%d/%m/%Y}'

    @property
    def problems_list(self):
        return [c for c in self.problems.split(',') if c]

    @property
    def problems_display(self):
        labels = dict(self.PROBLEMS)
        return ', '.join(labels.get(c, c) for c in self.problems_list)

    @property
    def duration_hours(self):
        from datetime import datetime as dt
        if not (self.start_time and self.end_time):
            return None
        delta = dt.combine(self.date, self.end_time) - dt.combine(self.date, self.start_time)
        return round(delta.total_seconds() / 3600, 2) if delta.total_seconds() > 0 else None

    @property
    def cost_total(self):
        return sum((line.amount for line in self.cost_lines.all()), Decimal('0'))


class ExecutionMember(models.Model):
    """Technician / operative involved (POQ-Execução: técnicos envolvidos na queima)."""
    FUNCTIONS = [('coordenacao', 'Coordenação da queima'), ('responsavel_linha', 'Responsável de linha de queima'),
                 ('ignicao', 'Ignição (pinga-lume)'), ('vigilancia', 'Vigilância'), ('seguranca', 'Segurança'),
                 ('apoio', 'Apoio'), ('formacao', 'Em formação'), ('todas', 'Todas as funções')]
    execution = models.ForeignKey(ParcelExecution, on_delete=models.CASCADE, related_name='members')
    operative = models.ForeignKey(Operative, on_delete=models.PROTECT, related_name='execution_roles',
                                  verbose_name='técnico / operacional')
    function  = models.CharField('função', max_length=20, choices=FUNCTIONS, blank=True, default='')
    # Livro de campo
    hours     = models.FloatField('horas', null=True, blank=True)   # empty: duration of the execution
    book_page = models.CharField('folha do livro de campo', max_length=10, blank=True, default='')
    validated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name='validated_participations',
                                     verbose_name='validada pelo técnico')
    validated_at = models.DateTimeField('validada em', null=True, blank=True)

    class Meta:
        unique_together = [('execution', 'operative')]
        ordering = ['id']

    @property
    def effective_hours(self):
        return self.hours if self.hours is not None else self.execution.duration_hours


class WeatherReading(models.Model):
    """Observed weather (start, end and whenever behaviour changes) and fire behaviour."""
    execution  = models.ForeignKey(ParcelExecution, on_delete=models.CASCADE, related_name='readings')
    time       = models.TimeField('hora')
    temp       = models.FloatField('temperatura (°C)', null=True, blank=True)
    rh         = models.FloatField('humidade relativa (%)', null=True, blank=True)
    weather    = models.PositiveSmallIntegerField('estado do tempo', choices=WEATHER_CODES, null=True, blank=True)
    wind_bft   = models.PositiveSmallIntegerField('vento (Beaufort)', null=True, blank=True)
    wind_kmh   = models.FloatField('vento (km/h)', null=True, blank=True)
    wind_dir   = models.CharField('direção do vento', max_length=2, choices=WIND_DIRECTIONS, blank=True, default='')
    conduct    = models.PositiveSmallIntegerField('condução', choices=CONDUCT, null=True, blank=True)
    conduct_other = models.CharField('condução — outro', max_length=200, blank=True, default='')
    flame_length_m = models.FloatField('comprimento / altura de chama (m)', null=True, blank=True)
    flame_angle = models.FloatField('ângulo da chama (°)', null=True, blank=True)
    spread_m_min = models.FloatField('velocidade de propagação (m/min)', null=True, blank=True)

    class Meta:
        ordering = ['time']


class SafetyStrip(models.Model):
    SIDES = [('cima', 'Cima'), ('baixo', 'Baixo'), ('lado1', 'Lado 1'), ('lado2', 'Lado 2')]
    MEANS = [(1, '1 — ferramenta manual'), (2, '2 — motoroçadora'), (3, '3 — bulldozer, corta-matos'), (4, '4 — grade'),
             (5, '5 — água'), (6, '6 — fogo'), (7, '7 — estrada, pista'), (8, '8 — caminho'), (9, '9 — rocha'),
             (10, '10 — curso de água'), (11, '11 — vegetação descontínua ou pouco inflamável'),
             (12, '12 — vegetação húmida')]
    execution = models.ForeignKey(ParcelExecution, on_delete=models.CASCADE, related_name='strips')
    side      = models.CharField('lado', max_length=6, choices=SIDES)
    means     = models.PositiveSmallIntegerField('meio', choices=MEANS, null=True, blank=True)
    width_m   = models.FloatField('largura (m)', null=True, blank=True)
    time_spent = models.CharField('tempo de execução (h:min)', max_length=10, blank=True, default='')

    class Meta:
        unique_together = [('execution', 'side')]
        ordering = ['id']


class CostLine(models.Model):
    """Real cost (POQ-Execução: avaliação económica)."""
    CATEGORIES = [('pessoal', 'Pessoal'), ('maquinas', 'Máquinas'), ('viaturas', 'Viaturas (km)'),
                  ('combustivel', 'Combustível (l)'), ('outro', 'Outro')]
    execution   = models.ForeignKey(ParcelExecution, on_delete=models.CASCADE, related_name='cost_lines')
    category    = models.CharField('categoria', max_length=12, choices=CATEGORIES, default='pessoal')
    description = models.CharField('tipo (pessoal / máquina / …)', max_length=120, blank=True, default='')
    qty_burn    = models.FloatField('queima (h, km, l)', null=True, blank=True)
    qty_extinction = models.FloatField('extinção / vigilância (h)', null=True, blank=True)
    unit_price  = models.DecimalField('custo unitário (€)', max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ['id']

    @property
    def quantity(self):
        return (self.qty_burn or 0) + (self.qty_extinction or 0)

    @property
    def amount(self):
        return (Decimal(str(self.quantity)) * (self.unit_price or Decimal('0'))).quantize(Decimal('0.01'))
