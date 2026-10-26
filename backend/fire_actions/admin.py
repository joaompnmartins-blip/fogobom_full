from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin
from .models import FireAction, BurningPlan
@admin.register(FireAction)
class FireActionAdmin(SimpleHistoryAdmin):
    list_display = ['name','scheduled_date','status']
@admin.register(BurningPlan)
class BurningPlanAdmin(SimpleHistoryAdmin):
    list_display = ['pre_plan','execution_date']
