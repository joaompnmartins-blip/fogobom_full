from django.conf import settings
from django.db import models


class AlertLog(models.Model):
    """Deadline alert already emailed to a user (each stage of each deadline is sent once)."""
    user    = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='deadline_alerts')
    key     = models.CharField(max_length=200)
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('user', 'key')]
        verbose_name = 'Alerta de prazo enviado'
        verbose_name_plural = 'Alertas de prazos enviados'
