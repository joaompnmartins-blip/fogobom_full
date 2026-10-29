"""Livro de campo (Regulamento do Fogo Técnico, art. 6.º, 7.º e 27.º): each person's participation in burns,
with hours, function and validation — the basis for renewing the credential (150 h técnico / 100 h operacional)."""
from datetime import timedelta

from django.utils import timezone

from fire_actions.models import ExecutionMember, ParcelExecution
from operatives.models import Operative
from parcelas.models import Freguesia

# ICNF register (BD_FOGO-CONTROLADO) wording
ICNF_FUNCTIONS = {'coordenacao': 'Responsável de queima', 'responsavel_linha': 'Chefe de Ignição',
                  'ignicao': 'Pinga-lume', 'vigilancia': 'Vigia', 'seguranca': 'Chefe de segurança',
                  'apoio': 'Apoio', 'formacao': 'Em formação', 'todas': 'Todas as funções'}
# Who validates the action (Regulamento, art. 7.º n.º 4) — same wording in the app and in the Excel list
ICNF_VALIDATOR = dict(ParcelExecution.VALIDATOR_ROLES)
ICNF_FORMATION = {'mato': 'Mato', 'pov': 'Pov', 'res': 'Res'}
RENEWAL_HOURS = {Operative.CRED_TECNICO: 150, Operative.CRED_OPERACIONAL: 100}
CREDENTIAL_YEARS = 5


def _distrito(parcel, cache):
    if parcel.distrito:
        return parcel.distrito
    if parcel.concelho not in cache:
        cache[parcel.concelho] = (Freguesia.objects.filter(concelho=parcel.concelho)
                                  .values_list('distrito', flat=True).first() or '')
    return cache[parcel.concelho]


def entries(operative, year=None):
    """Participations of `operative`, oldest first, as dicts ready for the page and the ICNF Excel."""
    qs = (ExecutionMember.objects.filter(operative=operative)
          .select_related('execution__parcel', 'execution__plan__pre_plan__pfc',
                          'execution__plan__pre_plan__responsible_user__operative', 'validated_by__operative')
          .prefetch_related('execution__members__operative')
          .order_by('execution__date', 'execution__start_time', 'id'))
    if year:
        qs = qs.filter(execution__date__year=year)
    distritos = {}
    out = []
    for m in qs:
        ex = m.execution
        action = ex.plan.pre_plan
        resp = getattr(action.responsible_user, 'operative', None) if action.responsible_user_id else None
        pfc_ref = ''
        if action.pfc_id:
            number = action.pfc.plan_parcels.filter(parcel_id=ex.parcel_id).values_list('number', flat=True).first()
            pfc_ref = f'PFC {action.pfc.number}' + (f', parcela {number}' if number else '')
        elif action.pfc_reference:
            pfc_ref = f'PFC {action.pfc_reference}'
        others = [f'{o.operative.name}' + (f' ({o.operative.credential_number})' if o.operative.credential_number else '')
                  + (f' {ICNF_FUNCTIONS.get(o.function, "").lower()}' if o.function else '')
                  for o in ex.members.all() if o.pk != m.pk]
        means = ', '.join(t for t in [
            f'{ex.n_vfci} VFCI' if ex.n_vfci else '', f'{ex.n_vlci} VLCI' if ex.n_vlci else '',
            f'{ex.n_men} operacionais' if ex.n_men else ''] if t)
        notes = '; '.join(t for t in [
            f'Equipa: {", ".join(others)}' if others else '',
            f'Meios: {means}' if means else '',
            f'Ignição: {ex.ignition_techniques}' if ex.ignition_techniques else '',
            f'Problemas: {ex.problems_display}' if ex.problems else '',
            'Fuga do fogo' if ex.plan.incident else ''] if t)
        if operative.credential_type == Operative.CRED_TECNICO:
            # técnico: the action is validated by the owner, the PFC proponent or ICNF (art. 7.º n.º 4)
            # the ICNF counts the hours only with the name of who validated
            validation_role = ICNF_VALIDATOR.get(ex.validator_role, '')
            validation_name, validated = ex.validator_name, bool(ex.validator_role and ex.validator_name.strip())
        else:
            # operacional: validated by the supervising technician (art. 27.º n.º 2)
            vop = getattr(m.validated_by, 'operative', None) if m.validated_by_id else None
            validation_role = 'Técnico credenciado' if m.validated_by_id else ''
            validation_name = (vop.name if vop else m.validated_by.get_username()) if m.validated_by_id else ''
            validated = bool(m.validated_by_id)
        out.append({
            'member': m, 'execution': ex, 'action': action,
            'book': operative.field_book_number, 'page': m.book_page,
            'freguesia': ex.parcel.freguesia, 'concelho': ex.parcel.concelho,
            'distrito': _distrito(ex.parcel, distritos),
            'type': 'Formação' if action.training else
                    'Plano Fogo Controlado' if action.action_type == action.TYPE_FOGO_CONTROLADO else 'Queimada Autor.',
            'date': ex.date, 'start': ex.start_time, 'end': ex.end_time,
            'objectives': action.objectives_display or (action.get_purpose_display() if action.purpose else ''),
            'formation': ICNF_FORMATION.get(ex.formation, ''), 'composition': ex.parcel.get_vegetation_type_display()
            if ex.parcel.vegetation_type else '',
            'function': ICNF_FUNCTIONS.get(m.function, ''), 'area': ex.area_treated_ha,
            'hours': m.effective_hours,
            'validation_role': validation_role, 'validation_name': validation_name, 'validated': validated,
            'missing_name': bool(validation_role) and not validated,
            'other': '; '.join(t for t in [
                f'Responsável de queima: {resp.name} ({resp.credential_number})' if resp else '', pfc_ref] if t),
            'notes': notes,
        })
    return out


def credential_period(operative, today=None):
    """(start, end) of the current credential period: the 5 years before the end of validity, or the last 5."""
    today = today or timezone.localdate()
    end = operative.credential_valid_until if operative.credential_valid_until and \
        not operative.credential_lifetime else today
    start = end.replace(year=end.year - CREDENTIAL_YEARS) if not (end.month == 2 and end.day == 29) \
        else end - timedelta(days=365 * CREDENTIAL_YEARS + 1)
    return start, end


def hours_summary(operative, rows=None, today=None):
    """Validated and total hours in the credential period vs. the renewal minimum."""
    rows = entries(operative) if rows is None else rows
    start, end = credential_period(operative, today)
    period = [r for r in rows if start <= r['date'] <= end]
    total = sum(r['hours'] or 0 for r in period)
    validated = sum(r['hours'] or 0 for r in period if r['validated'])
    if operative.credential_type == Operative.CRED_TECNICO:   # art. 8.º counts the técnico's own burns
        as_resp = sum(r['hours'] or 0 for r in period if r['member'].function == 'coordenacao')
    else:
        as_resp = None
    required = RENEWAL_HOURS.get(operative.credential_type)
    return {'start': start, 'end': end, 'total': round(total, 1), 'validated': round(validated, 1),
            'as_responsible': round(as_resp, 1) if as_resp is not None else None, 'required': required,
            'missing_hours': sum(1 for r in period if r['hours'] is None),
            'pct': min(100, round(100 * validated / required)) if required else None}
