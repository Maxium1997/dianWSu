from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.urls import reverse


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    """Return members to their profile after linking an OAuth provider."""

    def get_connect_redirect_url(self, request, socialaccount):
        return reverse('profile')
