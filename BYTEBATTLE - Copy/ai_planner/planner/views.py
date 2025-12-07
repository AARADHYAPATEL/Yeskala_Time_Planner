import json # Importing JSON module for handling JSON data
import datetime # Importing datetime module for date and time manipulation
from typing import Optional # Importing Optional type hint

from django.shortcuts import render, redirect # Importing render and redirect functions from Django
from django.conf import settings # Importing settings from Django configuration
from django.utils import timezone # Importing timezone utilities from Django
from django.http import HttpResponse # Importing HttpResponse class from Django
from openai import OpenAI # Importing OpenAI client library

from .models import DayLog # Importing DayLog model from current app
from .models import UserPreferences # Importing UserPreferences model from current app
from .models import SavedTask # Importing SavedTask model from current app

from google_auth_oauthlib.flow import Flow # Importing Flow class for Google OAuth
from googleapiclient.discovery import build # Importing build function for Google API client
from google.oauth2.credentials import Credentials # Importing Credentials class for Google OAuth2


# OpenAI client using key from settings.py
client = OpenAI(api_key=settings.OPENAI_API_KEY)


def build_prompt(user_text: str, previous_summary: Optional[str] = None) -> str: # Build the prompt for OpenAI
    """
    Build a prompt where the user gives a free-text description of:
    - who they are
    - how they feel today
    - their tasks, deadlines, constraints, preferences
    Optionally includes a summary of yesterday's plan + reflection.
    """
    lines = [ # List to hold lines of the prompt
        "You are an advanced AI time-management system for a student.",
        "The user will describe themselves and their day in free text.",
        "Your job is to:",
        "- infer their energy pattern, stress level, and priorities",
        "- extract tasks, estimate durations, and assign a clear priority level",
        "- build a realistic schedule from wake to slee p",
        "- adapt to their mood, constraints, and goals",
        "- and give a short coach note for the day.",
        "",
        "=== USER DESCRIPTION START ===",
        user_text, # Inserting user description into the prompt
        "=== USER DESCRIPTION END ===",
    ]

    if previous_summary: # If previous summary is provided
        lines += [ # Add previous day reflection section
            "",
            "=== PAST DAY REFLECTION (YESTERDAY) ===",
            previous_summary, # Inserting previous summary into the prompt
            (
                "Use this information to calibrate today's plan realistically. "
                "If they consistently overestimated last time, schedule slightly less intense blocks, "
                "move the hardest tasks into their best energy windows, and protect their rest."
            ),
        ]

    lines += [ # Continuing to build the prompt
        "",
        "From this description, you must internally reconstruct:",
        "- wake time and sleep time (or reasonable assumptions if missing)",
        "- a list of tasks with estimated durations",
        "- for each task, a PRIORITY bucket:",
        "    - MUST-DO today (deadline / very important)",
        "    - SHOULD-DO today (important but flexible)",
        "    - NICE-TO-HAVE (only if time/energy allows)",
        "- their stress tolerance and energy peaks (when they focus best, when they crash)",
        "",
        "Then generate a plan for TODAY only.",
        "",

        "Mood detection rules:",
        "- Infer mood only from the user's description: energy, stress, motivation, urgency, sleep quality, and emotional language.",
        "- You MUST assign a mood intensity from 1 to 10:",
        "    1-2 = extremely low energy / severely tired / defeated",
        "    3-4 = low energy, stressed, unfocused, mild negativity",
        "    5-6 = neutral or mixed emotional state",
        "    7-8 = strong emotion (very motivated, very stressed, very excited, etc.)",
        "    9-10 = extremely intense emotion (only if user language is very emotional)",
        "- Do NOT copy any example number for intensity.",
        "- You must THINK and calculate intensity uniquely for each prompt.",
        "- mood.intensity MUST be a NUMBER, not a string.",
        "",
        "=== OUTPUT FORMAT (STRICT JSON) ===",
        """
Return a SINGLE JSON object with exactly these keys:

{
  "schedule": [
    {
      "task": "string - task or break label",
      "type": "task" or "break",
      "start": "HH:MM in 24h format",
      "end": "HH:MM in 24h format",
      "importance": integer from 0 to 3,
      "note": "1-3 sentences explaining WHY this block is here, referencing their mood, energy, and goals."
    }
  ],
  "mood": {
      "label": "short phrase describing the user's emotional state",
      "intensity": "an integer from 1 to 10 based on the strength of the emotional tone",
      "reasoning": "1-2 sentences explaining why this mood and intensity were chosen"
 },

  "coach_note": "2-5 sentence high-level reflection and advice for this user about how to approach TODAY overall."
}

Priority mapping rules:
- importance = 3 → MUST-DO today (top priority, ideally done in their peak focus time).
- importance = 2 → SHOULD-DO today (important but can be moved slightly if needed).
- importance = 1 → NICE-TO-HAVE (only if time/energy remains).
- importance = 0 → REST / BREAK / LOW-INTENSITY blocks (usually with type = "break").

Scheduling rules:
- Cover the full day from wake time to sleep time with realistic spacing.
- Put MUST-DO (3) tasks into their best focus windows and earlier in the day if possible.
- Then place SHOULD-DO (2) tasks around them.
- Only insert NICE-TO-HAVE (1) tasks in leftover energy/time.
- Respect what the user says about when they feel more focused or tired.
- If they sound stressed or overloaded, insert more breaks and reduce intensity.
- Use importance=0 and type='break' for rest/food/scrolling/relaxation blocks.
- Never leave 'note' empty. Each block needs a meaningful explanation.
- Do NOT wrap the JSON in markdown. Output ONLY pure JSON.
"""
    ]

    return "\n".join(lines) # Join all lines into a single prompt string




def call_openai_schedule(prompt: str):
    """
    Call OpenAI to generate the schedule.
    Expects a JSON object: { "schedule": [...], "coach_note": "..." }
    """
    if not settings.OPENAI_API_KEY: # Check if OpenAI API key is configured
        raise RuntimeError("OPENAI_API_KEY is not configured in settings.py") # Raise error if API key is missing

    resp = client.chat.completions.create( # Call OpenAI chat completion API
        model="gpt-4o",  # or "gpt-5-large" if you want stronger
        temperature=0.4, # some creativity but not too much
        response_format={"type": "json_object"}, # expect JSON object response
        messages=[ # Message list for chat completion
            {
                "role": "system",
                "content": (
                    "You are an expert AI daily schedule planner and coach for students. "
                    "You are careful, realistic, and supportive."
                ),
            },
            {"role": "user", "content": prompt}, # User prompt message
        ],
    )

    content = resp.choices[0].message.content  # JSON string
    data = json.loads(content) # parse JSON

    schedule = data.get("schedule", []) # Extract schedule from response
    if not isinstance(schedule, list): # Ensure schedule is a list
        schedule = [] # Default to empty list if not

    schedule = validate_schedule(schedule) # Validate the schedule blocks

    coach_note = data.get("coach_note", "") # Extract coach note from response
    mood = data.get("mood", {}) # Extract mood from response

    return schedule, coach_note, content, mood # Return schedule, coach note, raw content, and mood


def planner_view(request): # Main view for daily planner
    schedule = None # Initialize schedule variable
    coach_note = None # Initialize coach note variable
    raw_model_output = None # Initialize raw model output variable
    error = None # Initialize error variable
    mood = None # Initialize mood variable

    today = timezone.localdate() # Get today's date
    form_defaults = {"description": "",} # Default form values

    load_str = request.GET.get("load") # Check if loading a previous day's log
    if load_str and request.method == "GET": # Only on GET requests
        try: # Try to parse the load date
            load_date = datetime.date.fromisoformat(load_str)  # expects YYYY-MM-DD
            log = DayLog.objects.filter(date=load_date).first() # Fetch the DayLog for the specified date
            if log: # If log exists
                form_defaults["description"] = log.description # Pre-fill description
                schedule = log.schedule_json # Load saved schedule
                coach_note = log.coach_note # Load saved coach note
        except ValueError: # If ValueError occurs
            # ignore bad load param and just render normal
            pass # Ignore invalid date format

    if request.method == "POST": # Handle form submission
        description = request.POST.get("description", "").strip() # Get user description from form
        form_defaults["description"] = description # Update form defaults

        # ---- Add selected SavedTasks into the description (task library) ----
        library_tasks = [] # List to hold selected library tasks
        for t in SavedTask.objects.all(): # Iterate over all saved tasks
            if request.POST.get(f"library_task_{t.id}"): # Check if task is selected
                library_tasks.append(t) # Add task to library tasks list

        if library_tasks: # If there are selected library tasks
            pieces = [] # List to hold task descriptions
            for t in library_tasks: # Iterate over selected tasks
                pieces.append( # Append task description to pieces list
                    f"{t.name} (about {t.default_duration_minutes} minutes, " # Task name and duration
                    f"importance {t.default_importance})" # Task importance
                )
            library_text = "Extra tasks I selected from my task library: " + "; ".join(pieces) + "." # Create library text
            # append to description so AI sees it
            description = (description + "\n\n" + library_text).strip() # Append library text to user description
            form_defaults["description"] = description # Update form defaults with new description

        if not description: # If description is empty
            error = "Describe yourself and your day so the AI has something to work with." # Set error message
        else: # If description is provided
            # ---- Build previous day summary (for personalization) ----
            yesterday = today - datetime.timedelta(days=1) # Calculate yesterday's date
            previous_summary = None # Initialize previous summary variable
            yesterday_log = ( # Fetch yesterday's DayLog with reflection
                DayLog.objects # Query DayLog model
                .filter(date=yesterday) # Filter by yesterday's date
                .exclude(reflection_text="") # Exclude logs without reflection
                .first() # Get the first matching log
            )
            if yesterday_log: # If yesterday's log exists
                previous_summary = ( # Build summary string
                    "Yesterday's plan and reflection:\n" # Summary header
                    f"- Schedule (JSON): {json.dumps(yesterday_log.schedule_json, ensure_ascii=False)}\n" # Schedule in JSON format
                    f"- Reflection: {yesterday_log.reflection_text}\n" # User reflection
                    f"- Energy (1-10): morning={yesterday_log.energy_morning}, " # Energy levels
                    f"afternoon={yesterday_log.energy_afternoon}, night={yesterday_log.energy_evening}\n" # Energy levels continued
                )

            pref_summary = None # Initialize preferences summary variable
            prefs = UserPreferences.objects.get_or_create(singleton=True)[0] # Fetch or create user preferences

            pref_summary = ( # Build preferences summary string
                f"User preferences: " # Summary header
                f"wake={prefs.preferred_wake_time}, " # Preferred wake time
                f"sleep={prefs.preferred_sleep_time}, " # Preferred sleep time
                f"max_study_hours={prefs.max_study_hours}, " # Max study hours
                f"break_frequency={prefs.break_frequency_minutes} mins, " # Break frequency
                f"focus_period={prefs.preferred_focus_period}, " # Preferred focus period
                f"study_style={prefs.study_style}, " # Prefered study style
                f"stress_sensitivity={prefs.stress_sensitivity}, " # Stress sensitivity
                f"plays_sport={prefs.plays_sport}." # Whether user plays sport
            )

            prompt = build_prompt(description, previous_summary + "\n" + pref_summary if previous_summary else pref_summary) # Build the prompt for OpenAI

            try: # Try to call OpenAI API
                schedule, coach_note, raw_json, mood = call_openai_schedule(prompt) # Call OpenAI to get schedule and coach note
                raw_model_output = raw_json # Store raw model output
                if not schedule: # If schedule is empty
                    error = "AI did not return any schedule blocks." # Set error message
                else: # If schedule is returned
                    # ---- Persist today's plan so we can reflect on it at night ----
                    DayLog.objects.update_or_create( # Update or create DayLog for today
                        date=today, # Today's date
                        defaults={ # Default values for DayLog
                            "description": description, # User description
                            "schedule_json": schedule, # Generated schedule
                            "coach_note": coach_note or "", # Generated coach note
                        },
                    )
            except Exception as e: # If an exception occurs
                error = f"Error contacting AI backend: {e}" # Set error message
    context = {
        "form": form_defaults, # Form defaults for rendering
        "schedule": schedule, # Generated schedule
        "coach_note": coach_note, # Generated coach note
        "raw_model_output": raw_model_output, # Raw model output
        "error": error, # Error message if any
        "saved_tasks": SavedTask.objects.all(), # All saved tasks for task library
        "mood": mood, # Detected mood information
    }
    return render(request, "planner/planner.html", context) # Render the planner template with context

def validate_schedule(schedule): # Validate the generated schedule
    valid = [] # List to hold valid schedule blocks
    last_end = None # Variable to track the end time of the last block

    for block in schedule: # Iterate over each block in the schedule
        if not block.get("start") or not block.get("end"): # Check if start and end times are present
            continue # Skip blocks without start or end times
        
        if last_end and block["start"] < last_end: # If block starts before the last block ended
            # fix overlap by adjusting start
            block["start"] = last_end # Adjust start time to last end time
        
        last_end = block["end"] # Update last end time
        valid.append(block) # Add valid block to the list
    
    return valid # Return the list of valid schedule blocks

def reflection_view(request): # View for end-of-day reflection
    """
    Simple end-of-day reflection page.
    User rates energy + writes how the day actually went.
    This will be used to personalize tomorrow's schedule.
    """
    today = timezone.localdate() # Get today's date

    # Show the most recent DayLog (usually today)
    day_log = DayLog.objects.filter(date=today).first()

    if request.method == "POST": # Handle form submission
        if not day_log: # If no DayLog exists for today
            return redirect("planner") # Redirect to planner view

        reflection_text = request.POST.get("reflection", "").strip() # Get reflection text from form
        em = request.POST.get("energy_morning") or None # Get morning energy rating
        ea = request.POST.get("energy_afternoon") or None # Get afternoon energy rating
        en = request.POST.get("energy_evening") or None # Get evening energy rating

        day_log.reflection_text = reflection_text # Update reflection text
        day_log.energy_morning = int(em) if em else None # Update morning energy rating
        day_log.energy_afternoon = int(ea) if ea else None # Update afternoon energy rating
        day_log.energy_evening = int(en) if en else None # Update evening energy rating
        day_log.save() # Save the updated DayLog

        return redirect("planner") # Redirect to planner view

    return render( # Render the reflection template
        request, # Request object
        "planner/reflection.html", # Template name
        {"day_log": day_log, "today": today}, # Context data
    )

from .models import UserPreferences # Import UserPreferences model

def preferences_view(request): # View for user preferences
    prefs, created = UserPreferences.objects.get_or_create(singleton=True) # Get or create UserPreferences singleton

    if request.method == "POST": # Handle form submission
        # Get values
        prefs.preferred_sleep_time = request.POST.get("sleep_time") or None # Update preferred sleep time
        prefs.preferred_wake_time = request.POST.get("wake_time") or None # Update preferred wake time

        prefs.max_study_hours = request.POST.get("max_study_hours") or None # Update max study hours
        prefs.break_frequency_minutes = request.POST.get("break_frequency") or None # Update break frequency

        prefs.preferred_focus_period = request.POST.get("focus_period") or None # Update preferred focus period
        prefs.study_style = request.POST.get("study_style") or None # Update study style
        prefs.stress_sensitivity = request.POST.get("stress_sensitivity") or None # Update stress sensitivity

        prefs.plays_sport = bool(request.POST.get("plays_sport")) # Update plays sport preference

        prefs.save() # Save the updated preferences

        return redirect("planner") # Redirect to planner view

    return render(request, "planner/preferences.html", {"prefs": prefs}) # Render the preferences template

def export_ics(request): # View to export schedule as .ics file
    """
    Export today's AI schedule as an .ics calendar file.
    Works with Google Calendar, Apple Calendar, Outlook, etc.
    """
    today = timezone.localdate() # Get today's date

    # Get today's saved plan (we stored it earlier in DayLog for reflections)
    day_log = DayLog.objects.filter(date=today).first()
    if not day_log or not day_log.schedule_json: # If no schedule found for today
        return HttpResponse( # Return error response
            "No schedule found for today. Generate a plan first.",
            status=400, # Bad Request status
            content_type="text/plain", # Plain text content type
        )

    schedule = day_log.schedule_json  # should already be a Python list

    # (Optional safety: handle older rows that might be strings)
    if isinstance(schedule, str):
        try: # Try to parse the schedule string as JSON
            schedule = json.loads(schedule) # Parse JSON string
        except Exception: # If parsing fails
            schedule = [] # Default to empty list

    lines = [ # List to hold lines of the .ics file
        "BEGIN:VCALENDAR", # ICS header
        "VERSION:2.0", # ICS version
        "PRODID:-//Yeskala//AI Time Planner//EN", # Product identifier
        "CALSCALE:GREGORIAN", # Calendar scale
        "METHOD:PUBLISH", # Method
    ]

    now = timezone.now() # Current timestamp

    def fmt(dt: datetime.datetime) -> str: # Format datetime for ICS
        # Local time, no timezone suffix (good enough for hackathon)
        return dt.strftime("%Y%m%dT%H%M%S") # Return formatted datetime string

    for idx, block in enumerate(schedule): # Iterate over each block in the schedule
        task = block.get("task", "Block") # Get task name or default to "Block"
        start_str = block.get("start") # Get start time string
        end_str = block.get("end") # Get end time string

        if not start_str or not end_str: # If start or end time is missing
            continue # Skip this block

        try: # Try to parse start and end times
            sh, sm = map(int, start_str.split(":")) # Parse start time
            eh, em = map(int, end_str.split(":")) # Parse end time
        except ValueError: # If parsing fails
            continue # Skip this block

        start_dt = datetime.datetime.combine(today, datetime.time(sh, sm)) # Combine date and start time
        end_dt = datetime.datetime.combine(today, datetime.time(eh, em)) # Combine date and end time

        # You can choose to skip breaks, or keep everything. Here we include all.
        lines.extend([ 
            "BEGIN:VEVENT", # Event start
            f"UID:{today.strftime('%Y%m%d')}-{idx}@yeskala", # Unique identifier
            f"DTSTAMP:{fmt(now)}", # Timestamp
            f"DTSTART:{fmt(start_dt)}", # Event start time
            f"DTEND:{fmt(end_dt)}", # Event end time
            f"SUMMARY:{task}", # Event summary
        ])

        note = block.get("note") # Get event note
        if note: # If note exists
            # Escape special chars for ICS
            desc = (
                note.replace("\\", "\\\\") # Escape backslashes
                    .replace("\n", "\\n") # Escape newlines
                    .replace(",", "\\,") # Escape commas
                    .replace(";", "\\;") # Escape semicolons
            )
            lines.append(f"DESCRIPTION:{desc}") # Add description line

        lines.append("END:VEVENT") # Event end

    lines.append("END:VCALENDAR") # ICS footer
    ics_content = "\r\n".join(lines) # Join lines with CRLF

    response = HttpResponse(ics_content, content_type="text/calendar") # Create HTTP response with ICS content
    response["Content-Disposition"] = 'attachment; filename=\"yeskala_day_plan.ics\"' # Set content disposition for file download
    return response # Return the response

def google_auth_start(request): # View to start Google OAuth flow
    """
    Start Google OAuth flow - redirect user to Google consent screen.
    """
    flow = Flow.from_client_secrets_file( # Create OAuth flow from client secrets file
        str(settings.GOOGLE_CLIENT_SECRET_FILE), # Path to client secrets file
        scopes=settings.GOOGLE_SCOPES, # Scopes for OAuth
        redirect_uri=settings.GOOGLE_OAUTH_REDIRECT_URI,  # Redirect URI after consent
    )

    auth_url, state = flow.authorization_url( # Generate authorization URL
        access_type="offline", # Request offline access for refresh token
        include_granted_scopes="true", # Include previously granted scopes
        prompt="consent", # Always prompt for consent
    )

    # Save state in session for security
    request.session["google_oauth_state"] = state # Store state in session
    return redirect(auth_url) # Redirect user to Google consent screen


def google_auth_callback(request): # View to handle Google OAuth callback
    """
    Google redirects here after user accepts/denies.
    We exchange the code for tokens and store them in session.
    """
    state = request.session.get("google_oauth_state") # Retrieve state from session
    if not state: # If state is missing
        return redirect("planner") # Redirect to planner view

    flow = Flow.from_client_secrets_file( # Create OAuth flow from client secrets file
        str(settings.GOOGLE_CLIENT_SECRET_FILE), # Path to client secrets file
        scopes=settings.GOOGLE_SCOPES, # Scopes for OAuth
        redirect_uri=settings.GOOGLE_OAUTH_REDIRECT_URI, # Redirect URI after consent
        state=state, # State for security
    )

    # Exchange auth code for tokens
    flow.fetch_token(authorization_response=request.build_absolute_uri()) # Fetch tokens using authorization response
    credentials = flow.credentials # Get credentials from the flow

    # Store credentials in session (good enough for hackathon demo)
    request.session["google_credentials"] = {
        "token": credentials.token, # Access token
        "refresh_token": credentials.refresh_token, # Refresh token
        "token_uri": credentials.token_uri, # Token URI
        "client_id": credentials.client_id, # Client ID
        "client_secret": credentials.client_secret, # Client secret
        "scopes": list(credentials.scopes), # Scopes
    }

    return redirect("planner") # Redirect to planner view


def add_to_google_calendar(request): # View to add schedule to Google Calendar
    """
    Take today's AI schedule and create events in user's Google Calendar.
    If not connected yet, start OAuth flow.
    """
    creds_data = request.session.get("google_credentials") # Retrieve Google credentials from session
    if not creds_data: # If credentials are missing
        # Not connected → go through Google login
        return redirect("google_auth_start") # Redirect to start Google OAuth flow

    creds = Credentials( # Create Credentials object from session data
        token=creds_data["token"], # Access token
        refresh_token=creds_data.get("refresh_token"), # Refresh token
        token_uri=creds_data["token_uri"], # Token URI
        client_id=creds_data["client_id"], # Client ID
        client_secret=creds_data["client_secret"], # Client secret
        scopes=creds_data["scopes"], # Scopes
    )

    # Build Calendar API client
    service = build("calendar", "v3", credentials=creds) # Build Google Calendar API client

    today = timezone.localdate() # Get today's date
    day_log = DayLog.objects.filter(date=today).first() # Fetch today's DayLog
    if not day_log or not day_log.schedule_json: # If no schedule found for today
        return HttpResponse("No schedule found for today. Generate a plan first.", status=400) # Return error response

    schedule = day_log.schedule_json # should already be a Python list

    events_created = 0 # Counter for created events

    for block in schedule:
        # Skip breaks if you don't want them as events

        start_str = block.get("start") # Get start time string
        end_str = block.get("end") # Get end time string
        if not start_str or not end_str: # If start or end time is missing
            continue # Skip this block

        try: # Try to parse start and end times
            sh, sm = map(int, start_str.split(":")) # Parse start time
            eh, em = map(int, end_str.split(":")) # Parse end time
        except ValueError: # If parsing fails
            continue # Skip this block

        start_dt = datetime.datetime.combine(today, datetime.time(sh, sm)) # Combine date and start time
        end_dt = datetime.datetime.combine(today, datetime.time(eh, em)) # Combine date and end time

        # Make timezone-aware in your Django TZ
        start_iso = timezone.make_aware(start_dt).isoformat() # Convert start time to ISO format
        end_iso = timezone.make_aware(end_dt).isoformat() # Convert end time to ISO format

        event_body = { # Prepare event body for Google Calendar
            "summary": block.get("task", "Study block"), # Event summary
            "description": block.get("note", ""), # Event description
            "start": {"dateTime": start_iso}, # Event start time
            "end": {"dateTime": end_iso}, # Event end time
        } 

        try: # Try to create the event in Google Calendar
            service.events().insert(calendarId="primary", body=event_body).execute() # Insert event into primary calendar
            events_created += 1 # Increment created events counter
        except Exception as e: # If an error occurs
            # For hackathon, just log errors to console
            print("Error creating event:", e) # Print error message

    return HttpResponse(f"Added {events_created} events to your Google Calendar!") # Return success response

from .models import SavedTask # Import SavedTask model


def task_library_view(request): # View for managing task library
    if request.method == "POST": # Handle form submission
        name = request.POST.get("name", "").strip() # Get task name from form
        duration = request.POST.get("duration", "30") # Get task duration from form
        importance = request.POST.get("importance", "2") # Get task importance from form
        category = request.POST.get("category", "").strip() # Get task category from form

        if name: # If task name is provided
            SavedTask.objects.create( # Create a new SavedTask
                name=name, # Task name
                default_duration_minutes=int(duration), # Task duration
                default_importance=int(importance), # Task importance
                category=category # Task category
            )

        return redirect("task_library") # Redirect to task library view

    tasks = SavedTask.objects.all() # Fetch all saved tasks
    return render(request, "planner/task_library.html", {"tasks": tasks}) # Render the task library template with tasks


def delete_saved_task(request, task_id): # View to delete a saved task
    SavedTask.objects.filter(id=task_id).delete() # Delete the specified SavedTask
    return redirect("task_library") # Redirect to task library view

def history_view(request): # View for displaying history of DayLogs
    # Get all DayLogs in reverse order (newest first)
    logs = DayLog.objects.order_by("-date") # Fetch all DayLogs ordered by date descending

    return render(request, "planner/history.html", { # Render the history template with logs
        "logs": logs 
    })
