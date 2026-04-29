from django.contrib.gis import admin
from .models import FireParcel
@admin.register(FireParcel)
class FireParcelAdmin(admin.GISModelAdmin):
    list_display = ['name','concelho','vegetation_type','area_ha']
