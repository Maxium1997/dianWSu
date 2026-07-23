from decimal import Decimal

from django.db import models, transaction
from django.utils import timezone

from auditlog.models import AuditEvent
from auditlog.services import log_event

from .models import (
    Bill, BillLineItem, BillMeterReading, BillPayment, BillSnapshot,
    BillTenantPermission, ElectricityRate, Lease, LeaseCharge, LeaseTenant,
)


def can_manage_property(user, property_):
    return user.is_superuser or property_.owner_id == user.id or property_.memberships.filter(user=user).exists()


def can_manage_lease(user, lease):
    return can_manage_property(user, lease.unit.property)


def is_lease_tenant(user, lease):
    return lease.lease_tenants.filter(tenant__user=user, status='active').exists()


def can_access_bill(user, bill):
    """Bill access starts on a tenant's billing-effective date or a lease-level fill authorization."""
    if can_manage_lease(user, bill.lease):
        return True
    default_access = LeaseTenant.objects.filter(
        lease=bill.lease,
        tenant__user=user,
        status=LeaseTenant.Status.ACTIVE,
        billing_access_start_date__lte=bill.period,
    ).exists()
    if default_access:
        return True
    if bill.tenant_fill_enabled and is_lease_tenant(user, bill.lease):
        return True
    return BillTenantPermission.objects.filter(
        bill=bill,
        tenant__tenant__user=user,
        tenant__status=LeaseTenant.Status.ACTIVE,
    ).filter(
        models.Q(expires_on__isnull=True) | models.Q(expires_on__gte=timezone.localdate())
    ).exists()


def can_fill_bill(user, bill):
    if bill.status != Bill.Status.DRAFT:
        return False
    default_access = LeaseTenant.objects.filter(
        lease=bill.lease,
        tenant__user=user,
        status=LeaseTenant.Status.ACTIVE,
        billing_access_start_date__lte=bill.period,
    ).exists()
    if default_access:
        return True
    if bill.tenant_fill_enabled and is_lease_tenant(user, bill.lease):
        return True
    return BillTenantPermission.objects.filter(
        bill=bill,
        tenant__tenant__user=user,
        tenant__status=LeaseTenant.Status.ACTIVE,
    ).filter(
        models.Q(expires_on__isnull=True) | models.Q(expires_on__gte=timezone.localdate())
    ).exists()


def bill_payload(bill):
    items = list(bill.items.order_by('sort_order', 'id').values('item_type', 'name', 'amount', 'tenant_editable'))
    payload = {
        'period': bill.period.isoformat(),
        'due_date': bill.due_date.isoformat(),
        'status': bill.status,
        'total_amount': str(bill.total_amount),
        'items': [{**item, 'amount': str(item['amount'])} for item in items],
    }
    try:
        meter = bill.meter_reading
        payload['meter_reading'] = {
            'reading_date': meter.reading_date.isoformat(),
            'previous_reading': str(meter.previous_reading) if meter.previous_reading is not None else None,
            'current_reading': str(meter.current_reading) if meter.current_reading is not None else None,
            'photo': meter.photo.name if meter.photo else '',
        }
    except BillMeterReading.DoesNotExist:
        pass
    try:
        payment = bill.payment
        payload['payment'] = {
            'method': payment.method,
            'receipt': payment.receipt.name if payment.receipt else '',
            'submitted_at': payment.submitted_at.isoformat(),
            'confirmed_at': payment.confirmed_at.isoformat() if payment.confirmed_at else None,
        }
    except BillPayment.DoesNotExist:
        pass
    return payload


def snapshot_bill(bill, event_type, *, actor=None, note='', request=None):
    snapshot = BillSnapshot.objects.create(
        bill=bill,
        event_type=event_type,
        payload=bill_payload(bill),
        note=note,
        actor=actor,
    )
    log_event(
        f'rental.bill.{event_type}',
        category=AuditEvent.Category.SYSTEM,
        message=f'租賃帳單流程：{event_type}',
        request=request,
        actor=actor,
        metadata={'bill_id': bill.id, 'lease_id': bill.lease_id, 'period': bill.period.isoformat()},
    )
    return snapshot


def rate_for_period(lease, period):
    for rate in lease.electricity_rates.all():
        if rate.applies_to(period.month):
            return rate.rate_per_kwh
    return Decimal('0')


@transaction.atomic
def create_bill(lease, period, *, actor=None, request=None):
    period = period.replace(day=1)
    bill, created = Bill.objects.get_or_create(
        lease=lease,
        period=period,
        defaults={'due_date': lease.due_date_for(period)},
    )
    if not created:
        return bill, False

    BillLineItem.objects.create(
        bill=bill,
        item_type=BillLineItem.ItemType.RENT,
        name='租金',
        amount=lease.monthly_rent,
        tenant_editable=False,
        sort_order=10,
    )
    BillLineItem.objects.create(
        bill=bill,
        item_type=BillLineItem.ItemType.ELECTRICITY,
        name='電費',
        amount=Decimal('0'),
        tenant_editable=True,
        sort_order=20,
    )
    for index, charge in enumerate(lease.recurring_charges.filter(enabled=True), start=30):
        item_type = {
            LeaseCharge.ChargeType.WATER: BillLineItem.ItemType.WATER,
            LeaseCharge.ChargeType.GAS: BillLineItem.ItemType.GAS,
            LeaseCharge.ChargeType.MANAGEMENT: BillLineItem.ItemType.MANAGEMENT,
        }.get(charge.charge_type, BillLineItem.ItemType.OTHER)
        BillLineItem.objects.create(
            bill=bill,
            item_type=item_type,
            name=charge.name,
            amount=charge.default_amount,
            tenant_editable=charge.tenant_editable,
            sort_order=index,
        )
    snapshot_bill(bill, 'created', actor=actor, request=request)
    return bill, True


def generate_current_bills(*, actor=None, request=None):
    period = timezone.localdate().replace(day=1)
    count = 0
    leases = Lease.objects.filter(
        status=Lease.Status.ACTIVE,
        start_date__lte=period,
        end_date__gte=period,
    ).select_related('unit__property').prefetch_related('recurring_charges', 'electricity_rates')
    for lease in leases:
        _, created = create_bill(lease, period, actor=actor, request=request)
        count += int(created)
    return count


@transaction.atomic
def submit_bill_for_review(bill, *, actor, request=None, note=''):
    bill.status = Bill.Status.SUBMITTED
    bill.submitted_at = timezone.now()
    bill.save(update_fields=['status', 'submitted_at', 'updated_at'])
    snapshot_bill(bill, 'tenant_submitted', actor=actor, request=request, note=note)


@transaction.atomic
def confirm_bill(bill, *, actor, request=None, note=''):
    bill.status = Bill.Status.CONFIRMED
    bill.confirmed_at = timezone.now()
    bill.save(update_fields=['status', 'confirmed_at', 'updated_at'])
    snapshot_bill(bill, 'manager_confirmed', actor=actor, request=request, note=note)


@transaction.atomic
def submit_payment(bill, *, actor, method, receipt=None, note='', request=None):
    payment, _ = BillPayment.objects.update_or_create(
        bill=bill,
        defaults={'method': method, 'receipt': receipt, 'submitted_by': actor, 'note': note},
    )
    payment.full_clean()
    payment.save()
    bill.status = Bill.Status.PAYMENT_SUBMITTED
    bill.save(update_fields=['status', 'updated_at'])
    snapshot_bill(bill, 'payment_submitted', actor=actor, request=request, note=note)
    return payment


@transaction.atomic
def confirm_payment(bill, *, actor, request=None, note=''):
    payment = bill.payment
    payment.confirmed_by = actor
    payment.confirmed_at = timezone.now()
    payment.save(update_fields=['confirmed_by', 'confirmed_at'])
    bill.status = Bill.Status.PAID
    bill.paid_at = timezone.now()
    bill.save(update_fields=['status', 'paid_at', 'updated_at'])
    snapshot_bill(bill, 'payment_confirmed', actor=actor, request=request, note=note)
