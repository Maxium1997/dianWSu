from django.core.management.base import BaseCommand

from rental.services import generate_current_bills


class Command(BaseCommand):
    help = '為有效租約建立當月尚未存在的帳單。'

    def handle(self, *args, **options):
        count = generate_current_bills()
        self.stdout.write(self.style.SUCCESS(f'已建立 {count} 筆租賃帳單。'))
