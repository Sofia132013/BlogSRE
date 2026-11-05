"""Log successful account sessions without credentials or personal details."""

import logging

from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver


activity_logger = logging.getLogger("blog.activity")


@receiver(user_logged_in)
def log_login(sender, request, user, **kwargs):
    activity_logger.info("auth.login actor_id=%s", user.pk)


@receiver(user_logged_out)
def log_logout(sender, request, user, **kwargs):
    if user is not None:
        activity_logger.info("auth.logout actor_id=%s", user.pk)
