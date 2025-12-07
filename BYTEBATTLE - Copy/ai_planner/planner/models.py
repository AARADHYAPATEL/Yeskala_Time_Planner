# planner/models.py
from django.db import models # Import Django's model module


class DayLog(models.Model): # Model for logging daily plans and reflections
    # Only 1 user for now (simple hackathon version)
    date = models.DateField(unique=True) # Date of the log entry

    # What the user typed at the start of the day
    description = models.TextField() # User's plan description

    # Raw schedule JSON the AI produced (list of blocks)
    schedule_json = models.JSONField() # AI-generated schedule in JSON format
    coach_note = models.TextField(blank=True) # Optional coaching note from AI

    # End-of-day reflection (user fills this later)
    reflection_text = models.TextField(blank=True) # User's reflection text
    energy_morning = models.PositiveSmallIntegerField(null=True, blank=True) # User's morning energy rating
    energy_afternoon = models.PositiveSmallIntegerField(null=True, blank=True) # User's afternoon energy rating
    energy_evening = models.PositiveSmallIntegerField(null=True, blank=True) # User's evening energy rating


    updated_at = models.DateTimeField(auto_now=True) # Timestamp of last update
    created_at = models.DateTimeField(auto_now_add=True) # Timestamp of creation

    class Meta: # Meta options for the model
        ordering = ["-date"] # Default ordering by date descending

    def __str__(self): # String representation of the model
        return f"DayLog {self.date}" # Return string with date

class UserPreferences(models.Model): # Model for storing user preferences
    # Only 1 user for now (simple hackathon version)
    singleton = models.BooleanField(default=True, unique=True) # Ensures only one instance exists

    preferred_sleep_time = models.TimeField(null=True, blank=True) # User's preferred sleep time
    preferred_wake_time = models.TimeField(null=True, blank=True) # User's preferred wake time

    max_study_hours = models.PositiveSmallIntegerField(null=True, blank=True) # Max study hours per day
    break_frequency_minutes = models.PositiveSmallIntegerField(null=True, blank=True) # Break frequency in minutes

    preferred_focus_period = models.CharField( # Focus period preference
        max_length=20, # Max length of the field
        choices=[ # Focus period options
            ("morning", "Morning"), # Morning option
            ("afternoon", "Afternoon"), # Afternoon option
            ("evening", "Evening"), # Evening option
        ],
        null=True, # Allow null values
        blank=True, # Allow blank values
    )

    study_style = models.CharField( # Study style preference
        max_length=20, # Max length of the field
        choices=[ # Study style options
            ("long_blocks", "Long Focus Blocks"), # Long focus blocks
            ("pomodoro", "Pomodoro (25/5)"), # Pomodoro technique
            ("mixed", "Mixed"), # Mixed style
        ],
        null=True, # Allow null values
        blank=True, # Allow blank values
    )

    stress_sensitivity = models.CharField( # Stress sensitivity preference
        max_length=20, # Max length of the field
        choices=[ # Stress sensitivity options
            ("low", "Low"), # Low sensitivity
            ("medium", "Medium"), # Medium sensitivity
            ("high", "High"), # High sensitivity
        ],
        null=True, # Allow null values
        blank=True, # Allow blank values
    )

    plays_sport = models.BooleanField(default=False) # Whether the user regularly plays sports

    def __str__(self): # String representation of the model
        return "User Preferences" # Return a fixed string
    
class SavedTask(models.Model): # Model for user-defined saved tasks
    name = models.CharField(max_length=200) # Name of the task
    default_duration_minutes = models.IntegerField(default=30)  # user-defined estimate
    default_importance = models.IntegerField(default=2)  # 3=MUST,2=SHOULD,1=NICE
    category = models.CharField(max_length=100, blank=True)  # optional grouping

    def __str__(self): # String representation of the model
        return self.name # Return the task name
