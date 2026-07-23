from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from .models import (
    Bill, BillLineItem, BillMeterReading, BillTenantPermission, ElectricityRate, Lease, LeaseCharge, LeaseTenant,
    Property, TenantProfile, Unit,
)
from .forms import TenantBillForm
from .services import can_access_bill, can_fill_bill, create_bill, is_lease_tenant, rate_for_period


class RentalBillingTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user('owner', password='test-password')
        self.tenant_user = get_user_model().objects.create_user('tenant', password='test-password')
        property_ = Property.objects.create(name='測試物件', owner=self.owner, address='測試地址')
        unit = Unit.objects.create(property=property_, number='101')
        self.lease = Lease.objects.create(
            unit=unit,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            monthly_rent=Decimal('12000'),
            deposit=Decimal('24000'),
            due_day=5,
            status=Lease.Status.ACTIVE,
        )
        LeaseCharge.objects.create(lease=self.lease, name='水費', charge_type=LeaseCharge.ChargeType.WATER, default_amount=Decimal('100'))
        ElectricityRate.objects.create(lease=self.lease, start_month=5, end_month=11, rate_per_kwh=Decimal('6'))
        ElectricityRate.objects.create(lease=self.lease, start_month=12, end_month=4, rate_per_kwh=Decimal('5'))
        profile = TenantProfile.objects.create(user=self.tenant_user)
        LeaseTenant.objects.create(
            lease=self.lease, tenant=profile, status=LeaseTenant.Status.ACTIVE,
            billing_access_start_date=date(2026, 1, 1),
        )

    def test_bill_is_created_once_with_rent_and_recurring_items(self):
        bill, created = create_bill(self.lease, date(2026, 6, 1), actor=self.owner)
        self.assertTrue(created)
        self.assertEqual(bill.due_date, date(2026, 6, 8))
        self.assertEqual(bill.items.count(), 3)
        self.assertEqual(bill.total_amount, Decimal('12100'))
        self.assertEqual(bill.snapshots.count(), 1)
        same_bill, created_again = create_bill(self.lease, date(2026, 6, 1), actor=self.owner)
        self.assertFalse(created_again)
        self.assertEqual(bill.id, same_bill.id)

    def test_seasonal_electricity_rate_and_tenant_identity(self):
        self.assertEqual(rate_for_period(self.lease, date(2026, 7, 1)), Decimal('6'))
        self.assertEqual(rate_for_period(self.lease, date(2026, 1, 1)), Decimal('5'))
        self.assertTrue(is_lease_tenant(self.tenant_user, self.lease))

    def test_meter_readings_are_carried_only_within_the_same_lease(self):
        prior_bill = Bill.objects.create(lease=self.lease, period=date(2026, 1, 1), due_date=date(2026, 1, 8))
        BillMeterReading.objects.create(bill=prior_bill, previous_reading=Decimal('100'), current_reading=Decimal('125'))
        current_bill = Bill.objects.create(lease=self.lease, period=date(2026, 2, 1), due_date=date(2026, 2, 8))
        electricity = BillLineItem.objects.create(
            bill=current_bill, item_type=BillLineItem.ItemType.ELECTRICITY,
            name='電費', amount=Decimal('0'), tenant_editable=True,
        )
        form = TenantBillForm(
            data={
                'previous_reading': '999', 'current_reading': '150',
                f'item_{electricity.id}': '0', 'note': '',
            },
            files={'meter_photo': SimpleUploadedFile('meter.jpg', b'meter-image', content_type='image/jpeg')},
            bill=current_bill,
        )
        self.assertEqual(form.fields['previous_reading'].initial, Decimal('125'))
        self.assertTrue(form.fields['previous_reading'].disabled)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['previous_reading'], Decimal('125'))

        new_lease = Lease.objects.create(
            unit=self.lease.unit, start_date=date(2027, 1, 1), end_date=date(2027, 12, 31),
            monthly_rent=Decimal('12000'), deposit=Decimal('24000'), status=Lease.Status.DRAFT,
        )
        new_bill = Bill.objects.create(lease=new_lease, period=date(2027, 1, 1), due_date=date(2027, 1, 8))
        BillLineItem.objects.create(bill=new_bill, item_type=BillLineItem.ItemType.ELECTRICITY, name='電費', amount=Decimal('0'), tenant_editable=True)
        new_lease_form = TenantBillForm(bill=new_bill)
        self.assertIsNone(new_lease_form.fields['previous_reading'].initial)
        self.assertFalse(new_lease_form.fields['previous_reading'].disabled)

    def test_historic_bill_requires_explicit_tenant_permission_before_billing_access_date(self):
        tenant_relation = self.lease.lease_tenants.get()
        tenant_relation.billing_access_start_date = date(2026, 3, 1)
        tenant_relation.save(update_fields=['billing_access_start_date'])
        historic_bill = Bill.objects.create(lease=self.lease, period=date(2026, 1, 1), due_date=date(2026, 1, 8))
        current_bill = Bill.objects.create(lease=self.lease, period=date(2026, 3, 1), due_date=date(2026, 3, 8))

        self.assertFalse(can_access_bill(self.tenant_user, historic_bill))
        self.assertTrue(can_access_bill(self.tenant_user, current_bill))
        self.assertFalse(can_fill_bill(self.tenant_user, historic_bill))

        BillTenantPermission.objects.create(bill=historic_bill, tenant=tenant_relation, granted_by=self.owner)
        self.assertTrue(can_access_bill(self.tenant_user, historic_bill))
        self.assertTrue(can_fill_bill(self.tenant_user, historic_bill))


class RentalLoginTests(TestCase):
    def test_base_layout_includes_theme_toggle(self):
        response = self.client.get('/')
        self.assertContains(response, 'data-theme-toggle')
        self.assertContains(response, 'dianwsu-theme')

    def test_line_login_uses_primary_domain_flow_from_rental_subdomain(self):
        response = self.client.get('/accounts/login/', HTTP_HOST='rental-management.dotwebsite.cc')
        self.assertContains(response, reverse('rental_line_login'))

        start = self.client.get(reverse('rental_line_login'), HTTP_HOST='rental-management.dotwebsite.cc')
        self.assertRedirects(
            start,
            'https://dotwebsite.cc/accounts/line/login/?process=login&next=/accounts/line/rental-complete/',
            fetch_redirect_response=False,
        )


class RentalManagementEditTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user('manager', password='test-password')
        self.property = Property.objects.create(name='原始名稱', owner=self.owner, address='原始地址')
        self.unit = Unit.objects.create(property=self.property, number='101')
        self.lease = Lease.objects.create(
            unit=self.unit, start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
            monthly_rent=Decimal('10000'), deposit=Decimal('20000'), status=Lease.Status.ACTIVE,
        )
        self.client.force_login(self.owner)

    def test_manager_can_edit_property_and_unit(self):
        property_response = self.client.post(
            reverse('rental:property_edit', args=[self.property.id]),
            {'name': '新名稱', 'address': '新地址', 'description': '更新說明'},
        )
        self.assertRedirects(property_response, reverse('rental:property_detail', args=[self.property.id]))
        self.property.refresh_from_db()
        self.assertEqual(self.property.name, '新名稱')
        self.assertEqual(self.property.address, '新地址')

        unit_response = self.client.post(
            reverse('rental:unit_edit', args=[self.unit.id]),
            {'floor': '1F', 'number': '102', 'room_type': '套房', 'area_ping': '', 'status': Unit.Status.AVAILABLE, 'notes': '已整理'},
        )
        self.assertRedirects(unit_response, reverse('rental:property_detail', args=[self.property.id]))
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.number, '102')

        unit_edit = self.client.get(reverse('rental:unit_edit', args=[self.unit.id]))
        self.assertNotContains(unit_edit, '出租狀態')

    def test_overlapping_lease_is_rejected_by_the_server(self):
        response = self.client.post(
            reverse('rental:lease_create', args=[self.unit.id]),
            {
                'start_date': '2026-06-01', 'end_date': '2026-12-31',
                'monthly_rent': '10000', 'deposit': '20000', 'due_day': '5',
                'status': Lease.Status.ACTIVE,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '期間重疊')
        self.assertEqual(Lease.objects.filter(unit=self.unit).count(), 1)

    def test_manager_can_configure_lease_electricity_and_recurring_fees(self):
        response = self.client.post(
            reverse('rental:lease_billing_settings', args=[self.lease.id]),
            {
                'electricity_rate_1_name': '暖季', 'electricity_rate_1_start_month': '4', 'electricity_rate_1_end_month': '10', 'electricity_rate_1_amount': '6',
                'electricity_rate_2_name': '涼季', 'electricity_rate_2_start_month': '11', 'electricity_rate_2_end_month': '3', 'electricity_rate_2_amount': '5',
                'water_fee': '100', 'gas_fee': '80', 'management_fee': '500',
                'other_fee_name': '網路費', 'other_fee': '300',
            },
        )
        self.assertRedirects(response, reverse('rental:property_detail', args=[self.property.id]))
        warm_rate = ElectricityRate.objects.get(lease=self.lease, start_month=4, end_month=10)
        cool_rate = ElectricityRate.objects.get(lease=self.lease, start_month=11, end_month=3)
        self.assertEqual(warm_rate.name, '暖季')
        self.assertEqual(warm_rate.rate_per_kwh, Decimal('6'))
        self.assertEqual(cool_rate.rate_per_kwh, Decimal('5'))
        self.assertEqual(LeaseCharge.objects.get(lease=self.lease, charge_type=LeaseCharge.ChargeType.WATER).default_amount, Decimal('100'))
        other = LeaseCharge.objects.get(lease=self.lease, charge_type=LeaseCharge.ChargeType.OTHER)
        self.assertEqual(other.name, '網路費')
        self.assertEqual(other.default_amount, Decimal('300'))

    def test_manager_room_workspace_and_lease_bill_permission_flow(self):
        tenant_user = get_user_model().objects.create_user('historical-tenant', password='test-password')
        tenant = TenantProfile.objects.create(user=tenant_user)
        LeaseTenant.objects.create(
            lease=self.lease, tenant=tenant, status=LeaseTenant.Status.ACTIVE,
            billing_access_start_date=date(2026, 6, 1),
        )
        workspace = self.client.get(reverse('rental:property_list'))
        self.assertContains(workspace, '查看帳單')
        self.assertContains(workspace, reverse('rental:lease_bill_list', args=[self.lease.id]))

        bill_list = self.client.get(reverse('rental:lease_bill_list', args=[self.lease.id]))
        self.assertContains(bill_list, '授權租客填補')
        self.assertContains(bill_list, '尚未產生帳單')

        grant = self.client.post(
            reverse('rental:lease_bill_list', args=[self.lease.id]) + '?grant=1',
            {'periods': ['2026-01-01']},
        )
        self.assertRedirects(grant, reverse('rental:lease_bill_list', args=[self.lease.id]))
        historic_bill = Bill.objects.get(lease=self.lease, period=date(2026, 1, 1))
        historic_bill.refresh_from_db()
        self.assertTrue(historic_bill.tenant_fill_enabled)
        self.assertEqual(historic_bill.status, Bill.Status.DRAFT)
        self.assertTrue(can_access_bill(tenant_user, historic_bill))
