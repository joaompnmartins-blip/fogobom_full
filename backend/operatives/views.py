from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from core.decorators import staff_required
from django.contrib import messages
from core.forms import form_errors_to_messages
from .forms import OperativeForm
from .models import Operative


@login_required
def operative_list(request):
    operatives = Operative.objects.all()
    return render(request, 'operatives/list.html', {'operatives': operatives})


@login_required
def operative_create(request):
    if request.method == 'POST':
        form = OperativeForm(request.POST)
        if form.is_valid():
            op = form.save()
            messages.success(request, f'Operacional "{op.name}" criado.')
            return redirect('operatives:list')
        form_errors_to_messages(request, form)
        return render(request, 'operatives/form.html', {'op': form.instance, 'action': 'Novo Operacional'})
    return render(request, 'operatives/form.html', {'action': 'Novo Operacional'})


@login_required
def operative_edit(request, pk):
    op = get_object_or_404(Operative, pk=pk)
    if request.method == 'POST':
        form = OperativeForm(request.POST, instance=op)
        if form.is_valid():
            form.save()
            messages.success(request, f'Operacional "{op.name}" atualizado.')
            return redirect('operatives:list')
        form_errors_to_messages(request, form)
    return render(request, 'operatives/form.html', {'op': op, 'action': 'Editar Operacional'})


@staff_required
def operative_delete(request, pk):
    op = get_object_or_404(Operative, pk=pk)
    if request.method == 'POST':
        name = op.name
        op.delete()
        messages.success(request, f'Operacional "{name}" eliminado.')
        return redirect('operatives:list')
    return render(request, 'operatives/confirm_delete.html', {'op': op})
