from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin
from .models import BurningPlan, FireAction, Participation


class ParticipationInline(admin.TabularInline):
    model = Participation
    extra = 0


@admin.register(FireAction)
class FireActionAdmin(SimpleHistoryAdmin):
    list_display = ['name', 'action_type', 'scheduled_date', 'status', 'responsible_user']
    list_filter = ['status', 'action_type', 'training']
    inlines = [ParticipationInline]


@admin.register(BurningPlan)
class BurningPlanAdmin(SimpleHistoryAdmin):
    list_display = ['pre_plan', 'execution_date']
