from django.contrib.gis import admin
from simple_history.admin import SimpleHistoryAdmin
from .models import EvaluationVegetation, FireParcel, Freguesia, ParcelEvaluation, ParcelPhoto


@admin.register(FireParcel)
class FireParcelAdmin(SimpleHistoryAdmin, admin.GISModelAdmin):
    list_display = ['name', 'status', 'concelho', 'vegetation_type', 'area_ha', 'proposed_by']
    list_filter = ['status', 'vegetation_type']
    search_fields = ['name', 'concelho', 'freguesia']


class VegetationInline(admin.TabularInline):
    model = EvaluationVegetation
    extra = 0


@admin.register(ParcelEvaluation)
class ParcelEvaluationAdmin(SimpleHistoryAdmin):
    list_display = ['parcel', 'evaluator', 'visit_date', 'decision', 'completed_at']
    list_filter = ['decision']
    inlines = [VegetationInline]


@admin.register(ParcelPhoto)
class ParcelPhotoAdmin(admin.ModelAdmin):
    list_display = ['parcel', 'stage', 'caption', 'uploaded_at']


@admin.register(Freguesia)
class FreguesiaAdmin(admin.GISModelAdmin):
    list_display = ['dicofre', 'freguesia', 'concelho', 'distrito']
    search_fields = ['freguesia', 'concelho', 'dicofre']
