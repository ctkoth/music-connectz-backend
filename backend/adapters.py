from allauth.socialaccount.adapter import DefaultSocialAccountAdapter


class SafeSocialAccountAdapter(DefaultSocialAccountAdapter):
    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)

        if not getattr(user, 'email', ''):
            user.email = ''

        if not getattr(user, 'username', ''):
            social_uid = getattr(getattr(sociallogin, 'account', None), 'uid', '') or 'user'
            user.username = f"{sociallogin.account.provider}_{social_uid}"[:150]

        return user