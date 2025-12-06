import json
import datetime
from typing import Optional

from django.shortcuts import render, redirect
from django.conf import settings
from django.utils import timezone
from django.http import HttpResponse
from openai import OpenAI

from .models import DayLog
from .models import UserPreferences
from .models import SavedTask

from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials


# OpenAI client using key from settings.py
client = OpenAI(api_key=settings.OPENAI_API_KEY)


def build_prompt(user_text: str, previous_summary: Optional[str] = None) -> str:
    """
    Build a prompt where the user gives a free-text description of:
    - who they are
    - how they feel today
    - their tasks, deadlines, constraints, preferences
    Optionally includes a summary of yesterday's plan + reflection.
    """
    lines = [
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
        user_text,
        "=== USER DESCRIPTION END ===",
    ]

    if previous_summary:
        lines += [
            "",
            "=== PAST DAY REFLECTION (YESTERDAY) ===",
            previous_summary,
            (
                "Use this information to calibrate today's plan realistically. "
                "If they consistently overestimated last time, schedule slightly less intense blocks, "
                "move the hardest tasks into their best energy windows, and protect their rest."
            ),
        ]

    lines += [
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

    return "\n".join(lines)




def call_openai_schedule(prompt: str):
    """
    Call OpenAI to generate the schedule.
    Expects a JSON object: { "schedule": [...], "coach_note": "..." }
    """
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured in settings.py")

    resp = client.chat.completions.create(
        model="gpt-4o",  # or "gpt-5-large" if you want stronger
        temperature=0.4,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an expert AI daily schedule planner and coach for students. "
                    "You are careful, realistic, and supportive."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    )

    content = resp.choices[0].message.content  # JSON string
    data = json.loads(content)

    schedule = data.get("schedule", [])
    if not isinstance(schedule, list):
        schedule = []

    schedule = validate_schedule(schedule)

    coach_note = data.get("coach_note", "")
    mood = data.get("mood", {})

    return schedule, coach_note, content, mood


def planner_view(request):
    schedule = None
    coach_note = None
    raw_model_output = None
    error = None
    mood = None

    today = timezone.localdate()
    form_defaults = {"description": "",}

    load_str = request.GET.get("load")
    if load_str and request.method == "GET":
        try:
            load_date = datetime.date.fromisoformat(load_str)  # expects YYYY-MM-DD
            log = DayLog.objects.filter(date=load_date).first()
            if log:
                form_defaults["description"] = log.description
                schedule = log.schedule_json
                coach_note = log.coach_note
        except ValueError:
            # ignore bad load param and just render normal
            pass

    if request.method == "POST":
        description = request.POST.get("description", "").strip()
        form_defaults["description"] = description

        # ---- Add selected SavedTasks into the description (task library) ----
        library_tasks = []
        for t in SavedTask.objects.all():
            if request.POST.get(f"library_task_{t.id}"):
                library_tasks.append(t)

        if library_tasks:
            pieces = []
            for t in library_tasks:
                pieces.append(
                    f"{t.name} (about {t.default_duration_minutes} minutes, "
                    f"importance {t.default_importance})"
                )
            library_text = "Extra tasks I selected from my task library: " + "; ".join(pieces) + "."
            # append to description so AI sees it
            description = (description + "\n\n" + library_text).strip()
            form_defaults["description"] = description

        if not description:
            error = "Describe yourself and your day so the AI has something to work with."
        else:
            # ---- Build previous day summary (for personalization) ----
            yesterday = today - datetime.timedelta(days=1)
            previous_summary = None
            yesterday_log = (
                DayLog.objects
                .filter(date=yesterday)
                .exclude(reflection_text="")
                .first()
            )
            if yesterday_log:
                previous_summary = (
                    "Yesterday's plan and reflection:\n"
                    f"- Schedule (JSON): {json.dumps(yesterday_log.schedule_json, ensure_ascii=False)}\n"
                    f"- Reflection: {yesterday_log.reflection_text}\n"
                    f"- Energy (1–10): morning={yesterday_log.energy_morning}, "
                    f"afternoon={yesterday_log.energy_afternoon}, night={yesterday_log.energy_evening}\n"
                )

            pref_summary = None
            prefs = UserPreferences.objects.get_or_create(singleton=True)[0]

            pref_summary = (
                f"User preferences: "
                f"wake={prefs.preferred_wake_time}, "
                f"sleep={prefs.preferred_sleep_time}, "
                f"max_study_hours={prefs.max_study_hours}, "
                f"break_frequency={prefs.break_frequency_minutes} mins, "
                f"focus_period={prefs.preferred_focus_period}, "
                f"study_style={prefs.study_style}, "
                f"stress_sensitivity={prefs.stress_sensitivity}, "
                f"plays_sport={prefs.plays_sport}."
            )

            prompt = build_prompt(description, previous_summary + "\n" + pref_summary if previous_summary else pref_summary)

            try:
                schedule, coach_note, raw_json, mood = call_openai_schedule(prompt)
                raw_model_output = raw_json
                if not schedule:
                    error = "AI did not return any schedule blocks."
                else:
                    # ---- Persist today's plan so we can reflect on it at night ----
                    DayLog.objects.update_or_create(
                        date=today,
                        defaults={
                            "description": description,
                            "schedule_json": schedule,
                            "coach_note": coach_note or "",
                        },
                    )
            except Exception as e:
                error = f"Error contacting AI backend: {e}"
    context = {
        "form": form_defaults,
        "schedule": schedule,
        "coach_note": coach_note,
        "raw_model_output": raw_model_output,
        "error": error,
        "saved_tasks": SavedTask.objects.all(),
        "mood": mood,
    }
    return render(request, "planner/planner.html", context)

def validate_schedule(schedule):
    valid = []
    last_end = None

    for block in schedule:
        if not block.get("start") or not block.get("end"):
            continue
        
        if last_end and block["start"] < last_end:
            # fix overlap by adjusting start
            block["start"] = last_end
        
        last_end = block["end"]
        valid.append(block)
    
    return valid

def reflection_view(request):
    """
    Simple end-of-day reflection page.
    User rates energy + writes how the day actually went.
    This will be used to personalize tomorrow's schedule.
    """
    today = timezone.localdate()

    # Show the most recent DayLog (usually today)
    day_log = DayLog.objects.filter(date=today).first()

    if request.method == "POST":
        if not day_log:
            return redirect("planner")

        reflection_text = request.POST.get("reflection", "").strip()
        em = request.POST.get("energy_morning") or None
        ea = request.POST.get("energy_afternoon") or None
        en = request.POST.get("energy_evening") or None

        day_log.reflection_text = reflection_text
        day_log.energy_morning = int(em) if em else None
        day_log.energy_afternoon = int(ea) if ea else None
        day_log.energy_evening = int(en) if en else None
        day_log.save()

        return redirect("planner")

    return render(
        request,
        "planner/reflection.html",
        {"day_log": day_log, "today": today},
    )

from .models import UserPreferences

def preferences_view(request):
    prefs, created = UserPreferences.objects.get_or_create(singleton=True)

    if request.method == "POST":
        # Get values
        prefs.preferred_sleep_time = request.POST.get("sleep_time") or None
        prefs.preferred_wake_time = request.POST.get("wake_time") or None

        prefs.max_study_hours = request.POST.get("max_study_hours") or None
        prefs.break_frequency_minutes = request.POST.get("break_frequency") or None

        prefs.preferred_focus_period = request.POST.get("focus_period") or None
        prefs.study_style = request.POST.get("study_style") or None
        prefs.stress_sensitivity = request.POST.get("stress_sensitivity") or None

        prefs.plays_sport = bool(request.POST.get("plays_sport"))

        prefs.save()

        return redirect("planner")

    return render(request, "planner/preferences.html", {"prefs": prefs})

def export_ics(request):
    """
    Export today's AI schedule as an .ics calendar file.
    Works with Google Calendar, Apple Calendar, Outlook, etc.
    """
    today = timezone.localdate()

    # Get today's saved plan (we stored it earlier in DayLog for reflections)
    day_log = DayLog.objects.filter(date=today).first()
    if not day_log or not day_log.schedule_json:
        return HttpResponse(
            "No schedule found for today. Generate a plan first.",
            status=400,
            content_type="text/plain",
        )

    schedule = day_log.schedule_json  # should already be a Python list

    # (Optional safety: handle older rows that might be strings)
    if isinstance(schedule, str):
        try:
            schedule = json.loads(schedule)
        except Exception:
            schedule = []

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Yeskala//AI Time Planner//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]

    now = timezone.now()

    def fmt(dt: datetime.datetime) -> str:
        # Local time, no timezone suffix (good enough for hackathon)
        return dt.strftime("%Y%m%dT%H%M%S")

    for idx, block in enumerate(schedule):
        task = block.get("task", "Block")
        start_str = block.get("start")
        end_str = block.get("end")

        if not start_str or not end_str:
            continue

        try:
            sh, sm = map(int, start_str.split(":"))
            eh, em = map(int, end_str.split(":"))
        except ValueError:
            continue

        start_dt = datetime.datetime.combine(today, datetime.time(sh, sm))
        end_dt = datetime.datetime.combine(today, datetime.time(eh, em))

        # You can choose to skip breaks, or keep everything. Here we include all.
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{today.strftime('%Y%m%d')}-{idx}@yeskala",
            f"DTSTAMP:{fmt(now)}",
            f"DTSTART:{fmt(start_dt)}",
            f"DTEND:{fmt(end_dt)}",
            f"SUMMARY:{task}",
        ])

        note = block.get("note")
        if note:
            # Escape special chars for ICS
            desc = (
                note.replace("\\", "\\\\")
                    .replace("\n", "\\n")
                    .replace(",", "\\,")
                    .replace(";", "\\;")
            )
            lines.append(f"DESCRIPTION:{desc}")

        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    ics_content = "\r\n".join(lines)

    response = HttpResponse(ics_content, content_type="text/calendar")
    response["Content-Disposition"] = 'attachment; filename=\"yeskala_day_plan.ics\"'
    return response

def google_auth_start(request):
    """
    Start Google OAuth flow – redirect user to Google consent screen.
    """
    flow = Flow.from_client_secrets_file(
        str(settings.GOOGLE_CLIENT_SECRET_FILE),
        scopes=settings.GOOGLE_SCOPES,
        redirect_uri=settings.GOOGLE_OAUTH_REDIRECT_URI,
    )

    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )

    # Save state in session for security
    request.session["google_oauth_state"] = state
    return redirect(auth_url)


def google_auth_callback(request):
    """
    Google redirects here after user accepts/denies.
    We exchange the code for tokens and store them in session.
    """
    state = request.session.get("google_oauth_state")
    if not state:
        return redirect("planner")

    flow = Flow.from_client_secrets_file(
        str(settings.GOOGLE_CLIENT_SECRET_FILE),
        scopes=settings.GOOGLE_SCOPES,
        redirect_uri=settings.GOOGLE_OAUTH_REDIRECT_URI,
        state=state,
    )

    # Exchange auth code for tokens
    flow.fetch_token(authorization_response=request.build_absolute_uri())
    credentials = flow.credentials

    # Store credentials in session (good enough for hackathon demo)
    request.session["google_credentials"] = {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": list(credentials.scopes),
    }

    return redirect("planner")


def add_to_google_calendar(request):
    """
    Take today's AI schedule and create events in user's Google Calendar.
    If not connected yet, start OAuth flow.
    """
    creds_data = request.session.get("google_credentials")
    if not creds_data:
        # Not connected → go through Google login
        return redirect("google_auth_start")

    creds = Credentials(
        token=creds_data["token"],
        refresh_token=creds_data.get("refresh_token"),
        token_uri=creds_data["token_uri"],
        client_id=creds_data["client_id"],
        client_secret=creds_data["client_secret"],
        scopes=creds_data["scopes"],
    )

    # Build Calendar API client
    service = build("calendar", "v3", credentials=creds)

    today = timezone.localdate()
    day_log = DayLog.objects.filter(date=today).first()
    if not day_log or not day_log.schedule_json:
        return HttpResponse("No schedule found for today. Generate a plan first.", status=400)

    schedule = day_log.schedule_json

    events_created = 0

    for block in schedule:
        # Skip breaks if you don't want them as events

        start_str = block.get("start")
        end_str = block.get("end")
        if not start_str or not end_str:
            continue

        try:
            sh, sm = map(int, start_str.split(":"))
            eh, em = map(int, end_str.split(":"))
        except ValueError:
            continue

        start_dt = datetime.datetime.combine(today, datetime.time(sh, sm))
        end_dt = datetime.datetime.combine(today, datetime.time(eh, em))

        # Make timezone-aware in your Django TZ
        start_iso = timezone.make_aware(start_dt).isoformat()
        end_iso = timezone.make_aware(end_dt).isoformat()

        event_body = {
            "summary": block.get("task", "Study block"),
            "description": block.get("note", ""),
            "start": {"dateTime": start_iso},
            "end": {"dateTime": end_iso},
        }

        try:
            service.events().insert(calendarId="primary", body=event_body).execute()
            events_created += 1
        except Exception as e:
            # For hackathon, just log errors to console
            print("Error creating event:", e)

    return HttpResponse(f"Added {events_created} events to your Google Calendar!")

from .models import SavedTask


def task_library_view(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        duration = request.POST.get("duration", "30")
        importance = request.POST.get("importance", "2")
        category = request.POST.get("category", "").strip()

        if name:
            SavedTask.objects.create(
                name=name,
                default_duration_minutes=int(duration),
                default_importance=int(importance),
                category=category
            )

        return redirect("task_library")

    tasks = SavedTask.objects.all()
    return render(request, "planner/task_library.html", {"tasks": tasks})


def delete_saved_task(request, task_id):
    SavedTask.objects.filter(id=task_id).delete()
    return redirect("task_library")

def history_view(request):
    # Get all DayLogs in reverse order (newest first)
    logs = DayLog.objects.order_by("-date")

    return render(request, "planner/history.html", {
        "logs": logs
    })
