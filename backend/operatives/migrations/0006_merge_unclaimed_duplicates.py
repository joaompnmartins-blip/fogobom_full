from django.db import migrations


def merge(apps, schema_editor):
    """An operative record created before the person had an account was duplicated when they saved their
    profile. Fold each such record (same email and name as an account's record) into the account's one."""
    Operative = apps.get_model('operatives', 'Operative')
    ExecutionMember = apps.get_model('fire_actions', 'ExecutionMember')
    BurningPlan = apps.get_model('fire_actions', 'BurningPlan')
    for old in Operative.objects.filter(user__isnull=True).exclude(email=''):
        new = Operative.objects.filter(user__isnull=False, email__iexact=old.email, name__iexact=old.name).first()
        if new is None:
            continue
        for m in ExecutionMember.objects.filter(operative=old):
            if ExecutionMember.objects.filter(execution_id=m.execution_id, operative=new).exists():
                m.delete()
            else:
                m.operative = new
                m.save(update_fields=['operative'])
        for plan in BurningPlan.objects.filter(operatives=old):
            plan.operatives.remove(old)
            plan.operatives.add(new)
        for f in ('nif', 'phone', 'notes'):
            if not getattr(new, f) and getattr(old, f):
                setattr(new, f, getattr(old, f))
        new.save()
        old.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('operatives', '0005_field_book_number'),
        ('fire_actions', '0009_icnf_submission_fieldbook'),
    ]

    operations = [migrations.RunPython(merge, migrations.RunPython.noop)]
