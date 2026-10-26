from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def eur(value):
    """1234.5 → '1 234,50 €' (Portuguese format)."""
    if value is None or value == '':
        return '—'
    try:
        v = Decimal(str(value)).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        return value
    sign = '-' if v < 0 else ''
    whole, cents = f'{abs(v):.2f}'.split('.')
    groups = []
    while whole:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    return f'{sign}{" ".join(groups)},{cents} €'
