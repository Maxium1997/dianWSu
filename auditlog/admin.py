from django.contrib import admin

from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'severity', 'category', 'event_type', 'actor', 'ip_address', 'message')
    list_filter = ('severity', 'category', 'event_type', 'created_at')
    search_fields = ('event_type', 'message', 'actor__username', 'actor__email', 'ip_address', 'request_path')
    readonly_fields = (
        'created_at', 'category', 'event_type', 'severity', 'message', 'actor',
        'ip_address', 'user_agent', 'request_path', 'request_method', 'status_code', 'metadata',
    )
    date_hierarchy = 'created_at'
    list_select_related = ('actor',)
    ordering = ('-created_at',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
