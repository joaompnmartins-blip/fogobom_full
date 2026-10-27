from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from fire_actions.models import BurningPlan, ParcelExecution
from fire_actions.views import can_manage
from operatives.models import Operative
from .deadlines import KIND_LABELS, all_deadlines
from .excel import generate_icnf_xlsx
from .fieldbook import entries, hours_summary


@login_required
def deadlines_page(request):
    items = all_deadlines()
    mine = [i for i in items if request.user.pk in i['users']]
    scope = request.GET.get('ver', 'meus' if mine or not request.user.is_staff else 'todos')
    shown = mine if scope == 'meus' else items
    kind = request.GET.get('tipo', '')
    if kind in KIND_LABELS:
        shown = [i for i in shown if i['kind'] == kind]
    return render(request, 'registos/deadlines.html', {
        'items': shown, 'scope': scope, 'kind': kind, 'kinds': KIND_LABELS.items(),
        'n_mine': len(mine), 'n_all': len(items),
        'overdue': sum(1 for i in shown if i['status'] == 'atrasado'),
    })


@login_required
def my_fieldbook(request):
    op = getattr(request.user, 'operative', None)
    if op is None:
        messages.info(request, 'Complete primeiro o seu perfil.')
        return redirect('core:profile')
    return redirect('registos:fieldbook', op_pk=op.pk)


def _year(request):
    try:
        return int(request.GET.get('ano', ''))
    except ValueError:
        return None


@login_required
def fieldbook(request, op_pk):
    op = get_object_or_404(Operative, pk=op_pk)
    all_rows = entries(op)
    year = _year(request)
    rows = [r for r in all_rows if r['date'].year == year] if year else all_rows
    return render(request, 'registos/fieldbook.html', {
        'op': op, 'rows': rows, 'year': year, 'summary': hours_summary(op, all_rows),
        'years': sorted({r['date'].year for r in all_rows}, reverse=True),
        'can_export': op.credential_type == Operative.CRED_TECNICO and (
            request.user.is_staff or op.user_id == request.user.pk),
        'total_hours': round(sum(r['hours'] or 0 for r in rows), 1),
    })


@login_required
def fieldbook_xlsx(request, op_pk):
    op = get_object_or_404(Operative, pk=op_pk)
    if not (request.user.is_staff or op.user_id == request.user.pk):
        messages.error(request, 'Só o próprio técnico ou um administrador podem exportar a base de dados.')
        return redirect('registos:fieldbook', op_pk=op.pk)
    year = _year(request)
    content = generate_icnf_xlsx(op, entries(op, year))
    response = HttpResponse(content,
                            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    ref = (op.credential_number or str(op.pk)).replace('/', '-')
    response['Content-Disposition'] = (f'attachment; filename="BD_FOGO-CONTROLADO_{ref}'
                                       f'{"_" + str(year) if year else ""}.xlsx"')
    return response


@require_POST
@login_required
def mark_sent(request, plan_pk):
    """Record (or clear) the date the POQ-Execução / POQ-Impacto was sent to ICNF."""
    plan = get_object_or_404(BurningPlan.objects.select_related('pre_plan'), pk=plan_pk)
    if not can_manage(request.user, plan.pre_plan):
        messages.error(request, 'Sem permissão para alterar esta execução.')
        return redirect('fire_actions:burning_plan_detail', pk=plan.pk)
    field = {'poq': 'poq_sent_on', 'impacto': 'impact_sent_on'}.get(request.POST.get('which'))
    if not field:
        return redirect('fire_actions:burning_plan_detail', pk=plan.pk)
    sent_on = None
    if not request.POST.get('clear'):
        try:
            sent_on = datetime.strptime(request.POST.get('date', ''), '%Y-%m-%d').date()
        except ValueError:
            messages.error(request, 'Data inválida.')
            return redirect('fire_actions:burning_plan_detail', pk=plan.pk)
        if sent_on > timezone.localdate():
            messages.error(request, 'A data de envio não pode ser futura.')
            return redirect('fire_actions:burning_plan_detail', pk=plan.pk)
    setattr(plan, field, sent_on)
    plan.save(update_fields=[field])
    cache.delete(f'deadlines_overdue:{request.user.pk}')
    what = 'POQ-Execução' if field == 'poq_sent_on' else 'POQ-Impacto'
    messages.success(request, f'{what}: envio ao ICNF registado em {sent_on:%d/%m/%Y}.' if sent_on
                     else f'{what}: registo de envio anulado.')
    return redirect('fire_actions:burning_plan_detail', pk=plan.pk)


@require_POST
@login_required
def validate_team(request, ex_pk):
    """The supervising técnico validates the participation of the operacionais (Regulamento, art. 27.º n.º 2)."""
    ex = get_object_or_404(ParcelExecution.objects.select_related('plan__pre_plan'), pk=ex_pk)
    op = getattr(request.user, 'operative', None)
    if not (op and op.is_tecnico):
        messages.error(request, 'Só um técnico credenciado valida a participação dos operacionais.')
        return redirect('fire_actions:execution_edit', pk=ex.pk)
    members = ex.members.exclude(operative=op).exclude(operative__credential_type=Operative.CRED_TECNICO)
    n = members.filter(validated_by__isnull=True).update(validated_by=request.user, validated_at=timezone.now())
    messages.success(request, f'Participação validada para {n} operaciona{"l" if n == 1 else "is"}.' if n
                     else 'Não há participações por validar.')
    return redirect('fire_actions:execution_edit', pk=ex.pk)
