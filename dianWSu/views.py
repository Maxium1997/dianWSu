from allauth.socialaccount.models import SocialAccount
from django.contrib.auth.decorators import login_required
from django.shortcuts import render


def index(request):
    return render(request, "index.html")


@login_required
def profile(request):
    accounts = list(SocialAccount.objects.filter(user=request.user).order_by('provider'))
    linked_providers = {account.provider for account in accounts}
    return render(request, 'account/profile.html', {
        'accounts': accounts,
        'linked_providers': linked_providers,
    })
