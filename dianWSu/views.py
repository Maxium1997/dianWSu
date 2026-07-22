from allauth.socialaccount.models import SocialAccount
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render


def index(request):
    if request.get_host().split(':', 1)[0].lower() == 'rental-management.dotwebsite.cc':
        from rental.views import dashboard
        return dashboard(request)
    return render(request, "index.html")


def healthz(request):
    return JsonResponse({'status': 'ok'})


def rental_line_login(request):
    """Start LINE OAuth on the primary domain, which LINE permits as one callback."""
    return redirect(
        'https://dotwebsite.cc/accounts/line/login/'
        '?process=login&next=/accounts/line/rental-complete/'
    )


@login_required
def rental_line_complete(request):
    """Return the shared authenticated session to the rental application."""
    return redirect('https://rental-management.dotwebsite.cc/')


@login_required
def profile(request):
    accounts = list(SocialAccount.objects.filter(user=request.user).order_by('provider'))
    linked_providers = {account.provider for account in accounts}
    return render(request, 'account/profile.html', {
        'accounts': accounts,
        'linked_providers': linked_providers,
    })
