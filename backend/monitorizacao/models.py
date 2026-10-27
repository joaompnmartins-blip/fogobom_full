"""Post-burn impact assessment (POQ-Impacto) and permanent monitoring of each burned parcel."""
from django.conf import settings
from django.db import models
from simple_history.models import HistoricalRecords

from fire_actions.models import ParcelExecution
from parcelas.models import FireParcel

COVER_CLASSES = [('0', '0 %'), ('<25', '< 25 %'), ('26-50', '26–50 %'), ('51-75', '51–75 %'), ('>75', '> 75 %')]


class Assessment(models.Model):
    """One field visit to a burned parcel: 1.ª fase (immediate), 2.ª fase (6 months) or annual monitoring."""
    PHASE_IMEDIATA, PHASE_6M, PHASE_ANUAL = 'imediata', '6meses', 'anual'
    PHASES = [(PHASE_IMEDIATA, '1.ª fase — avaliação imediata'), (PHASE_6M, '2.ª fase — 6 meses'),
              (PHASE_ANUAL, 'Monitorização anual')]

    execution = models.ForeignKey(ParcelExecution, on_delete=models.PROTECT, related_name='assessments',
                                  verbose_name='execução')
    phase     = models.CharField('fase', max_length=10, choices=PHASES)
    year      = models.PositiveSmallIntegerField('ano de monitorização', default=0)   # 1, 2, … for annual visits
    date      = models.DateField('data da visita')
    observer  = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name='assessments', verbose_name='técnico')

    # Manta morta
    litter_area    = models.CharField('manta morta — área percorrida', max_length=6, choices=COVER_CLASSES,
                                      blank=True, default='')
    litter_red_l   = models.CharField('redução da espessura — L (cm ou %)', max_length=10, blank=True, default='')
    litter_red_f   = models.CharField('redução da espessura — F (cm ou %)', max_length=10, blank=True, default='')
    litter_red_h   = models.CharField('redução da espessura — H (cm ou %)', max_length=10, blank=True, default='')
    soil_exposed_pct = models.FloatField('exposição do solo mineral (%)', null=True, blank=True)
    soil_movement  = models.BooleanField('sinais de erosão — movimento de solo', null=True, blank=True)
    gullying       = models.BooleanField('sinais de erosão — ravinação', null=True, blank=True)

    # Herbáceas
    herb_area          = models.CharField('herbáceas — área percorrida', max_length=6, choices=COVER_CLASSES,
                                          blank=True, default='')
    herb_resprout_pct  = models.FloatField('herbáceas — rebentamento (% da área)', null=True, blank=True)
    herb_height_cm     = models.FloatField('herbáceas — altura média (cm)', null=True, blank=True)
    herb_germination   = models.BooleanField('herbáceas — germinação', null=True, blank=True)

    # Arbustos
    shrub_area         = models.CharField('arbustos — área percorrida', max_length=6, choices=COVER_CLASSES,
                                          blank=True, default='')
    shrub_crown_consumed_pct = models.FloatField('arbustos — copa consumida (%)', null=True, blank=True)
    shrub_resprout     = models.BooleanField('arbustos — rebentamento', null=True, blank=True)
    shrub_dead_crowns_pct = models.FloatField('arbustos — copas mortas (%)', null=True, blank=True)
    shrub_resprout_pct = models.FloatField('arbustos — rebentamento (% da área)', null=True, blank=True)
    shrub_height_cm    = models.FloatField('arbustos — altura média (cm)', null=True, blank=True)
    shrub_germination  = models.BooleanField('arbustos — germinação', null=True, blank=True)

    # Árvores
    tree_scorch_pct      = models.FloatField('árvores — crestamento da copa (% da copa)', null=True, blank=True)
    tree_scorch_height_m = models.FloatField('árvores — altura de crestamento (m)', null=True, blank=True)
    tree_bole_min_m      = models.FloatField('árvores — altura de tronco queimado, mínimo (m)', null=True, blank=True)
    tree_bole_max_m      = models.FloatField('árvores — altura de tronco queimado, máximo (m)', null=True, blank=True)
    tree_resin           = models.BooleanField('árvores — derrame de resina', null=True, blank=True)
    tree_mortality_pct   = models.FloatField('árvores — mortalidade (%)', null=True, blank=True)
    tree_mortality_dbh_cm = models.FloatField('mortalidade em árvores com DAP até (cm)', null=True, blank=True)
    tree_bark_beetles    = models.BooleanField('árvores — mortalidade por escolitídeos', null=True, blank=True)
    tree_regeneration    = models.BooleanField('árvores — regeneração', null=True, blank=True)

    # Restos lenhosos de exploração
    debris_area = models.CharField('restos lenhosos — área percorrida', max_length=6, choices=COVER_CLASSES,
                                   blank=True, default='')

    # Solo
    soil_cover_pct  = models.FloatField('cobertura do solo — vegetação e manta morta (%)', null=True, blank=True)
    soil_sampled    = models.BooleanField('recolhida amostra de solo', null=True, blank=True)
    soil_ph         = models.FloatField('pH do solo', null=True, blank=True)
    soil_organic_matter_pct = models.FloatField('matéria orgânica (%)', null=True, blank=True)
    soil_notes      = models.TextField('observações sobre o solo', blank=True, default='')
    soil_report     = models.FileField('relatório de análise de solo', upload_to='soil_reports/', null=True,
                                       blank=True)

    # Regeneração da vegetação
    veg_cover_pct   = models.FloatField('cobertura total da vegetação (%)', null=True, blank=True)
    veg_species     = models.TextField('espécies em regeneração / dominantes', blank=True, default='')

    notes      = models.TextField('observações gerais', blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    history    = HistoricalRecords()

    # Fields shown in each phase, following the 1.ª / 2.ª fase columns of the ICNF model
    PHASE1_FIELDS = ['litter_area', 'litter_red_l', 'litter_red_f', 'litter_red_h', 'soil_exposed_pct',
                     'herb_area', 'herb_resprout_pct', 'shrub_area', 'shrub_crown_consumed_pct', 'shrub_resprout',
                     'tree_scorch_pct', 'tree_scorch_height_m', 'tree_bole_min_m', 'tree_bole_max_m', 'tree_resin',
                     'debris_area']
    PHASE2_FIELDS = ['soil_movement', 'gullying', 'herb_resprout_pct', 'herb_height_cm', 'herb_germination',
                     'shrub_dead_crowns_pct', 'shrub_resprout_pct', 'shrub_height_cm', 'shrub_germination',
                     'tree_mortality_pct', 'tree_mortality_dbh_cm', 'tree_bark_beetles', 'tree_regeneration']
    COMMON_FIELDS = ['soil_cover_pct', 'soil_sampled', 'soil_ph', 'soil_organic_matter_pct', 'soil_notes',
                     'soil_report', 'veg_cover_pct', 'veg_species', 'notes']
    SECTIONS = [
        ('Manta morta e erosão', ['litter_area', 'litter_red_l', 'litter_red_f', 'litter_red_h', 'soil_exposed_pct',
                                  'soil_movement', 'gullying']),
        ('Herbáceas', ['herb_area', 'herb_resprout_pct', 'herb_height_cm', 'herb_germination']),
        ('Arbustos', ['shrub_area', 'shrub_crown_consumed_pct', 'shrub_resprout', 'shrub_dead_crowns_pct',
                      'shrub_resprout_pct', 'shrub_height_cm', 'shrub_germination']),
        ('Árvores', ['tree_scorch_pct', 'tree_scorch_height_m', 'tree_bole_min_m', 'tree_bole_max_m', 'tree_resin',
                     'tree_mortality_pct', 'tree_mortality_dbh_cm', 'tree_bark_beetles', 'tree_regeneration']),
        ('Restos lenhosos de exploração', ['debris_area']),
        ('Solo', ['soil_cover_pct', 'soil_sampled', 'soil_ph', 'soil_organic_matter_pct', 'soil_notes',
                  'soil_report']),
        ('Regeneração da vegetação', ['veg_cover_pct', 'veg_species']),
        ('Observações', ['notes']),
    ]

    class Meta:
        ordering = ['execution', 'date']
        unique_together = [('execution', 'phase', 'year')]
        verbose_name = 'Avaliação de impacto / monitorização'
        verbose_name_plural = 'Avaliações de impacto / monitorização'

    def __str__(self):
        return f'{self.execution.parcel} — {self.label}'

    @classmethod
    def fields_for(cls, phase):
        base = cls.PHASE1_FIELDS if phase == cls.PHASE_IMEDIATA else \
            cls.PHASE2_FIELDS + (['soil_exposed_pct'] if phase == cls.PHASE_ANUAL else [])
        return base + cls.COMMON_FIELDS

    @property
    def label(self):
        if self.phase == self.PHASE_ANUAL:
            return f'Monitorização — ano {self.year}'
        return self.get_phase_display()


class ParcelCriterion(models.Model):
    """Monitoring criterion specific to a parcel (e.g. a protected species, a erosion pin, a regeneration plot)."""
    parcel      = models.ForeignKey(FireParcel, on_delete=models.CASCADE, related_name='monitoring_criteria')
    name        = models.CharField('critério', max_length=120)
    unit        = models.CharField('unidade / escala', max_length=40, blank=True, default='')
    description = models.CharField('como medir', max_length=300, blank=True, default='')
    active      = models.BooleanField('ativo', default=True)

    class Meta:
        ordering = ['id']
        verbose_name = 'Critério de monitorização da parcela'
        verbose_name_plural = 'Critérios de monitorização das parcelas'

    def __str__(self):
        return f'{self.name} ({self.unit})' if self.unit else self.name


class CriterionValue(models.Model):
    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE, related_name='criterion_values')
    criterion  = models.ForeignKey(ParcelCriterion, on_delete=models.PROTECT, related_name='values')
    value      = models.CharField('valor', max_length=200)

    class Meta:
        unique_together = [('assessment', 'criterion')]
        ordering = ['criterion_id']


class AssessmentPhoto(models.Model):
    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE, related_name='photos')
    image      = models.ImageField(upload_to='monitoring_photos/')
    caption    = models.CharField('legenda', max_length=200, blank=True, default='')

    class Meta:
        ordering = ['id']


class VisitWaiver(models.Model):
    """A scheduled visit that will not be done (e.g. the burn predates the platform), with the reason."""
    execution = models.ForeignKey(ParcelExecution, on_delete=models.CASCADE, related_name='waivers')
    phase     = models.CharField('fase', max_length=10, choices=Assessment.PHASES)
    year      = models.PositiveSmallIntegerField('ano de monitorização', default=0)
    reason    = models.TextField('motivo')
    waived_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name='visit_waivers', verbose_name='dispensada por')
    created_at = models.DateTimeField('dispensada em', auto_now_add=True)
    history   = HistoricalRecords()

    class Meta:
        ordering = ['execution', 'phase', 'year']
        unique_together = [('execution', 'phase', 'year')]
        verbose_name = 'Visita dispensada'
        verbose_name_plural = 'Visitas dispensadas'

    def __str__(self):
        return f'{self.execution.parcel} — {self.label} (dispensada)'

    @property
    def label(self):
        if self.phase == Assessment.PHASE_ANUAL:
            return f'Monitorização — ano {self.year}'
        return self.get_phase_display()
