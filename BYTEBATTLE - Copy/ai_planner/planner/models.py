# planner/models.py
from django.db import models


class DayLog(models.Model):
    date = models.DateField(unique=True)

    # What the user typed at the start of the day
    description = models.TextField()

    # Raw schedule JSON the AI produced (list of blocks)
    schedule_json = models.JSONField()
    coach_note = models.TextField(blank=True)

    # End-of-day reflection (user fills this later)
    reflection_text = models.TextField(blank=True)
    energy_morning = models.PositiveSmallIntegerField(null=True, blank=True)
    energy_afternoon = models.PositiveSmallIntegerField(null=True, blank=True)
    energy_evening = models.PositiveSmallIntegerField(null=True, blank=True)


    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"DayLog {self.date}"

class UserPreferences(models.Model):
    # Only 1 user for now (simple hackathon version)
    singleton = models.BooleanField(default=True, unique=True)

    preferred_sleep_time = models.TimeField(null=True, blank=True)
    preferred_wake_time = models.TimeField(null=True, blank=True)

    max_study_hours = models.PositiveSmallIntegerField(null=True, blank=True)
    break_frequency_minutes = models.PositiveSmallIntegerField(null=True, blank=True)

    preferred_focus_period = models.CharField(
        max_length=20,
        choices=[
            ("morning", "Morning"),
            ("afternoon", "Afternoon"),
            ("evening", "Evening"),
        ],
        null=True,
        blank=True,
    )

    study_style = models.CharField(
        max_length=20,
        choices=[
            ("long_blocks", "Long Focus Blocks"),
            ("pomodoro", "Pomodoro (25/5)"),
            ("mixed", "Mixed"),
        ],
        null=True,
        blank=True,
    )

    stress_sensitivity = models.CharField(
        max_length=20,
        choices=[
            ("low", "Low"),
            ("medium", "Medium"),
            ("high", "High"),
        ],
        null=True,
        blank=True,
    )

    plays_sport = models.BooleanField(default=False)

    def __str__(self):
        return "User Preferences"
    
class SavedTask(models.Model):
    name = models.CharField(max_length=200)
    default_duration_minutes = models.IntegerField(default=30)  # user-defined estimate
    default_importance = models.IntegerField(default=2)  # 3=MUST,2=SHOULD,1=NICE
    category = models.CharField(max_length=100, blank=True)  # optional grouping

    def __str__(self):
        return self.name
