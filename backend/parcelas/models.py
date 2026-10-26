from django.conf import settings
from django.contrib.gis.db import models
from simple_history.models import HistoricalRecords


class Freguesia(models.Model):
    """Official administrative boundaries (CAOP, DGT), loaded with `manage.py load_caop`."""
    dicofre   = models.CharField('código DICOFRE', max_length=8, unique=True)
    freguesia = models.CharField(max_length=200)
    concelho  = models.CharField(max_length=100, db_index=True)
    distrito  = models.CharField(max_length=100)
    nuts3     = models.CharField('NUTS III', max_length=100, blank=True, default='')
    geom      = models.MultiPolygonField(srid=3763)

    class Meta:
        ordering = ['concelho', 'freguesia']
        verbose_name = 'Freguesia (CAOP)'
        verbose_name_plural = 'Freguesias (CAOP)'

    def __str__(self):
        return f'{self.freguesia} ({self.concelho})'


class FireParcel(models.Model):
    STATUS_PROPOSTA     = 'proposta'
    STATUS_AVALIACAO    = 'em_avaliacao'
    STATUS_APTA         = 'apta'
    STATUS_CONDICIONADA = 'apta_condicionantes'
    STATUS_NAO_APTA     = 'nao_apta'
    STATUS_CHOICES = [
        (STATUS_PROPOSTA,     'Proposta'),
        (STATUS_AVALIACAO,    'Em avaliação'),
        (STATUS_APTA,         'Apta'),
        (STATUS_CONDICIONADA, 'Apta com condicionantes'),
        (STATUS_NAO_APTA,     'Não apta'),
    ]
    AVAILABLE_STATUSES = (STATUS_APTA, STATUS_CONDICIONADA)

    name = models.CharField('nome', max_length=100)
    status = models.CharField('estado', max_length=20, choices=STATUS_CHOICES, default=STATUS_PROPOSTA,
                              db_index=True)
    proposed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='proposed_parcels', verbose_name='proposta por')
    concelho  = models.CharField(max_length=100, blank=True, default='')
    freguesia = models.CharField('freguesia(s)', max_length=300, blank=True, default='')
    distrito  = models.CharField(max_length=100, blank=True, default='')
    vegetation_type = models.CharField(
        'tipologia',
        max_length=20,
        choices=[('matos', 'Matos'), ('pinhal', 'Povoamento de pinheiro'),
                 ('eucaliptal', 'Povoamento de eucalipto'), ('misto', 'Misto')],
        default='matos'
    )
    infrastructure = models.CharField(
        'infraestruturas',
        max_length=50,
        choices=[('non_existing','Inexistente'),('existing','Operacional'),('req_maintenance','Manutenção necessária'),('no_info','Sem informação')],
        default='no_info'
    )
    owner_info = models.CharField(
        'existem dados do proprietário',
        max_length=20,
        choices=[('yes','Sim'),('no','Não')],
        default='no'
    )
    resp_name  = models.CharField('responsável de contacto', max_length=100, blank=True, null=True)
    resp_email = models.EmailField('email de contacto', blank=True, null=True)
    notes      = models.TextField('observações', blank=True, default='')
    geometry   = models.PolygonField(srid=4326)
    area_ha    = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    history    = HistoricalRecords()

    class Meta:
        ordering = ['name']
        verbose_name = 'Parcela'
        verbose_name_plural = 'Parcelas'

    def __str__(self):
        return self.name

    @property
    def is_available(self):
        """Can be used in burning actions and PFC."""
        return self.status in self.AVAILABLE_STATUSES

    @property
    def latest_evaluation(self):
        return self.evaluations.order_by('-started_at').first()


class ParcelEvaluation(models.Model):
    """Field evaluation of a parcel by a credentialed technician."""
    DECISIONS = [
        (FireParcel.STATUS_APTA,         'Apta'),
        (FireParcel.STATUS_CONDICIONADA, 'Apta com condicionantes'),
        (FireParcel.STATUS_NAO_APTA,     'Não apta'),
    ]
    ASPECTS = [(a, a) for a in ('N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW')] + [('plano', 'Plano')]
    TOPOGRAPHY = [('cumeada', 'Cumeada'), ('alto_encosta', 'Alto de encosta'), ('meia_encosta', 'Meia encosta'),
                  ('baixo_encosta', 'Baixo de encosta'), ('vale', 'Vale'), ('plano', 'Plano')]
    FUEL_LOAD = [('baixa', 'Baixa (< 12 t/ha)'), ('alta', 'Alta (≥ 12 t/ha)')]
    TREATMENT = [('fogo_controlado', 'Fogo controlado'), ('queimada', 'Queimada')]
    OBJECTIVES = [('prevencao', 'Prevenção'), ('silvicola', 'Silvícola'), ('pastoreio', 'Pastoreio'),
                  ('cinegetico', 'Cinegético'), ('ecologico', 'Ecológico'), ('fitossanitario', 'Fitossanitário'),
                  ('agricola', 'Agrícola'), ('outro', 'Outro')]
    QUEIMADA_PURPOSE = [('pastagens', 'Renovação de pastagens'), ('restolho', 'Eliminação de restolho'),
                        ('sobrantes', 'Eliminação de sobrantes cortados (não amontoados)')]
    # Annex "Classificação da dificuldade da operação" (POQ-Execução): (field, label, weight)
    DIFFICULTY_ELEMENTS = [
        ('diff_escape',     'Potencial de fuga', 1),
        ('diff_risk',       'Risco', 3),
        ('diff_fuels',      'Combustíveis / comportamento do fogo', 2),
        ('diff_environment', 'Restrições ambientais', 2),
        ('diff_smoke',      'Fumo / qualidade do ar', 1),
        ('diff_ignition',   'Métodos de ignição', 2),
        ('diff_team',       'Gestão da equipa', 1),
        ('diff_objectives', 'Objetivos do tratamento', 3),
    ]

    parcel       = models.ForeignKey(FireParcel, on_delete=models.CASCADE, related_name='evaluations')
    evaluator    = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                     related_name='parcel_evaluations', verbose_name='técnico')
    started_at   = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField('concluída em', null=True, blank=True)
    visit_date   = models.DateField('data da visita ao terreno', null=True, blank=True)
    decision     = models.CharField('decisão', max_length=20, choices=DECISIONS, blank=True, default='')
    justification = models.TextField('justificação', blank=True, default='')
    conditions   = models.TextField('condicionantes', blank=True, default='')

    # Physical characterisation (altitude/slope/aspect pre-filled from the terrain model)
    altitude_m   = models.FloatField('altitude média (m)', null=True, blank=True)
    slope_pct    = models.FloatField('declive médio (%)', null=True, blank=True)
    aspect       = models.CharField('exposição', max_length=6, choices=ASPECTS, blank=True, default='')
    terrain_source = models.CharField('origem do relevo', max_length=100, blank=True, default='')
    rocks_pct    = models.PositiveSmallIntegerField('rochas (%)', null=True, blank=True)
    terraces     = models.BooleanField('terraços', null=True, blank=True)
    topography   = models.CharField('topografia', max_length=20, choices=TOPOGRAPHY, blank=True, default='')

    # Fuel
    fuel_load    = models.CharField('carga de combustível', max_length=10, choices=FUEL_LOAD, blank=True, default='')
    litter_cm    = models.FloatField('espessura da manta morta (cm)', null=True, blank=True)

    # Constraints
    access       = models.TextField('acessos', blank=True, default='')
    water_points = models.TextField('pontos de água', blank=True, default='')
    existing_strips = models.TextField('faixas de contenção existentes', blank=True, default='')
    new_strips_needed = models.BooleanField('é necessário abrir faixas', null=True, blank=True)
    buildings_nearby  = models.BooleanField('edificações próximas', null=True, blank=True)
    smoke_sensitive   = models.BooleanField('áreas sensíveis ao fumo', null=True, blank=True)
    protected_area    = models.BooleanField('habitats / áreas protegidas', null=True, blank=True)
    constraints_notes = models.TextField('outras condicionantes', blank=True, default='')

    # Proposed treatment
    recommended_type = models.CharField('tipo de ação recomendado', max_length=20, choices=TREATMENT,
                                        blank=True, default='')
    objectives   = models.CharField('objetivos', max_length=200, blank=True, default='')  # comma-separated codes
    queimada_purpose = models.CharField('finalidade (queimada)', max_length=20, choices=QUEIMADA_PURPOSE,
                                        blank=True, default='')
    prescription_notes = models.TextField('prescrição sugerida', blank=True, default='')
    include_in_pfc = models.BooleanField('deve integrar um PFC', null=True, blank=True)

    diff_escape      = models.PositiveSmallIntegerField(null=True, blank=True)
    diff_risk        = models.PositiveSmallIntegerField(null=True, blank=True)
    diff_fuels       = models.PositiveSmallIntegerField(null=True, blank=True)
    diff_environment = models.PositiveSmallIntegerField(null=True, blank=True)
    diff_smoke       = models.PositiveSmallIntegerField(null=True, blank=True)
    diff_ignition    = models.PositiveSmallIntegerField(null=True, blank=True)
    diff_team        = models.PositiveSmallIntegerField(null=True, blank=True)
    diff_objectives  = models.PositiveSmallIntegerField(null=True, blank=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ['-started_at']
        verbose_name = 'Avaliação de parcela'
        verbose_name_plural = 'Avaliações de parcelas'

    def __str__(self):
        return f'Avaliação de {self.parcel} ({self.started_at:%d/%m/%Y})'

    @property
    def is_complete(self):
        return bool(self.decision and self.completed_at)

    @property
    def objectives_list(self):
        return [c for c in self.objectives.split(',') if c]

    @property
    def objectives_display(self):
        labels = dict(self.OBJECTIVES)
        return ', '.join(labels.get(c, c) for c in self.objectives_list)

    @property
    def difficulty_total(self):
        values = [(getattr(self, f), w) for f, _, w in self.DIFFICULTY_ELEMENTS]
        if any(v is None for v, _ in values):
            return None
        return sum(v * w for v, w in values)

    @property
    def difficulty_class(self):
        total = self.difficulty_total
        if total is None:
            return ''
        return 'Fácil / simples' if total < 35 else 'Normal' if total < 55 else 'Difícil / complexa'


class EvaluationVegetation(models.Model):
    """Vegetation inventory line (species, cover, height, age)."""
    evaluation = models.ForeignKey(ParcelEvaluation, on_delete=models.CASCADE, related_name='vegetation')
    species    = models.CharField('espécie', max_length=100)
    cover_pct  = models.PositiveSmallIntegerField('coberto (%)', null=True, blank=True)
    height_m   = models.FloatField('altura (m)', null=True, blank=True)
    age_years  = models.PositiveSmallIntegerField('idade (anos)', null=True, blank=True)

    class Meta:
        ordering = ['-cover_pct', 'species']


class ParcelPhoto(models.Model):
    STAGES = [('proposta', 'Proposta'), ('avaliacao', 'Avaliação')]
    parcel      = models.ForeignKey(FireParcel, on_delete=models.CASCADE, related_name='photos')
    evaluation  = models.ForeignKey(ParcelEvaluation, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='photos')
    stage       = models.CharField(max_length=10, choices=STAGES, default='proposta')
    image       = models.ImageField(upload_to='parcel_photos/')
    caption     = models.CharField('legenda', max_length=200, blank=True, default='')
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['uploaded_at']
