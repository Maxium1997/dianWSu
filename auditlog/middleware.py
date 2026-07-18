import logging

from .models import AuditEvent
from .services import log_event

logger = logging.getLogger('auditlog.security')


class SecurityAuditMiddleware:
    """Records security-relevant responses without tracking ordinary page views."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            response = self.get_response(request)
        except Exception:
            log_event(
                'system.unhandled_exception',
                category=AuditEvent.Category.SYSTEM,
                severity=AuditEvent.Severity.CRITICAL,
                message='未處理的應用程式例外',
                request=request,
            )
            logger.exception('Unhandled application exception at %s', request.path)
            raise

        if response.status_code in {401, 403}:
            log_event(
                'security.access_denied',
                category=AuditEvent.Category.SECURITY,
                severity=AuditEvent.Severity.WARNING,
                message='未授權或拒絕存取',
                request=request,
                status_code=response.status_code,
            )
        return response
