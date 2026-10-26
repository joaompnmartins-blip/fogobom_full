from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin
from .models import IcnfTechnician, Operative


@admin.register(Operative)
class OperativeAdmin(SimpleHistoryAdmin):
    list_display = ['name', 'user', 'credential_type', 'credential_number', 'credential_status',
                    'credential_valid_until']
    list_filter = ['credential_type', 'credential_status']
    search_fields = ['name', 'email', 'credential_number']
    raw_id_fields = ['user', 'credential_reviewed_by']


@admin.register(IcnfTechnician)
class IcnfTechnicianAdmin(admin.ModelAdmin):
    list_display = ['number', 'text', 'lifetime', 'valid_until', 'list_date']
    search_fields = ['number', 'text']
