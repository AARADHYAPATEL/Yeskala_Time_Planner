# planner/urls.py
from django.urls import path # Import path function for URL routing
from . import views # Import views from the current package

urlpatterns = [ # Define URL patterns
    path("", views.planner_view, name="planner"), # Main planner view
    path("reflect/", views.reflection_view, name="planner_reflect"), # Reflection view
    path("preferences/", views.preferences_view, name="preferences"), # User preferences view
    path("export-ics/", views.export_ics, name="export_ics"), # Export to ICS file
    path("tasks/", views.task_library_view, name="task_library"), # Task library view
    path("tasks/delete/<int:task_id>/", views.delete_saved_task, name="delete_saved_task"), # Delete saved task
    path("history/", views.history_view, name="history"), # History view



    # Google Calendar integration
    path("google/connect/", views.google_auth_start, name="google_auth_start"), # Start Google OAuth2 flow
    path("google/oauth2/callback/", views.google_auth_callback, name="google_auth_callback"), # OAuth2 callback
    path("google/add-today/", views.add_to_google_calendar, name="add_to_google_calendar"), # Add today's plan to Google Calendar
]
