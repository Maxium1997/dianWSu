from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from auditlog.models import AuditEvent


class Command(BaseCommand):
    help = 'Delete audit events older than the configured retention period.'

    def handle(self, *args, **options):
        retention_days = settings.AUDIT_LOG_RETENTION_DAYS
        cutoff = timezone.now() - timedelta(days=retention_days)
        deleted_count, _ = AuditEvent.objects.filter(created_at__lt=cutoff).delete()
        self.stdout.write(self.style.SUCCESS(
            f'Deleted {deleted_count} audit events older than {retention_days} days.'
        ))
