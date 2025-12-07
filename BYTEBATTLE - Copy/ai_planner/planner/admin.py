from django.contrib import admin # Import admin module
from .models import DayLog # Import DayLog model

@admin.register(DayLog) # Register DayLog model with admin
class DayLogAdmin(admin.ModelAdmin): # Define admin interface for DayLog
    list_display = ("date", "created_at", "updated_at") # Fields to display in admin list view
