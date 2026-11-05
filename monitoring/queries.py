"""Shared MetricsQL definitions for dashboard generation and live verification."""

BUSINESS = {
    "post": ("blog_posts_created_total", "Публикации"),
    "comment": ("blog_comments_created_total", "Комментарии"),
    "registration": ("blog_user_registrations_total", "Регистрации"),
}


def ratio(operation, window):
    success = BUSINESS[operation][0]
    attempts = f'sum(increase(blog_business_attempts_total{{job="blog-web",operation="{operation}"}}[{window}]))'
    # Zero traffic stays absent. Do not turn 0/0 into a fabricated 100%.
    return f'100 * sum(increase({success}{{job="blog-web"}}[{window}])) / ({attempts} > 0)'


P95 = 'histogram_quantile(0.95, sum(rate(django_http_requests_latency_seconds_by_view_method_bucket{job="blog-web",view=~"index|post_view",method="GET"}[2m])) by (le))'
# Fixed 15-second slots. Missing/old observations become bad slots after first
# installation. The 7-day guard excludes time before installation, matching VM retention.
GOOD_SLOT = '''(
  (min(last_over_time(blog_probe_round_good{job="blog-prober"}[30s])) default vector(0))
  * (min(last_over_time(up{job="blog-prober"}[30s])) default vector(0))
  * ((time() - max(last_over_time(blog_probe_last_run_timestamp_seconds{job="blog-prober"}[30s])) < bool 30) default vector(0))
) if (count(last_over_time(blog_probe_started_timestamp_seconds{job="blog-prober"}[7d])) > 0)'''


def tbslo(window):
    return f'100 * avg_over_time(({GOOD_SLOT})[{window}:15s])'


def sla_ok(window):
    obligations = [f'({ratio(op, window)} >= bool 99)' for op in BUSINESS]
    obligations.append(f'({tbslo(window)} >= bool 99)')
    # Absent business traffic means no overall verdict, not a pass.
    return ' * '.join(obligations)
