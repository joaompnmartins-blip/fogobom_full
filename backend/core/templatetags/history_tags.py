from django import template

register = template.Library()

ACTIONS = {'+': 'Criado', '~': 'Alterado', '-': 'Eliminado'}
IGNORED_FIELDS = {'created_at'}


def _label(model, field_name):
    try:
        return str(model._meta.get_field(field_name).verbose_name).capitalize()
    except Exception:
        return field_name


@register.inclusion_tag('core/_history.html')
def change_history(obj, limit=20):
    """Recent django-simple-history records for `obj`: who, when, and which fields changed."""
    records = list(obj.history.select_related('history_user').order_by('-history_date', '-history_id')[:limit])
    entries = []
    for rec in records:
        changed = []
        prev = rec.prev_record
        if rec.history_type == '~' and prev is not None:
            delta = rec.diff_against(prev)
            changed = [_label(type(obj), c.field) for c in delta.changes if c.field not in IGNORED_FIELDS]
        entries.append({
            'date':    rec.history_date,
            'user':    rec.history_user.get_username() if rec.history_user else 'Sistema',
            'action':  ACTIONS.get(rec.history_type, rec.history_type),
            'changed': changed,
        })
    return {'entries': entries}
