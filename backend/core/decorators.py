from functools import wraps
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render


def staff_required(view):
    """Login required, and only staff users may proceed."""
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_staff:
            messages.error(request, 'Apenas administradores podem realizar esta ação.')
            return redirect('core:dashboard')
        return view(request, *args, **kwargs)
    return wrapper


TECNICO_AREAS = {
    'execucoes': ('Execuções (POQ)', 'nav_bp',
                  'Nesta área os técnicos credenciados registam a execução de cada ação de fogo: equipa, '
                  'meteorologia, comportamento do fogo, custos e validação, e produzem o POQ-Execução enviado ao ICNF.'),
    'monitorizacao': ('Monitorização', 'nav_mon',
                      'Nesta área os técnicos credenciados acompanham os efeitos das queimas nas parcelas '
                      '(visitas imediata, aos 6 meses e anuais) e produzem o POQ-Impacto enviado ao ICNF.'),
}


def tecnico_area(area):
    """Login required; only validated technicians and staff see the page, others get a short explanation."""
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapper(request, *args, **kwargs):
            op = getattr(request.user, 'operative', None)
            if request.user.is_staff or (op and op.is_tecnico):
                return view(request, *args, **kwargs)
            title, nav, text = TECNICO_AREAS[area]
            return render(request, 'core/tecnico_only.html', {'title': title, 'nav': nav, 'text': text})
        return wrapper
    return decorator
