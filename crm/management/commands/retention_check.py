"""Daily housekeeping for the privacy rules. Run from cron, e.g.:

    docker compose exec -T web python manage.py retention_check

* tells admins (in-app) how many student records are past the retention period;
* removes old in-app notifications (> 1 year) and email-log entries older than the retention period;
* removes uploads that were never imported (> 1 day).

It never anonymises on its own: an admin decides on the Privacy page.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.urls import reverse
from django.utils import timezone

from crm import privacy
from crm.models import ImportBatch, Notification, OutgoingEmail


class Command(BaseCommand):
    help = "Flag records past the retention period and clean up old logs."

    def handle(self, *args, **options):
        from django.contrib.auth.models import User

        now = timezone.now()
        due = privacy.due_for_anonymisation(now)
        url = reverse("staff:privacy")
        if due:
            message = f"{len(due)} student record(s) are past the retention period. Review them on the Privacy page."
            admins = User.objects.filter(is_active=True, groups__name="Admin").distinct()
            for admin in admins:
                # One open reminder per admin is enough.
                Notification.objects.filter(user=admin, url=url, read_at__isnull=True).delete()
                Notification.objects.create(user=admin, message=message, url=url)
        notifications = Notification.objects.filter(created_at__lt=now - timedelta(days=365)).delete()[0]
        emails = OutgoingEmail.objects.filter(created_at__lt=privacy.retention_cutoff(now)).delete()[0]
        uploads = ImportBatch.objects.filter(status=ImportBatch.Status.UPLOADED, created_at__lt=now - timedelta(days=1)).delete()[0]
        self.stdout.write(f"Due for anonymisation: {len(due)}; removed {notifications} old notifications, "
                          f"{emails} old email-log entries, {uploads} stale uploads.")
