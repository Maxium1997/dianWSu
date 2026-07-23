from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import F, Prefetch, Q
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from auditlog.models import AuditEvent
from auditlog.services import log_event

from .forms import BillTenantPermissionForm, LeaseBillTenantPermissionForm, LeaseBillingSettingsForm, LeaseForm, MaintenanceForm, PaymentForm, PropertyForm, TenantBillForm, TenantInvitationForm, UnitForm
from .models import (
    Announcement, Bill, BillMeterReading, BillPayment, BillTenantPermission, Lease, LeaseDocument, LeaseTenant,
    MaintenanceAttachment, MaintenanceRequest, Property, TenantInvitation, TenantProfile,
    Unit, UnitPhoto,
)
from .services import (
    can_access_bill, can_fill_bill, can_manage_lease, can_manage_property, confirm_bill, confirm_payment,
    is_lease_tenant, snapshot_bill, submit_bill_for_review, submit_payment,
)


def _managed_properties(user):
    return Property.objects.filter(Q(owner=user) | Q(memberships__user=user)).distinct()


def _manager_or_403(user, property_):
    if not can_manage_property(user, property_):
        return HttpResponseForbidden('您沒有管理此物件的權限。')


def _bill_access_or_403(user, bill):
    if not can_access_bill(user, bill):
        return HttpResponseForbidden('您沒有存取此帳單的權限。')


def _accessible_bills(user):
    managed_properties = _managed_properties(user)
    tenant_access = Q(
        lease__lease_tenants__tenant__user=user,
        lease__lease_tenants__status=LeaseTenant.Status.ACTIVE,
        lease__lease_tenants__billing_access_start_date__lte=F('period'),
    )
    granted_access = Q(
        tenant_permissions__tenant__tenant__user=user,
        tenant_permissions__tenant__status=LeaseTenant.Status.ACTIVE,
    ) & (Q(tenant_permissions__expires_on__isnull=True) | Q(tenant_permissions__expires_on__gte=timezone.localdate()))
    return Bill.objects.filter(
        Q(lease__unit__property__in=managed_properties) | tenant_access | granted_access
    ).select_related('lease__unit__property').distinct()


def _apply_unit_display_state(units):
    """Rental state is derived from active leases; operational states remain read-only here."""
    for unit in units:
        unit.active_lease = next(iter(unit.leases.all()), None)
        if unit.active_lease:
            unit.display_status = Unit.Status.OCCUPIED
        elif unit.status in {Unit.Status.MAINTENANCE, Unit.Status.INACTIVE}:
            unit.display_status = unit.status
        else:
            unit.display_status = Unit.Status.AVAILABLE
        unit.display_status_label = Unit.Status(unit.display_status).label


@login_required
def dashboard(request):
    tenant_leases = Lease.objects.filter(
        lease_tenants__tenant__user=request.user,
        lease_tenants__status=LeaseTenant.Status.ACTIVE,
    ).select_related('unit__property').distinct()
    managed_properties = _managed_properties(request.user)
    bills = _accessible_bills(request.user).order_by('-period')[:6]
    return render(request, 'rental/dashboard.html', {
        'tenant_leases': tenant_leases,
        'managed_properties': managed_properties,
        'bills': bills,
        'has_tenant_role': tenant_leases.exists(),
    })


@login_required
def property_list(request):
    today = timezone.localdate()
    properties = _managed_properties(request.user).prefetch_related(
        Prefetch('units__leases', queryset=Lease.objects.filter(
            status=Lease.Status.ACTIVE, start_date__lte=today, end_date__gte=today,
        ).order_by('-start_date')),
    )
    for property_ in properties:
        _apply_unit_display_state(property_.units.all())
    return render(request, 'rental/property_list.html', {'properties': properties})


@login_required
def property_create(request):
    form = PropertyForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        property_ = form.save(commit=False)
        property_.owner = request.user
        property_.save()
        log_event('rental.property.created', category=AuditEvent.Category.SYSTEM, message='已建立租賃物件', request=request, metadata={'property_id': property_.id})
        messages.success(request, '物件已建立。')
        return redirect('rental:property_detail', property_id=property_.id)
    return render(request, 'rental/form.html', {
        'form': form, 'title': '建立物件', 'back_url': reverse('rental:property_list'),
    })


@login_required
def property_detail(request, property_id):
    today = timezone.localdate()
    property_ = get_object_or_404(
        _managed_properties(request.user).prefetch_related(
            Prefetch('units__leases', queryset=Lease.objects.filter(
                status=Lease.Status.ACTIVE, start_date__lte=today, end_date__gte=today,
            ).order_by('-start_date')),
        ),
        pk=property_id,
    )
    _apply_unit_display_state(property_.units.all())
    return render(request, 'rental/property_detail.html', {'property': property_})


@login_required
def property_edit(request, property_id):
    property_ = get_object_or_404(_managed_properties(request.user), pk=property_id)
    form = PropertyForm(request.POST or None, instance=property_)
    if request.method == 'POST' and form.is_valid():
        form.save()
        log_event('rental.property.updated', category=AuditEvent.Category.SYSTEM, message='已更新租賃物件', request=request, metadata={'property_id': property_.id})
        messages.success(request, '物件資料已更新。')
        return redirect('rental:property_detail', property_id=property_.id)
    return render(request, 'rental/form.html', {
        'form': form, 'title': f'編輯 {property_.name}',
        'back_url': reverse('rental:property_detail', args=[property_.id]),
    })


@login_required
def unit_create(request, property_id):
    property_ = get_object_or_404(Property, pk=property_id)
    denied = _manager_or_403(request.user, property_)
    if denied:
        return denied
    form = UnitForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        unit = form.save(commit=False)
        unit.property = property_
        unit.save()
        log_event('rental.unit.created', category=AuditEvent.Category.SYSTEM, message='已建立房間', request=request, metadata={'property_id': property_.id, 'unit_id': unit.id})
        messages.success(request, '房間已建立。可在 Django Admin 補充設備與最多 6 張現況照片。')
        return redirect('rental:property_detail', property_id=property_.id)
    return render(request, 'rental/form.html', {
        'form': form, 'title': f'新增 {property_.name} 的房間',
        'back_url': reverse('rental:property_detail', args=[property_.id]),
    })


@login_required
def unit_edit(request, unit_id):
    unit = get_object_or_404(Unit.objects.select_related('property'), pk=unit_id)
    denied = _manager_or_403(request.user, unit.property)
    if denied:
        return denied
    form = UnitForm(request.POST or None, instance=unit)
    if request.method == 'POST' and form.is_valid():
        form.save()
        log_event('rental.unit.updated', category=AuditEvent.Category.SYSTEM, message='已更新房間資料', request=request, metadata={'property_id': unit.property_id, 'unit_id': unit.id})
        messages.success(request, '房間資料已更新。')
        return redirect('rental:property_detail', property_id=unit.property_id)
    return render(request, 'rental/form.html', {
        'form': form, 'title': f'編輯 {unit.property.name} {unit.number}',
        'back_url': reverse('rental:property_detail', args=[unit.property_id]),
    })


@login_required
def lease_create(request, unit_id):
    unit = get_object_or_404(Unit.objects.select_related('property'), pk=unit_id)
    denied = _manager_or_403(request.user, unit.property)
    if denied:
        return denied
    form = LeaseForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        lease = form.save(commit=False)
        lease.unit = unit
        try:
            lease.full_clean()
        except ValidationError as error:
            form.add_error(None, error)
        else:
            lease.save()
            if lease.status == Lease.Status.ACTIVE:
                unit.status = Unit.Status.OCCUPIED
                unit.save(update_fields=['status'])
            log_event('rental.lease.created', category=AuditEvent.Category.SYSTEM, message='已建立租約', request=request, metadata={'lease_id': lease.id, 'unit_id': unit.id})
            messages.success(request, '租約已建立。現在可以建立租客邀請連結。')
            return redirect('rental:invitation_create')
    return render(request, 'rental/form.html', {
        'form': form, 'title': f'建立 {unit.property.name} {unit.number} 的租約',
        'back_url': reverse('rental:property_detail', args=[unit.property_id]),
    })


@login_required
def lease_billing_settings(request, lease_id):
    lease = get_object_or_404(Lease.objects.select_related('unit__property'), pk=lease_id)
    denied = _manager_or_403(request.user, lease.unit.property)
    if denied:
        return denied
    form = LeaseBillingSettingsForm(request.POST or None, lease=lease)
    if request.method == 'POST' and form.is_valid():
        form.save()
        log_event(
            'rental.lease.billing_settings_updated', category=AuditEvent.Category.SYSTEM,
            message='已更新租約帳務設定', request=request,
            metadata={'lease_id': lease.id, 'unit_id': lease.unit_id},
        )
        messages.success(request, '租約帳務設定已更新，之後產生的帳單會套用新設定。')
        return redirect('rental:property_detail', property_id=lease.unit.property_id)
    return render(request, 'rental/form.html', {
        'form': form, 'title': f'{lease.unit.property.name} {lease.unit.number} 的帳務設定',
        'back_url': reverse('rental:property_detail', args=[lease.unit.property_id]),
        'form_intro': '電費費率可自訂起訖月份，跨年請直接設定起始月份大於結束月份（例如 12 月至 4 月）。設定會套用於之後自動產生的帳單；既有帳單保留原始快照。',
    })


@login_required
def bill_list(request):
    properties = _managed_properties(request.user)
    bills = _accessible_bills(request.user)
    granted_bill_ids = set(BillTenantPermission.objects.filter(
        bill__in=bills,
        tenant__tenant__user=request.user,
        tenant__status=LeaseTenant.Status.ACTIVE,
    ).filter(
        Q(expires_on__isnull=True) | Q(expires_on__gte=timezone.localdate())
    ).values_list('bill_id', flat=True))
    for bill in bills:
        bill.is_historic_fill_grant = bill.id in granted_bill_ids
    return render(request, 'rental/bill_list.html', {'bills': bills, 'properties': properties})


def _lease_months(lease):
    period = date(lease.start_date.year, lease.start_date.month, 1)
    final_period = date(lease.end_date.year, lease.end_date.month, 1)
    while period <= final_period:
        yield period
        period = date(period.year + 1, 1, 1) if period.month == 12 else date(period.year, period.month + 1, 1)


@login_required
def lease_bill_list(request, lease_id):
    lease = get_object_or_404(Lease.objects.select_related('unit__property'), pk=lease_id)
    denied = _manager_or_403(request.user, lease.unit.property)
    if denied:
        return denied

    grant_mode = request.GET.get('grant') == '1' or request.method == 'POST'
    form = LeaseBillTenantPermissionForm(request.POST or None, lease=lease) if grant_mode else None
    if request.method == 'POST' and form.is_valid():
        bills = list(form.cleaned_data['bills'])
        tenant = form.cleaned_data['lease_tenant']
        form.save(granted_by=request.user)
        log_event(
            'rental.bill.tenant_permission_granted', category=AuditEvent.Category.SYSTEM,
            message='已由租約帳單清單授權租客補填', request=request,
            metadata={
                'lease_id': lease.id,
                'lease_tenant_id': tenant.id,
                'bill_ids': [bill.id for bill in bills],
                'expires_on': form.cleaned_data['expires_on'].isoformat() if form.cleaned_data['expires_on'] else None,
            },
        )
        messages.success(request, '已授權租客填補選取的歷史帳單。')
        return redirect('rental:lease_bill_list', lease_id=lease.id)

    bills_by_period = {bill.period: bill for bill in lease.bills.all()}
    entries = [{'period': period, 'bill': bills_by_period.get(period)} for period in _lease_months(lease)]
    return render(request, 'rental/lease_bill_list.html', {
        'lease': lease,
        'entries': entries,
        'grant_mode': grant_mode,
        'permission_form': form,
    })


@login_required
def bill_detail(request, bill_id):
    bill = get_object_or_404(Bill.objects.select_related('lease__unit__property').prefetch_related('items', 'snapshots__actor'), pk=bill_id)
    denied = _bill_access_or_403(request.user, bill)
    if denied:
        return denied
    is_manager = can_manage_lease(request.user, bill.lease)
    is_tenant = is_lease_tenant(request.user, bill.lease) and can_access_bill(request.user, bill)
    return render(request, 'rental/bill_detail.html', {
        'bill': bill,
        'is_manager': is_manager,
        'is_tenant': is_tenant,
        'tenant_form': TenantBillForm(bill=bill) if can_fill_bill(request.user, bill) else None,
        'payment_form': PaymentForm() if is_tenant and bill.status == Bill.Status.CONFIRMED else None,
    })


@login_required
@require_POST
def bill_submit(request, bill_id):
    bill = get_object_or_404(Bill.objects.select_related('lease__unit__property'), pk=bill_id)
    if not can_fill_bill(request.user, bill):
        return HttpResponseForbidden('此帳單目前不可提交。')
    form = TenantBillForm(request.POST, request.FILES, bill=bill)
    if form.is_valid():
        form.save(request.user)
        submit_bill_for_review(bill, actor=request.user, request=request, note=form.cleaned_data['note'])
        messages.success(request, '帳單已提交給管理者確認。')
    else:
        messages.error(request, '帳單資料有誤，請檢查後再提交。')
    return redirect('rental:bill_detail', bill_id=bill.id)


@login_required
@require_POST
def bill_confirm(request, bill_id):
    bill = get_object_or_404(Bill.objects.select_related('lease__unit__property'), pk=bill_id)
    if not can_manage_lease(request.user, bill.lease) or bill.status != Bill.Status.SUBMITTED:
        return HttpResponseForbidden('此帳單目前不可確認。')
    confirm_bill(bill, actor=request.user, request=request, note=request.POST.get('note', ''))
    messages.success(request, '帳單已確認，租客現在可以付款。')
    return redirect('rental:bill_detail', bill_id=bill.id)


@login_required
@require_POST
def bill_payment(request, bill_id):
    bill = get_object_or_404(Bill.objects.select_related('lease__unit__property'), pk=bill_id)
    if not (is_lease_tenant(request.user, bill.lease) and can_access_bill(request.user, bill)) or bill.status != Bill.Status.CONFIRMED:
        return HttpResponseForbidden('此帳單目前不可付款。')
    form = PaymentForm(request.POST, request.FILES)
    if form.is_valid():
        submit_payment(bill, actor=request.user, request=request, **form.cleaned_data)
        messages.success(request, '付款資料已提交，等待管理者確認收款。')
    else:
        messages.error(request, '付款資料有誤，請檢查後再提交。')
    return redirect('rental:bill_detail', bill_id=bill.id)


@login_required
@require_POST
def bill_payment_confirm(request, bill_id):
    bill = get_object_or_404(Bill.objects.select_related('lease__unit__property'), pk=bill_id)
    if not can_manage_lease(request.user, bill.lease) or bill.status != Bill.Status.PAYMENT_SUBMITTED:
        return HttpResponseForbidden('此帳單目前不可確認收款。')
    confirm_payment(bill, actor=request.user, request=request, note=request.POST.get('note', ''))
    messages.success(request, '已確認收款，帳單完成結案。')
    return redirect('rental:bill_detail', bill_id=bill.id)


@login_required
def invitation_accept(request, token):
    invitation = get_object_or_404(TenantInvitation.objects.select_related('lease__unit__property'), token=token)
    if not invitation.is_usable:
        return render(request, 'rental/invitation.html', {'invitation': invitation, 'usable': False})
    if request.method == 'POST':
        profile, _ = TenantProfile.objects.get_or_create(user=request.user)
        LeaseTenant.objects.get_or_create(
            lease=invitation.lease,
            tenant=profile,
            defaults={
                'status': LeaseTenant.Status.ACTIVE,
                'move_in_date': invitation.lease.start_date,
                'billing_access_start_date': invitation.billing_access_start_date or invitation.lease.start_date,
            },
        )
        invitation.accepted_by = request.user
        invitation.accepted_at = timezone.now()
        invitation.save(update_fields=['accepted_by', 'accepted_at'])
        log_event('rental.invitation.accepted', category=AuditEvent.Category.SYSTEM, message='租客已接受租約邀請', request=request, metadata={'invitation_id': invitation.id, 'lease_id': invitation.lease_id})
        messages.success(request, '已完成租約綁定。')
        return redirect('rental:dashboard')
    return render(request, 'rental/invitation.html', {'invitation': invitation, 'usable': True})


@login_required
def invitation_list(request):
    invitations = TenantInvitation.objects.filter(
        lease__unit__property__in=_managed_properties(request.user)
    ).select_related('lease__unit__property', 'accepted_by')
    return render(request, 'rental/invitation_list.html', {'invitations': invitations})


@login_required
def invitation_create(request):
    form = TenantInvitationForm(request.POST or None, manager=request.user)
    if request.method == 'POST' and form.is_valid():
        invitation = form.save(created_by=request.user)
        log_event('rental.invitation.created', category=AuditEvent.Category.SYSTEM, message='已建立租客邀請連結', request=request, metadata={'invitation_id': invitation.id, 'lease_id': invitation.lease_id})
        messages.success(request, '邀請連結已建立，有效期限為 3 天。')
        return redirect('rental:invitation_list')
    return render(request, 'rental/form.html', {
        'form': form, 'title': '建立租客邀請', 'back_url': reverse('rental:invitation_list'),
    })


@login_required
def bill_tenant_permission_create(request):
    form = BillTenantPermissionForm(request.POST or None, manager=request.user)
    if request.method == 'POST' and form.is_valid():
        tenant = form.cleaned_data['lease_tenant']
        bills = list(form.cleaned_data['bills'])
        form.save(granted_by=request.user)
        log_event(
            'rental.bill.tenant_permission_granted', category=AuditEvent.Category.SYSTEM,
            message='已授權租客補填歷史帳單', request=request,
            metadata={
                'lease_id': tenant.lease_id,
                'lease_tenant_id': tenant.id,
                'bill_ids': [bill.id for bill in bills],
                'expires_on': form.cleaned_data['expires_on'].isoformat() if form.cleaned_data['expires_on'] else None,
            },
        )
        messages.success(request, '已完成租客歷史帳單補填授權。')
        return redirect('rental:bill_list')
    return render(request, 'rental/form.html', {
        'form': form, 'title': '授權租客補填歷史帳單',
        'back_url': reverse('rental:bill_list'),
        'form_intro': '請先選擇租客，再勾選同一份租約中狀態為「待租客填寫」的歷史帳單。已結案帳單維持唯讀，不可直接修改。',
    })


@login_required
def maintenance_list(request):
    properties = _managed_properties(request.user)
    tenant_leases = Lease.objects.filter(lease_tenants__tenant__user=request.user, lease_tenants__status=LeaseTenant.Status.ACTIVE)
    requests = MaintenanceRequest.objects.filter(Q(unit__property__in=properties) | Q(lease__in=tenant_leases)).distinct()
    return render(request, 'rental/maintenance_list.html', {'requests': requests, 'tenant_leases': tenant_leases})


@login_required
def maintenance_create(request):
    tenant_leases = Lease.objects.filter(lease_tenants__tenant__user=request.user, lease_tenants__status=LeaseTenant.Status.ACTIVE).select_related('unit')
    if not tenant_leases.exists():
        return HttpResponseForbidden('僅有效租客可建立報修。')
    form = MaintenanceForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        lease = tenant_leases.first()
        maintenance = form.save(commit=False)
        maintenance.lease = lease
        maintenance.unit = lease.unit
        maintenance.created_by = request.user
        maintenance.save()
        if form.cleaned_data.get('attachment'):
            MaintenanceAttachment.objects.create(request=maintenance, file=form.cleaned_data['attachment'], uploaded_by=request.user)
        log_event('rental.maintenance.created', category=AuditEvent.Category.SYSTEM, message='租客已建立報修單', request=request, metadata={'request_id': maintenance.id})
        messages.success(request, '報修單已送出。')
        return redirect('rental:maintenance_list')
    return render(request, 'rental/form.html', {
        'form': form, 'title': '建立報修', 'back_url': reverse('rental:maintenance_list'),
    })


@login_required
def announcement_list(request):
    properties = _managed_properties(request.user)
    tenant_properties = Property.objects.filter(units__leases__lease_tenants__tenant__user=request.user, units__leases__lease_tenants__status=LeaseTenant.Status.ACTIVE)
    announcements = Announcement.objects.filter(Q(property__isnull=True) | Q(property__in=properties) | Q(property__in=tenant_properties)).distinct()
    return render(request, 'rental/announcement_list.html', {'announcements': announcements})


@login_required
def rental_file(request, stored_name):
    candidates = [
        (UnitPhoto, 'image', lambda item: can_manage_property(request.user, item.unit.property)),
        (LeaseDocument, 'file', lambda item: can_manage_lease(request.user, item.lease) or is_lease_tenant(request.user, item.lease)),
        (BillMeterReading, 'photo', lambda item: can_access_bill(request.user, item.bill)),
        (BillPayment, 'receipt', lambda item: can_access_bill(request.user, item.bill)),
        (MaintenanceAttachment, 'file', lambda item: can_manage_lease(request.user, item.request.lease) or item.request.created_by_id == request.user),
    ]
    for model, field, permitted in candidates:
        item = model.objects.filter(**{field: stored_name}).first()
        if item:
            if not permitted(item):
                return HttpResponseForbidden('您沒有存取此附件的權限。')
            file = getattr(item, field)
            return FileResponse(file.open('rb'), as_attachment=False, filename=file.name.rsplit('/', 1)[-1])
    raise Http404('找不到附件。')
