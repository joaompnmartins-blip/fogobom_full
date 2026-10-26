from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin
from .models import Operative
@admin.register(Operative)
class OperativeAdmin(SimpleHistoryAdmin):
    list_display = ['name','email','phone','certification_level']
    search_fields = ['name','email']
