from datetime import timedelta

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from .models import (
    Bill, BillLineItem, BillMeterReading, BillPayment, BillTenantPermission, ElectricityRate, Lease, LeaseCharge, LeaseTenant,
    MaintenanceAttachment, MaintenanceRequest, Property, TenantInvitation, Unit,
)
from .services import rate_for_period


class PropertyForm(forms.ModelForm):
    class Meta:
        model = Property
        fields = ['name', 'address', 'description']
        widgets = {'description': forms.Textarea(attrs={'rows': 3})}


class UnitForm(forms.ModelForm):
    class Meta:
        model = Unit
        fields = ['floor', 'number', 'room_type', 'area_ping', 'notes']
        widgets = {'notes': forms.Textarea(attrs={'rows': 3})}


class LeaseForm(forms.ModelForm):
    class Meta:
        model = Lease
        fields = ['start_date', 'end_date', 'monthly_rent', 'deposit', 'due_day', 'status']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
        }


class LeaseBillingSettingsForm(forms.Form):
    MONTH_CHOICES = [('', '請選擇')] + [(month, f'{month} 月') for month in range(1, 13)]

    electricity_rate_1_name = forms.CharField(label='電費費率一名稱', required=False, max_length=80)
    electricity_rate_1_start_month = forms.TypedChoiceField(label='費率一起始月份', required=False, choices=MONTH_CHOICES, coerce=int)
    electricity_rate_1_end_month = forms.TypedChoiceField(label='費率一結束月份', required=False, choices=MONTH_CHOICES, coerce=int)
    electricity_rate_1_amount = forms.DecimalField(label='費率一每度電價', required=False, min_value=0, decimal_places=2)
    electricity_rate_2_name = forms.CharField(label='電費費率二名稱', required=False, max_length=80)
    electricity_rate_2_start_month = forms.TypedChoiceField(label='費率二起始月份', required=False, choices=MONTH_CHOICES, coerce=int)
    electricity_rate_2_end_month = forms.TypedChoiceField(label='費率二結束月份', required=False, choices=MONTH_CHOICES, coerce=int)
    electricity_rate_2_amount = forms.DecimalField(label='費率二每度電價', required=False, min_value=0, decimal_places=2)
    water_fee = forms.DecimalField(label='每月水費', required=False, min_value=0, decimal_places=2)
    gas_fee = forms.DecimalField(label='每月瓦斯費', required=False, min_value=0, decimal_places=2)
    management_fee = forms.DecimalField(label='每月管理費', required=False, min_value=0, decimal_places=2)
    other_fee_name = forms.CharField(label='其他每月費用名稱', required=False, max_length=100)
    other_fee = forms.DecimalField(label='其他每月費用金額', required=False, min_value=0, decimal_places=2)

    def __init__(self, *args, lease, **kwargs):
        super().__init__(*args, **kwargs)
        self.lease = lease
        for field in self.fields.values():
            field.widget.attrs['step'] = '0.01'

        rates = list(lease.electricity_rates.order_by('id'))
        self.rate_ids = {}
        for index, rate in enumerate(rates[:2], start=1):
            self.rate_ids[index] = rate.id
            self.fields[f'electricity_rate_{index}_name'].initial = rate.name
            self.fields[f'electricity_rate_{index}_start_month'].initial = rate.start_month
            self.fields[f'electricity_rate_{index}_end_month'].initial = rate.end_month
            self.fields[f'electricity_rate_{index}_amount'].initial = rate.rate_per_kwh

        charge_fields = {
            LeaseCharge.ChargeType.WATER: 'water_fee',
            LeaseCharge.ChargeType.GAS: 'gas_fee',
            LeaseCharge.ChargeType.MANAGEMENT: 'management_fee',
            LeaseCharge.ChargeType.OTHER: 'other_fee',
        }
        for charge_type, field_name in charge_fields.items():
            charge = lease.recurring_charges.filter(charge_type=charge_type).first()
            if charge:
                self.fields[field_name].initial = charge.default_amount
                if charge_type == LeaseCharge.ChargeType.OTHER:
                    self.fields['other_fee_name'].initial = charge.name

    def clean(self):
        cleaned = super().clean()
        has_other_name = bool(cleaned.get('other_fee_name'))
        has_other_amount = cleaned.get('other_fee') is not None
        if has_other_name != has_other_amount:
            self.add_error('other_fee', '其他費用請同時填寫名稱與金額。')
        for index in (1, 2):
            values = [
                cleaned.get(f'electricity_rate_{index}_start_month'),
                cleaned.get(f'electricity_rate_{index}_end_month'),
                cleaned.get(f'electricity_rate_{index}_amount'),
            ]
            if any(value is not None for value in values) and not all(value is not None for value in values):
                self.add_error(f'electricity_rate_{index}_amount', '請完整填寫起始月份、結束月份與每度電價。')
        rate_months = []
        for index in (1, 2):
            start = cleaned.get(f'electricity_rate_{index}_start_month')
            end = cleaned.get(f'electricity_rate_{index}_end_month')
            amount = cleaned.get(f'electricity_rate_{index}_amount')
            if start is not None and end is not None and amount is not None:
                months = set(range(start, end + 1)) if start <= end else set(range(start, 13)) | set(range(1, end + 1))
                rate_months.append((index, months))
        if len(rate_months) == 2 and rate_months[0][1] & rate_months[1][1]:
            self.add_error('electricity_rate_2_start_month', '兩組電價月份不可重疊。')
        return cleaned

    def save(self):
        for index in (1, 2):
            rate_id = self.rate_ids.get(index)
            start_month = self.cleaned_data[f'electricity_rate_{index}_start_month']
            end_month = self.cleaned_data[f'electricity_rate_{index}_end_month']
            amount = self.cleaned_data[f'electricity_rate_{index}_amount']
            name = self.cleaned_data[f'electricity_rate_{index}_name'] or f'電費費率（{start_month}–{end_month} 月）'
            if amount is None:
                if rate_id:
                    ElectricityRate.objects.filter(pk=rate_id, lease=self.lease).delete()
                continue
            if rate_id:
                rate = ElectricityRate.objects.get(pk=rate_id, lease=self.lease)
                rate.name = name
                rate.start_month = start_month
                rate.end_month = end_month
                rate.rate_per_kwh = amount
                rate.save(update_fields=['name', 'start_month', 'end_month', 'rate_per_kwh'])
            else:
                ElectricityRate.objects.create(
                    lease=self.lease, name=name, start_month=start_month,
                    end_month=end_month, rate_per_kwh=amount,
                )

        charge_specs = [
            ('water_fee', LeaseCharge.ChargeType.WATER, '水費'),
            ('gas_fee', LeaseCharge.ChargeType.GAS, '瓦斯費'),
            ('management_fee', LeaseCharge.ChargeType.MANAGEMENT, '管理費'),
            ('other_fee', LeaseCharge.ChargeType.OTHER, self.cleaned_data.get('other_fee_name') or '其他費用'),
        ]
        for field_name, charge_type, name in charge_specs:
            charges = self.lease.recurring_charges.filter(charge_type=charge_type).order_by('id')
            amount = self.cleaned_data[field_name]
            if amount is None:
                charges.delete()
                continue
            charge = charges.first()
            if charge:
                charge.name = name
                charge.default_amount = amount
                charge.enabled = True
                charge.save(update_fields=['name', 'default_amount', 'enabled'])
                charges.exclude(pk=charge.pk).delete()
            else:
                LeaseCharge.objects.create(
                    lease=self.lease, name=name, charge_type=charge_type,
                    default_amount=amount, tenant_editable=True,
                )


class TenantInvitationForm(forms.ModelForm):
    class Meta:
        model = TenantInvitation
        fields = ['lease', 'invited_name', 'invited_email', 'billing_access_start_date']
        widgets = {'billing_access_start_date': forms.DateInput(attrs={'type': 'date'})}

    def __init__(self, *args, manager, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['lease'].queryset = Lease.objects.filter(
            unit__property__in=Property.objects.filter(
                Q(owner=manager) | Q(memberships__user=manager)
            )
        ).distinct().select_related('unit__property')
        self.fields['billing_access_start_date'].help_text = '留白時，租客接受邀請後會從租約起始日取得帳務權限。'

    def save(self, *, created_by):
        invitation = super().save(commit=False)
        invitation.created_by = created_by
        invitation.expires_at = timezone.now() + timedelta(days=3)
        invitation.save()
        return invitation


class BillTenantPermissionForm(forms.Form):
    lease_tenant = forms.ModelChoiceField(label='租客', queryset=LeaseTenant.objects.none())
    bills = forms.ModelMultipleChoiceField(label='可補填的歷史帳單', queryset=Bill.objects.none(), widget=forms.CheckboxSelectMultiple)
    expires_on = forms.DateField(
        label='授權到期日（選填）', required=False,
        widget=forms.DateInput(attrs={'type': 'date'}),
        help_text='留白代表未設定期限；只有「待租客填寫」的帳單可被授權。',
    )

    def __init__(self, *args, manager, **kwargs):
        super().__init__(*args, **kwargs)
        managed_properties = Property.objects.filter(Q(owner=manager) | Q(memberships__user=manager)).distinct()
        self.fields['lease_tenant'].queryset = LeaseTenant.objects.filter(
            lease__unit__property__in=managed_properties,
            status=LeaseTenant.Status.ACTIVE,
        ).select_related('tenant__user', 'lease__unit__property')
        self.fields['bills'].queryset = Bill.objects.filter(
            lease__unit__property__in=managed_properties,
            status=Bill.Status.DRAFT,
        ).select_related('lease__unit__property').order_by('-period')

    def clean(self):
        cleaned = super().clean()
        lease_tenant = cleaned.get('lease_tenant')
        bills = cleaned.get('bills')
        if lease_tenant and bills:
            mismatched = [bill for bill in bills if bill.lease_id != lease_tenant.lease_id]
            if mismatched:
                self.add_error('bills', '只能選擇該租客所屬租約的帳單。')
        return cleaned

    def save(self, *, granted_by):
        tenant = self.cleaned_data['lease_tenant']
        for bill in self.cleaned_data['bills']:
            BillTenantPermission.objects.update_or_create(
                bill=bill,
                tenant=tenant,
                defaults={'expires_on': self.cleaned_data['expires_on'], 'granted_by': granted_by},
            )


class LeaseBillTenantPermissionForm(forms.Form):
    bills = forms.ModelMultipleChoiceField(label='帳單', queryset=Bill.objects.none(), required=True)

    def __init__(self, *args, lease, **kwargs):
        super().__init__(*args, **kwargs)
        self.lease = lease
        self.fields['bills'].queryset = lease.bills.exclude(status=Bill.Status.PAID).order_by('period')


class TenantBillForm(forms.Form):
    previous_reading = forms.DecimalField(label='前次／入住初始電表度數', required=False, min_value=0, decimal_places=2)
    current_reading = forms.DecimalField(label='本次電表度數', required=False, min_value=0, decimal_places=2)
    meter_photo = forms.FileField(label='電表照片', required=False)
    note = forms.CharField(label='給管理者的備註', required=False, widget=forms.Textarea(attrs={'rows': 3}))

    def __init__(self, *args, bill, **kwargs):
        super().__init__(*args, **kwargs)
        self.bill = bill
        self.editable_items = list(bill.items.filter(tenant_editable=True).order_by('sort_order', 'id'))
        self.has_electricity = any(item.item_type == BillLineItem.ItemType.ELECTRICITY for item in self.editable_items)
        for item in self.editable_items:
            self.fields[f'item_{item.id}'] = forms.DecimalField(
                label=item.name, min_value=0, decimal_places=2, initial=item.amount,
            )
        self.previous_reading = bill.bills_before_current_reading()
        if self.previous_reading is not None:
            self.fields['previous_reading'].initial = self.previous_reading
            self.fields['previous_reading'].disabled = True
            self.fields['previous_reading'].help_text = '已自動帶入同一份租約上期的本次度數。'
        else:
            self.fields['previous_reading'].help_text = '這是此租約的首次抄表，請填寫入住時的電表初始度數。'
        try:
            reading = bill.meter_reading
            self.fields['current_reading'].initial = reading.current_reading
        except BillMeterReading.DoesNotExist:
            pass

    def clean(self):
        cleaned = super().clean()
        current = cleaned.get('current_reading')
        previous = cleaned.get('previous_reading')
        if self.has_electricity and previous is None:
            self.add_error('previous_reading', '請填寫入住初始電表度數。')
        if self.has_electricity and current is None:
            self.add_error('current_reading', '請填寫本次電表度數。')
        if self.has_electricity and current is not None and previous is not None and current < previous:
            self.add_error('current_reading', '本次度數不可小於前次／入住初始度數。')
        if self.has_electricity and current is not None and not cleaned.get('meter_photo'):
            try:
                if not self.bill.meter_reading.photo:
                    self.add_error('meter_photo', '填寫電表度數時必須上傳電表照片。')
            except BillMeterReading.DoesNotExist:
                self.add_error('meter_photo', '填寫電表度數時必須上傳電表照片。')
        return cleaned

    def save(self, user):
        for item in self.editable_items:
            item.amount = self.cleaned_data[f'item_{item.id}']
            item.save(update_fields=['amount'])
        current = self.cleaned_data.get('current_reading')
        previous = self.cleaned_data.get('previous_reading')
        if self.has_electricity and current is not None and previous is not None:
            reading, _ = BillMeterReading.objects.get_or_create(bill=self.bill)
            reading.previous_reading = previous
            reading.current_reading = current
            reading.recorded_by = user
            if self.cleaned_data.get('meter_photo'):
                reading.photo = self.cleaned_data['meter_photo']
            reading.full_clean()
            reading.save()
            electricity = next((item for item in self.editable_items if item.item_type == BillLineItem.ItemType.ELECTRICITY), None)
            if electricity and previous is not None:
                electricity.amount = (current - previous) * rate_for_period(self.bill.lease, self.bill.period)
                electricity.save(update_fields=['amount'])


class PaymentForm(forms.Form):
    method = forms.ChoiceField(label='付款方式', choices=BillPayment.Method.choices)
    receipt = forms.FileField(label='匯款憑證', required=False)
    note = forms.CharField(label='付款備註', required=False, widget=forms.Textarea(attrs={'rows': 3}))

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('method') == BillPayment.Method.TRANSFER and not cleaned.get('receipt'):
            raise ValidationError('選擇銀行匯款時必須上傳匯款憑證。')
        return cleaned


class MaintenanceForm(forms.ModelForm):
    attachment = forms.FileField(label='照片或附件', required=False)

    class Meta:
        model = MaintenanceRequest
        fields = ['title', 'description']
        widgets = {'description': forms.Textarea(attrs={'rows': 4})}
