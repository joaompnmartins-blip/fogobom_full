from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin
from .models import PFC, CostSettings, PFCParcel


class PFCParcelInline(admin.TabularInline):
    model = PFCParcel
    extra = 0
    fields = ['number', 'parcel', 'season', 'cost_type', 'cost_slope', 'cost_load']


@admin.register(PFC)
class PFCAdmin(SimpleHistoryAdmin):
    list_display = ['name', 'sequence', 'credential_number', 'status', 'validity_start', 'validity_end']
    list_filter = ['status', 'dcnf']
    inlines = [PFCParcelInline]


@admin.register(CostSettings)
class CostSettingsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not CostSettings.objects.exists()
