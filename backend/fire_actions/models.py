from django.conf import settings
from django.contrib.gis.db import models as gis_models
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
    image      = models.ImageField(upload_to='bp_photos/')
    caption    = models.CharField(max_length=200, blank=True)
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
    created_at      = models.DateTimeField(auto_now_add=True)
    history         = HistoricalRecords(m2m_fields=[operatives])

    class Meta:
        ordering = ['-execution_date']
        verbose_name = 'Plano de Queima'
        verbose_name_plural = 'Planos de Queima'

    def __str__(self):
        return f"Plano de Queima — {self.pre_plan.name} ({self.execution_date})"
