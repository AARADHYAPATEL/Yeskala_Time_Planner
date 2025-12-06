from django.contrib import admin
from .models import DayLog

@admin.register(DayLog)
class DayLogAdmin(admin.ModelAdmin):
    list_display = ("date", "created_at", "updated_at")
