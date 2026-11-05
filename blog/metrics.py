"""Successful business operations; no user data or IDs in metric labels."""

from prometheus_client import Counter


POSTS_CREATED = Counter(
    "blog_posts_created_total", "Successfully created posts through Blog."
)
COMMENTS_CREATED = Counter(
    "blog_comments_created_total", "Successfully added comments through Blog."
)
USER_REGISTRATIONS = Counter(
    "blog_user_registrations_total", "Successful registrations through Blog."
)
SUBSCRIPTIONS_CREATED = Counter(
    "blog_subscriptions_created_total", "Successfully created subscriptions through Blog."
)

# Only validated submissions reach the persistence step. No personal labels.
BUSINESS_ATTEMPTS = Counter(
    "blog_business_attempts_total", "Validated submissions attempting persistence.",
    ["operation"],
)
for operation in ("post", "comment", "registration"):
    BUSINESS_ATTEMPTS.labels(operation)
