from django.contrib import admin
from .models import Operative
@admin.register(Operative)
class OperativeAdmin(admin.ModelAdmin):
    list_display = ['name','email','phone','certification_level']
    search_fields = ['name','email']
