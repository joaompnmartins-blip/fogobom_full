"""Convert each existing BurningPlan (single record per action) into POQ-Execução rows per parcel."""
import json
import re
from datetime import time

from django.db import migrations

WEATHER = {'limpo': 0, 'parcialmente nublado': 1, 'nublado': 2, 'neblinoso': 4}
WIND_DIR = {'SO': 'SW', 'O': 'W', 'NO': 'NW'}


def _num(value):
    m = re.search(r'\d+(?:[.,]\d+)?', value or '')
    return float(m.group().replace(',', '.')) if m else None


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def forwards(apps, schema_editor):
    BurningPlan = apps.get_model('fire_actions', 'BurningPlan')
    ParcelExecution = apps.get_model('fire_actions', 'ParcelExecution')
    ExecutionMember = apps.get_model('fire_actions', 'ExecutionMember')
    WeatherReading = apps.get_model('fire_actions', 'WeatherReading')
    SafetyStrip = apps.get_model('fire_actions', 'SafetyStrip')

    for plan in BurningPlan.objects.select_related('pre_plan'):
        if ParcelExecution.objects.filter(plan=plan).exists():
            continue
        action = plan.pre_plan
        parcels = list(action.parcels.all())
        try:
            vehicles = json.loads(plan.vehicles or '{}')
        except (TypeError, ValueError):
            vehicles = {}
        operatives = list(plan.operatives.all())
        bft, kmh = _int(_num(plan.wind_speed_beaufort)), _num(plan.wind_speed_kmh)
        has_reading = any([plan.weather_state, bft is not None, kmh is not None, plan.wind_direction,
                           plan.fire_conduct])
        notes = f'Efeitos: {plan.burn_effects}' if plan.burn_effects else ''
        for i, parcel in enumerate(parcels):
            ex = ParcelExecution.objects.create(
                plan=plan, parcel=parcel, date=plan.execution_date, area_treated_ha=parcel.area_ha,
                formation='mato' if parcel.vegetation_type == 'matos' else 'pov',
                start_time=action.start_time,
                n_men=plan.num_men or (len(operatives) or None),
                n_vfci=_int(vehicles.get('VFCI')) or None,
                fuel_superficial=plan.fuel_superficial, fuel_manta_f=plan.fuel_manta_f,
                fuel_manta_h=plan.fuel_manta_h,
                operation_notes=notes, problems_description=plan.problems,
                rating_why=plan.burn_efficiency,
                schema=plan.tactical_schema.name if (i == 0 and plan.tactical_schema) else None,
            )
            for op in operatives:
                ExecutionMember.objects.create(execution=ex, operative=op, function='')
            for side in ('cima', 'baixo', 'lado1', 'lado2'):
                SafetyStrip.objects.create(execution=ex, side=side)
            if has_reading:
                WeatherReading.objects.create(
                    execution=ex, time=action.start_time or time(10, 0),
                    weather=WEATHER.get((plan.weather_state or '').strip().lower()),
                    wind_bft=bft, wind_kmh=kmh,
                    wind_dir=WIND_DIR.get(plan.wind_direction, plan.wind_direction or ''),
                    conduct=_int(plan.fire_conduct), conduct_other=(plan.fire_conduct_other or '')[:200])
        # Photos belonged to the plan as a whole; tie them to the parcel when there is only one
        for photo in plan.photos.all():
            photo.taken_on = photo.taken_on or plan.execution_date
            if len(parcels) == 1 and not photo.parcel_id:
                photo.parcel = parcels[0]
            photo.save()


class Migration(migrations.Migration):

    dependencies = [
        ('fire_actions', '0007_poq_execucao'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
