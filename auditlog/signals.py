from allauth.socialaccount.signals import (
    social_account_added,
    social_account_removed,
    social_account_updated,
)
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from .models import AuditEvent
from .services import log_event


@receiver(user_logged_in)
def record_login(sender, request, user, **kwargs):
    log_event(
        'authentication.login_succeeded',
        category=AuditEvent.Category.AUTHENTICATION,
        message='會員登入成功',
        request=request,
        actor=user,
    )


@receiver(user_logged_out)
def record_logout(sender, request, user, **kwargs):
    if user is None:
        return
    log_event(
        'authentication.logout',
        category=AuditEvent.Category.AUTHENTICATION,
        message='會員已登出',
        request=request,
        actor=user,
    )


@receiver(user_login_failed)
def record_failed_login(sender, credentials, request, **kwargs):
    log_event(
        'authentication.login_failed',
        category=AuditEvent.Category.AUTHENTICATION,
        severity=AuditEvent.Severity.WARNING,
        message='會員登入失敗',
        request=request,
    )


def _provider_name(sociallogin):
    return sociallogin.account.provider


@receiver(social_account_added)
def record_social_account_added(sender, request, sociallogin, **kwargs):
    log_event(
        'authentication.social_account_linked',
        category=AuditEvent.Category.AUTHENTICATION,
        message='已連結第三方登入帳號',
        request=request,
        actor=sociallogin.user,
        metadata={'provider': _provider_name(sociallogin)},
    )


@receiver(social_account_updated)
def record_social_account_updated(sender, request, sociallogin, **kwargs):
    log_event(
        'authentication.social_account_refreshed',
        category=AuditEvent.Category.AUTHENTICATION,
        message='第三方登入帳號資料已更新',
        request=request,
        actor=sociallogin.user,
        metadata={'provider': _provider_name(sociallogin)},
    )


@receiver(social_account_removed)
def record_social_account_removed(sender, request, socialaccount, **kwargs):
    log_event(
        'authentication.social_account_unlinked',
        category=AuditEvent.Category.AUTHENTICATION,
        severity=AuditEvent.Severity.WARNING,
        message='已解除第三方登入帳號連結',
        request=request,
        actor=socialaccount.user,
        metadata={'provider': socialaccount.provider},
    )
