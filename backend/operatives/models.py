from django.db import models
from simple_history.models import HistoricalRecords

class Operative(models.Model):
    name                = models.CharField(max_length=100)
    nif                 = models.CharField(max_length=20, blank=True, default='')
    email               = models.EmailField()
    phone               = models.CharField(max_length=20)
    certification_level = models.CharField(max_length=50)
    notes               = models.TextField(blank=True, default='')
    created_at          = models.DateTimeField(auto_now_add=True)
    history             = HistoricalRecords()

    class Meta:
        ordering = ['name']
        verbose_name = 'Operacional'
        verbose_name_plural = 'Operacionais'

    def __str__(self):
        return self.name
