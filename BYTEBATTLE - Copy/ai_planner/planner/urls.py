# planner/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path("", views.planner_view, name="planner"),
    path("reflect/", views.reflection_view, name="planner_reflect"),
    path("preferences/", views.preferences_view, name="preferences"),
    path("export-ics/", views.export_ics, name="export_ics"),
    path("tasks/", views.task_library_view, name="task_library"),
    path("tasks/delete/<int:task_id>/", views.delete_saved_task, name="delete_saved_task"),
    path("history/", views.history_view, name="history"),



    # Google Calendar integration
    path("google/connect/", views.google_auth_start, name="google_auth_start"),
    path("google/oauth2/callback/", views.google_auth_callback, name="google_auth_callback"),
    path("google/add-today/", views.add_to_google_calendar, name="add_to_google_calendar"),
]
