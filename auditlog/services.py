import logging

from django.conf import settings

from .models import AuditEvent

logger = logging.getLogger(__name__)

SENSITIVE_KEYS = {
    'access_token', 'authorization', 'client_secret', 'cookie', 'id_token',
    'password', 'refresh_token', 'secret', 'token',
}


def _redact(value):
    if isinstance(value, dict):
        return {
            key: '[redacted]' if key.lower() in SENSITIVE_KEYS else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


def _client_ip(request):
    if settings.TRUST_CLOUDFLARE_PROXY:
        cloudflare_ip = request.META.get('HTTP_CF_CONNECTING_IP', '')
        if cloudflare_ip:
            return cloudflare_ip
    return request.META.get('REMOTE_ADDR') or None


def log_event(event_type, *, category, severity=AuditEvent.Severity.INFO, message, request=None,
              actor=None, status_code=None, metadata=None):
    """Create an audit event without allowing logging failures to affect a request."""
    if request is not None and actor is None and getattr(request, 'user', None) and request.user.is_authenticated:
        actor = request.user

    try:
        return AuditEvent.objects.create(
            category=category,
            event_type=event_type,
            severity=severity,
            message=message,
            actor=actor,
            ip_address=_client_ip(request) if request is not None else None,
            user_agent=(request.META.get('HTTP_USER_AGENT', '')[:512] if request is not None else ''),
            request_path=(getattr(request, 'path', '')[:500] if request is not None else ''),
            request_method=(getattr(request, 'method', '') or ''),
            status_code=status_code,
            metadata=_redact(metadata or {}),
        )
    except Exception:
        logger.exception('Unable to save audit event: %s', event_type)
        return None
