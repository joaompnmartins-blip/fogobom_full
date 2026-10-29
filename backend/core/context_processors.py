from django.conf import settings


def map_keys(request):
    return {'carto_api_key': settings.CARTO_API_KEY}


def pending_validations(request):
    """Badge count for staff: accounts awaiting approval + credentials awaiting validation."""
    user = getattr(request, 'user', None)
    if not (user and user.is_authenticated and user.is_staff):
        return {}
    from django.contrib.auth.models import User
    from operatives.models import Operative
    accounts = User.objects.filter(is_active=False, last_login__isnull=True).count()
    creds = Operative.objects.filter(credential_status=Operative.STATUS_PENDENTE).count()
    return {'pending_validations': accounts + creds}


def user_roles(request):
    """`user_is_tecnico`: validated, non-expired ICNF technician; `user_has_credential`: técnico or operacional."""
    user = getattr(request, 'user', None)
    op = getattr(user, 'operative', None) if user and user.is_authenticated else None
    from operatives.models import has_credential
    return {'user_is_tecnico': bool(op and op.is_tecnico),
            'user_has_credential': has_credential(user) if user else False}
