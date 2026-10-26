from django.core.cache import cache

CACHE_KEY = 'monitoring_overdue'


def monitoring_overdue(request):
    """Menu badge for technicians and staff: monitoring visits overdue."""
    user = getattr(request, 'user', None)
    if not (user and user.is_authenticated):
        return {}
    op = getattr(user, 'operative', None)
    if not (user.is_staff or (op and op.is_tecnico)):
        return {}
    n = cache.get(CACHE_KEY)
    if n is None:
        from .schedule import all_visits
        n = sum(1 for v in all_visits() if v['status'] == 'atrasada')
        cache.set(CACHE_KEY, n, 600)
    return {'monitoring_overdue': n}
