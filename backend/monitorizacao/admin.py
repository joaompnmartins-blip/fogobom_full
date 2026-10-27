from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin
from .models import Assessment, AssessmentPhoto, CriterionValue, ParcelCriterion, VisitWaiver


class CriterionValueInline(admin.TabularInline):
    model = CriterionValue
    extra = 0


class AssessmentPhotoInline(admin.TabularInline):
    model = AssessmentPhoto
    extra = 0


@admin.register(Assessment)
class AssessmentAdmin(SimpleHistoryAdmin):
    list_display = ['execution', 'phase', 'year', 'date', 'observer']
    list_filter = ['phase']
    inlines = [CriterionValueInline, AssessmentPhotoInline]


@admin.register(ParcelCriterion)
class ParcelCriterionAdmin(admin.ModelAdmin):
    list_display = ['name', 'parcel', 'unit', 'active']
    list_filter = ['active']


@admin.register(VisitWaiver)
class VisitWaiverAdmin(SimpleHistoryAdmin):
    list_display = ['execution', 'phase', 'year', 'waived_by', 'created_at']
    list_filter = ['phase']
