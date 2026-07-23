from datetime import timedelta

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from .models import (
    BillLineItem, BillMeterReading, BillPayment, ElectricityRate, Lease, LeaseCharge,
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
        fields = ['floor', 'number', 'room_type', 'area_ping', 'status', 'notes']
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
    summer_electricity_rate = forms.DecimalField(
        label='夏季每度電價（5–11 月）', required=False, min_value=0, decimal_places=2,
        help_text='例如 6 元／度；留白會移除此季節費率。',
    )
    winter_electricity_rate = forms.DecimalField(
        label='冬季每度電價（12–4 月）', required=False, min_value=0, decimal_places=2,
        help_text='例如 5 元／度；留白會移除此季節費率。',
    )
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

        summer = lease.electricity_rates.filter(start_month=5, end_month=11).first()
        winter = lease.electricity_rates.filter(start_month=12, end_month=4).first()
        self.fields['summer_electricity_rate'].initial = summer.rate_per_kwh if summer else None
        self.fields['winter_electricity_rate'].initial = winter.rate_per_kwh if winter else None

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
        return cleaned

    def save(self):
        rate_specs = [
            ('summer_electricity_rate', 5, 11, '夏季電價（5–11 月）'),
            ('winter_electricity_rate', 12, 4, '冬季電價（12–4 月）'),
        ]
        for field_name, start_month, end_month, name in rate_specs:
            rates = self.lease.electricity_rates.filter(start_month=start_month, end_month=end_month).order_by('id')
            amount = self.cleaned_data[field_name]
            if amount is None:
                rates.delete()
                continue
            rate = rates.first()
            if rate:
                rate.name = name
                rate.rate_per_kwh = amount
                rate.save(update_fields=['name', 'rate_per_kwh'])
                rates.exclude(pk=rate.pk).delete()
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
        fields = ['lease', 'invited_name', 'invited_email']

    def __init__(self, *args, manager, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['lease'].queryset = Lease.objects.filter(
            unit__property__in=Property.objects.filter(
                Q(owner=manager) | Q(memberships__user=manager)
            )
        ).distinct().select_related('unit__property')

    def save(self, *, created_by):
        invitation = super().save(commit=False)
        invitation.created_by = created_by
        invitation.expires_at = timezone.now() + timedelta(days=3)
        invitation.save()
        return invitation


class TenantBillForm(forms.Form):
    current_reading = forms.DecimalField(label='本次電表度數', required=False, min_value=0, decimal_places=2)
    meter_photo = forms.FileField(label='電表照片', required=False)
    note = forms.CharField(label='給管理者的備註', required=False, widget=forms.Textarea(attrs={'rows': 3}))

    def __init__(self, *args, bill, **kwargs):
        super().__init__(*args, **kwargs)
        self.bill = bill
        self.editable_items = list(bill.items.filter(tenant_editable=True).order_by('sort_order', 'id'))
        for item in self.editable_items:
            self.fields[f'item_{item.id}'] = forms.DecimalField(
                label=item.name, min_value=0, decimal_places=2, initial=item.amount,
            )
        try:
            reading = bill.meter_reading
            self.fields['current_reading'].initial = reading.current_reading
        except BillMeterReading.DoesNotExist:
            pass

    def clean(self):
        cleaned = super().clean()
        current = cleaned.get('current_reading')
        has_electricity = any(item.item_type == BillLineItem.ItemType.ELECTRICITY for item in self.editable_items)
        if has_electricity and current is not None and not cleaned.get('meter_photo'):
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
        if current is not None:
            previous = self.bill.bills_before_current_reading()
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
