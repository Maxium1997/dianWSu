from django.conf import settings
from django.db import models


class AuditEvent(models.Model):
    class Category(models.TextChoices):
        AUTHENTICATION = 'authentication', '帳號驗證'
        SECURITY = 'security', '安全事件'
        SYSTEM = 'system', '系統事件'

    class Severity(models.TextChoices):
        INFO = 'info', '資訊'
        WARNING = 'warning', '警告'
        ERROR = 'error', '錯誤'
        CRITICAL = 'critical', '嚴重'

    created_at = models.DateTimeField('發生時間', auto_now_add=True, db_index=True)
    category = models.CharField('分類', max_length=32, choices=Category.choices, db_index=True)
    event_type = models.CharField('事件類型', max_length=64, db_index=True)
    severity = models.CharField('嚴重度', max_length=16, choices=Severity.choices, default=Severity.INFO, db_index=True)
    message = models.CharField('事件說明', max_length=255)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name='會員',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='audit_events',
    )
    ip_address = models.GenericIPAddressField('來源 IP', null=True, blank=True)
    user_agent = models.CharField('User-Agent', max_length=512, blank=True)
    request_path = models.CharField('請求路徑', max_length=500, blank=True)
    request_method = models.CharField('請求方法', max_length=10, blank=True)
    status_code = models.PositiveSmallIntegerField('回應狀態碼', null=True, blank=True)
    metadata = models.JSONField('補充資料', default=dict, blank=True)

    class Meta:
        verbose_name = '系統日誌'
        verbose_name_plural = '系統日誌'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['category', 'event_type', 'created_at']),
            models.Index(fields=['actor', 'created_at']),
        ]

    def __str__(self):
        return f'{self.created_at:%Y-%m-%d %H:%M:%S} {self.event_type}'
