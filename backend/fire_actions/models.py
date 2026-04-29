from django.db import models
from parcelas.models import FireParcel
from operatives.models import Operative


class FireAction(models.Model):
    STATUS_CHOICES = [
        ('Pre-Plano', 'Pré-Plano'),
        ('Executada',  'Executada'),
    ]
    name           = models.CharField(max_length=200)
    responsible    = models.CharField(max_length=200, blank=True, default='')
    scheduled_date = models.DateField()
    notes          = models.TextField(blank=True, default='')
    parcels        = models.ManyToManyField(FireParcel, related_name='fire_actions')
    status         = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pre-Plano')
    execution_date = models.DateField(null=True, blank=True)
    created_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-scheduled_date']
        verbose_name = 'Pré-Plano'
        verbose_name_plural = 'Pré-Planos'

    def __str__(self):
        return f"{self.name} ({self.scheduled_date})"


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

    class Meta:
        ordering = ['-execution_date']
        verbose_name = 'Plano de Queima'
        verbose_name_plural = 'Planos de Queima'

    def __str__(self):
        return f"Plano de Queima — {self.pre_plan.name} ({self.execution_date})"
