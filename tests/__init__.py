import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "chronos_site.settings")

import django  # noqa: E402

django.setup()
