from django.apps import AppConfig # Import AppConfig for app configuration


class PlannerConfig(AppConfig): # Define PlannerConfig class
    default_auto_field = "django.db.models.BigAutoField" # Set default auto field type
    name = "planner" # Set app name
