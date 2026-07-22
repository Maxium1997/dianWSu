from django.contrib import admin

from .models import (
    Announcement, Bill, BillLineItem, BillMeterReading, BillPayment, BillSnapshot,
    ElectricityRate, Lease, LeaseCharge, LeaseDocument, LeaseTenant,
    MaintenanceAttachment, MaintenanceRequest, Property, PropertyMembership,
    TenantInvitation, TenantProfile, Unit, UnitAmenity, UnitPhoto,
)


class UnitAmenityInline(admin.TabularInline):
    model = UnitAmenity
    extra = 1


class UnitPhotoInline(admin.TabularInline):
    model = UnitPhoto
    extra = 0
    max_num = 6


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = ('name', 'owner', 'address', 'status', 'updated_at')
    list_filter = ('status',)
    search_fields = ('name', 'address', 'owner__username', 'owner__email')


@admin.register(PropertyMembership)
class PropertyMembershipAdmin(admin.ModelAdmin):
    list_display = ('property', 'user', 'role', 'created_at')
    list_filter = ('role',)
    search_fields = ('property__name', 'user__username', 'user__email')


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ('number', 'property', 'floor', 'room_type', 'status')
    list_filter = ('status', 'property')
    search_fields = ('number', 'property__name')
    inlines = [UnitAmenityInline, UnitPhotoInline]


@admin.register(TenantProfile)
class TenantProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'phone', 'emergency_contact_name', 'updated_at')
    search_fields = ('user__username', 'user__email', 'phone')


class LeaseTenantInline(admin.TabularInline):
    model = LeaseTenant
    extra = 0


class LeaseChargeInline(admin.TabularInline):
    model = LeaseCharge
    extra = 0


class ElectricityRateInline(admin.TabularInline):
    model = ElectricityRate
    extra = 0


class LeaseDocumentInline(admin.TabularInline):
    model = LeaseDocument
    extra = 0


@admin.register(Lease)
class LeaseAdmin(admin.ModelAdmin):
    list_display = ('unit', 'start_date', 'end_date', 'monthly_rent', 'due_day', 'status')
    list_filter = ('status',)
    search_fields = ('unit__number', 'unit__property__name')
    inlines = [LeaseTenantInline, LeaseChargeInline, ElectricityRateInline, LeaseDocumentInline]


@admin.register(TenantInvitation)
class TenantInvitationAdmin(admin.ModelAdmin):
    list_display = ('invited_name', 'lease', 'expires_at', 'accepted_by', 'accepted_at', 'created_by')
    list_filter = ('accepted_at',)
    search_fields = ('invited_name', 'invited_email', 'lease__unit__number')
    readonly_fields = ('token', 'accepted_by', 'accepted_at', 'created_at')


class BillLineItemInline(admin.TabularInline):
    model = BillLineItem
    extra = 0


class BillSnapshotInline(admin.TabularInline):
    model = BillSnapshot
    extra = 0
    readonly_fields = ('event_type', 'payload', 'note', 'actor', 'created_at')
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Bill)
class BillAdmin(admin.ModelAdmin):
    list_display = ('lease', 'period', 'due_date', 'status', 'total_amount', 'updated_at')
    list_filter = ('status', 'period')
    search_fields = ('lease__unit__number', 'lease__unit__property__name')
    inlines = [BillLineItemInline, BillSnapshotInline]


@admin.register(BillMeterReading)
class BillMeterReadingAdmin(admin.ModelAdmin):
    list_display = ('bill', 'reading_date', 'previous_reading', 'current_reading', 'recorded_by')


@admin.register(BillPayment)
class BillPaymentAdmin(admin.ModelAdmin):
    list_display = ('bill', 'method', 'submitted_by', 'submitted_at', 'confirmed_by', 'confirmed_at')
    list_filter = ('method',)


@admin.register(MaintenanceRequest)
class MaintenanceRequestAdmin(admin.ModelAdmin):
    list_display = ('title', 'unit', 'status', 'assigned_to', 'created_by', 'created_at')
    list_filter = ('status',)
    search_fields = ('title', 'unit__number', 'unit__property__name')


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ('title', 'property', 'published_at', 'expires_at', 'created_by')
    search_fields = ('title', 'content', 'property__name')


admin.site.register([UnitAmenity, UnitPhoto, LeaseTenant, LeaseCharge, ElectricityRate, LeaseDocument, MaintenanceAttachment])
