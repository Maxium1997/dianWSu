from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import (
    Bill, BillLineItem, ElectricityRate, Lease, LeaseCharge, LeaseTenant,
    Property, TenantProfile, Unit,
)
from .services import create_bill, is_lease_tenant, rate_for_period


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
        LeaseTenant.objects.create(lease=self.lease, tenant=profile, status=LeaseTenant.Status.ACTIVE)

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


class RentalLoginTests(TestCase):
    def test_line_login_uses_primary_domain_flow_from_rental_subdomain(self):
        response = self.client.get('/accounts/login/', HTTP_HOST='rental-management.dotwebsite.cc')
        self.assertContains(response, reverse('rental_line_login'))

        start = self.client.get(reverse('rental_line_login'), HTTP_HOST='rental-management.dotwebsite.cc')
        self.assertRedirects(
            start,
            'https://dotwebsite.cc/accounts/line/login/?process=login&next=/accounts/line/rental-complete/',
            fetch_redirect_response=False,
        )
