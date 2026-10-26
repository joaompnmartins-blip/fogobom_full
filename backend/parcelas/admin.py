from django.contrib.gis import admin
from simple_history.admin import SimpleHistoryAdmin
from .models import FireParcel
@admin.register(FireParcel)
class FireParcelAdmin(SimpleHistoryAdmin, admin.GISModelAdmin):
    list_display = ['name','concelho','vegetation_type','area_ha']
