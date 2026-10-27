from django.contrib import admin
from .models import AlertLog


@admin.register(AlertLog)
class AlertLogAdmin(admin.ModelAdmin):
    list_display = ['user', 'key', 'sent_at']
    search_fields = ['key', 'user__username']
