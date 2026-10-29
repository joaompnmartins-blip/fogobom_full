from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords

# Renewal can be requested in the 2 months before expiry (Regulamento do Fogo Técnico, art. 8.º)
RENEWAL_WINDOW = timedelta(days=61)


class Operative(models.Model):
    CRED_TECNICO     = 'tecnico_fc'
    CRED_OPERACIONAL = 'operacional'
    CRED_NENHUMA     = 'nenhuma'
    CREDENTIAL_TYPES = [
        (CRED_TECNICO,     'Técnico credenciado em fogo controlado'),
        (CRED_OPERACIONAL, 'Operacional de queima'),
        (CRED_NENHUMA,     'Sem credenciação'),
    ]
    STATUS_NA        = 'na'
    STATUS_PENDENTE  = 'pendente'
    STATUS_VALIDADA  = 'validada'
    STATUS_RECUSADA  = 'recusada'
    CREDENTIAL_STATUS = [
        (STATUS_NA,       '—'),
        (STATUS_PENDENTE, 'Por validar'),
        (STATUS_VALIDADA, 'Validada'),
        (STATUS_RECUSADA, 'Recusada'),
    ]

    user                = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                               null=True, blank=True, related_name='operative',
                                               verbose_name='conta de utilizador')
    name                = models.CharField('nome', max_length=100)
    nif                 = models.CharField(max_length=20, blank=True, default='')
    email               = models.EmailField()
    phone               = models.CharField('telefone', max_length=20)
    certification_level = models.CharField('nível de certificação', max_length=50)
    notes               = models.TextField(blank=True, default='')
    created_at          = models.DateTimeField(auto_now_add=True)

    credential_type     = models.CharField('tipo de credenciação', max_length=20,
                                           choices=CREDENTIAL_TYPES, default=CRED_NENHUMA)
    credential_number   = models.CharField('n.º de credenciação ICNF', max_length=20, blank=True, default='')
    credential_lifetime = models.BooleanField('credenciação vitalícia', default=False)
    credential_valid_until = models.DateField('validade da credenciação', null=True, blank=True)
    field_book_number   = models.CharField('n.º do livro de campo', max_length=20, blank=True, default='')
    credential_status   = models.CharField('estado da credenciação', max_length=10,
                                           choices=CREDENTIAL_STATUS, default=STATUS_NA)
    credential_reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                               null=True, blank=True, related_name='+',
                                               verbose_name='validada por')
    credential_reviewed_at = models.DateTimeField('validada em', null=True, blank=True)
    credential_rejection_reason = models.TextField('motivo da recusa', blank=True, default='')

    history             = HistoricalRecords()

    class Meta:
        ordering = ['name']
        verbose_name = 'Operacional'
        verbose_name_plural = 'Operacionais'

    def __str__(self):
        return self.name

    @property
    def credential_expired(self):
        return (not self.credential_lifetime and self.credential_valid_until is not None
                and self.credential_valid_until < timezone.localdate())

    @property
    def credential_expiring(self):
        """In the legal renewal window (2 months before expiry) and not yet expired."""
        if self.credential_lifetime or self.credential_valid_until is None or self.credential_expired:
            return False
        return self.credential_valid_until - timezone.localdate() <= RENEWAL_WINDOW

    @property
    def is_tecnico(self):
        """Validated, non-expired ICNF credential in controlled burning."""
        return (self.credential_type == self.CRED_TECNICO
                and self.credential_status == self.STATUS_VALIDADA
                and not self.credential_expired)



def link_unclaimed_operative(user):
    """Attach to `user` an operative record created before they had an account (same email), if any."""
    if getattr(user, 'operative', None) is not None or not user.email:
        return None
    op = Operative.objects.filter(user__isnull=True, email__iexact=user.email).order_by('created_at').first()
    if op:
        op.user = user
        op.save(update_fields=['user'])
        user.operative = op
    return op


def has_credential(user):
    """Técnico credenciado or operacional de queima (they have deadlines and a livro de campo)."""
    op = getattr(user, 'operative', None) if user and user.is_authenticated else None
    return bool(op and op.credential_type != Operative.CRED_NENHUMA)


class IcnfTechnician(models.Model):
    """One line of the ICNF list of technicians credentialed in controlled burning."""
    number      = models.CharField('n.º ICNF', max_length=20, unique=True)
    name        = models.CharField('nome', max_length=150)
    concelho    = models.CharField('concelho de residência', max_length=100, blank=True, default='')
    lifetime    = models.BooleanField('vitalícia', default=False)
    valid_until = models.DateField('validade', null=True, blank=True)
    list_date   = models.DateField('data da lista', null=True, blank=True)

    class Meta:
        ordering = ['number']
        verbose_name = 'Técnico da lista ICNF'
        verbose_name_plural = 'Lista ICNF de técnicos credenciados'

    def __str__(self):
        return f'{self.number} {self.name}'
