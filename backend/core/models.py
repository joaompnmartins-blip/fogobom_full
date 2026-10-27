from django.conf import settings
from django.db import models


class UserPreferences(models.Model):
    """Per-user email notification choices."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='preferences')
    email_new_actions    = models.BooleanField('novas ações anunciadas', default=True)
    email_action_updates = models.BooleanField('alterações às ações em que estou inscrito', default=True)
    email_reminders      = models.BooleanField('lembrete na véspera das ações', default=True)
    email_deadlines      = models.BooleanField('prazos (envio ao ICNF, monitorização, credenciação)', default=True)

    class Meta:
        verbose_name = 'Preferências de utilizador'
        verbose_name_plural = 'Preferências de utilizadores'

    @classmethod
    def for_user(cls, user):
        prefs, _ = cls.objects.get_or_create(user=user)
        return prefs
