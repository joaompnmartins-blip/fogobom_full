from django.contrib import admin
from .models import FireAction, BurningPlan
@admin.register(FireAction)
class FireActionAdmin(admin.ModelAdmin):
    list_display = ['name','scheduled_date','status']
@admin.register(BurningPlan)
class BurningPlanAdmin(admin.ModelAdmin):
    list_display = ['pre_plan','execution_date']
