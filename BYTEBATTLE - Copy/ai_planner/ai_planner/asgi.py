"""
ASGI config for ai_planner project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os # Import os module to interact with the operating system

from django.core.asgi import get_asgi_application # Import ASGI application function from Django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ai_planner.settings") # Set default settings module for Django

application = get_asgi_application() # Get the ASGI application instance
