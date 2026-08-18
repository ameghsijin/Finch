# wsgi.py

import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Finch.settings')

# Auto-start Celery
try:
    from celery_starter import start_celery
    start_celery()
except ImportError:
    pass

application = get_wsgi_application()