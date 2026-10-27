from django.core.cache import cache


def deadlines_overdue(request):
    """Menu badge: the user's overdue deadlines (cached for 10 minutes)."""
    user = getattr(request, 'user', None)
    if not (user and user.is_authenticated):
        return {}
    key = f'deadlines_overdue:{user.pk}'
    n = cache.get(key)
    if n is None:
        from .deadlines import all_deadlines
        n = sum(1 for i in all_deadlines() if i['status'] == 'atrasado' and user.pk in i['users'])
        cache.set(key, n, 600)
    return {'deadlines_overdue': n}
