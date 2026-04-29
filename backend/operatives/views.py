from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Operative


@login_required
def operative_list(request):
    operatives = Operative.objects.all()
    return render(request, 'operatives/list.html', {'operatives': operatives})


@login_required
def operative_create(request):
    if request.method == 'POST':
        try:
            Operative.objects.create(
                name                = request.POST['name'],
                nif                 = request.POST.get('nif', ''),
                email               = request.POST.get('email', ''),
                phone               = request.POST.get('phone', ''),
                certification_level = request.POST.get('certification_level', ''),
                notes               = request.POST.get('notes', ''),
            )
            messages.success(request, f'Operacional "{request.POST["name"]}" criado.')
            return redirect('operatives:list')
        except Exception as e:
            messages.error(request, f'Erro: {e}')
    return render(request, 'operatives/form.html', {'action': 'Novo Operacional'})


@login_required
def operative_edit(request, pk):
    op = get_object_or_404(Operative, pk=pk)
    if request.method == 'POST':
        try:
            op.name                = request.POST['name']
            op.nif                 = request.POST.get('nif', '')
            op.email               = request.POST.get('email', '')
            op.phone               = request.POST.get('phone', '')
            op.certification_level = request.POST.get('certification_level', '')
            op.notes               = request.POST.get('notes', '')
            op.save()
            messages.success(request, f'Operacional "{op.name}" atualizado.')
            return redirect('operatives:list')
        except Exception as e:
            messages.error(request, f'Erro: {e}')
    return render(request, 'operatives/form.html', {'op': op, 'action': 'Editar Operacional'})


@login_required
def operative_delete(request, pk):
    op = get_object_or_404(Operative, pk=pk)
    if request.method == 'POST':
        name = op.name
        op.delete()
        messages.success(request, f'Operacional "{name}" eliminado.')
        return redirect('operatives:list')
    return render(request, 'operatives/confirm_delete.html', {'op': op})
