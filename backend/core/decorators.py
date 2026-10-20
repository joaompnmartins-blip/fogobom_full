from functools import wraps
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


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
