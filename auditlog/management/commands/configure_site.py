from django.contrib.sites.models import Site
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Set the django.contrib.sites domain used by OAuth callbacks.'

    def add_arguments(self, parser):
        parser.add_argument('--domain', required=True, help='Public domain, without scheme or path.')
        parser.add_argument('--name', help='Human-readable site name. Defaults to the domain.')

    def handle(self, *args, **options):
        domain = options['domain'].strip().lower()
        if '://' in domain or '/' in domain:
            raise CommandError('Use only the hostname, for example: app.example.com')

        site, _ = Site.objects.update_or_create(
            id=1,
            defaults={'domain': domain, 'name': options['name'] or domain},
        )
        self.stdout.write(self.style.SUCCESS(f'Configured site domain: {site.domain}'))
