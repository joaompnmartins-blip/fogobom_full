from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings

STRONG_PW = 'Fogo-Bom-2026!x'


@override_settings(SECURE_SSL_REDIRECT=False)
class AuthTests(TestCase):
    def setUp(self):
        cache.clear()
        self.staff = User.objects.create_user('staff', password='x', is_staff=True)

    def register(self, **overrides):
        data = {'form_type': 'register', 'reg_username': 'novo', 'reg_email': 'novo@example.com',
                'reg_password': STRONG_PW, 'reg_confirm': STRONG_PW, **overrides}
        with mock.patch('core.views._send_async') as send:
            response = self.client.post('/login/', data)
        return response, send

    def login(self, username, password, next_url=''):
        url = f'/login/?next={next_url}' if next_url else '/login/'
        return self.client.post(url, {'form_type': 'login', 'username': username, 'password': password})

    def test_register_rejects_weak_password(self):
        r, _ = self.register(reg_password='123456', reg_confirm='123456')
        self.assertTrue(r.context['reg_error'])
        self.assertFalse(User.objects.filter(username='novo').exists())

    def test_register_rejects_invalid_email(self):
        r, _ = self.register(reg_email='nao-email')
        self.assertEqual(r.context['reg_error'], 'Email inválido.')
        self.assertFalse(User.objects.filter(username='novo').exists())

    def test_register_rejects_duplicate_username_case_insensitive(self):
        User.objects.create_user('Novo', password='x')
        r, _ = self.register()
        self.assertEqual(r.context['reg_error'], 'Utilizador já existe.')

    @override_settings(ADMIN_EMAIL='admin@example.com')
    def test_register_creates_inactive_user_and_notifies_admin(self):
        r, send = self.register()
        user = User.objects.get(username='novo')
        self.assertFalse(user.is_active)
        self.assertEqual(send.call_args.args[2], ['admin@example.com'])

    def test_pending_user_gets_approval_message(self):
        self.register()
        r = self.login('novo', STRONG_PW)
        self.assertIn('aguarda aprovação', r.context['login_error'])

    def test_approve_requires_post_and_staff(self):
        self.register()
        novo = User.objects.get(username='novo')
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(f'/utilizadores/{novo.pk}/aprovar/').status_code, 405)
        with mock.patch('core.views._send_async'):
            self.client.post(f'/utilizadores/{novo.pk}/aprovar/')
        novo.refresh_from_db()
        self.assertTrue(novo.is_active)

    def test_decline_deletes_pending_user(self):
        self.register()
        novo = User.objects.get(username='novo')
        self.client.force_login(self.staff)
        with mock.patch('core.views._send_async'):
            self.client.post(f'/utilizadores/{novo.pk}/recusar/')
        self.assertFalse(User.objects.filter(pk=novo.pk).exists())

    def test_deactivated_user_not_listed_as_pending(self):
        old = User.objects.create_user('antigo', password='x')
        User.objects.filter(pk=old.pk).update(is_active=False, last_login='2026-01-01T00:00Z')
        self.client.force_login(self.staff)
        r = self.client.get('/utilizadores/pendentes/')
        self.assertNotIn(old, r.context['pending'])

    def test_non_staff_cannot_manage_users(self):
        self.client.force_login(User.objects.create_user('normal', password='x'))
        self.assertEqual(self.client.get('/utilizadores/pendentes/').status_code, 302)

    def test_logout_requires_post(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get('/logout/').status_code, 405)
        r = self.client.post('/logout/')
        self.assertRedirects(r, '/login/', fetch_redirect_response=False)

    def test_login_throttled_after_repeated_failures(self):
        for _ in range(10):
            self.login('staff', 'errada')
        r = self.login('staff', 'x')  # correct password, but locked
        self.assertIn('Demasiadas tentativas', r.context['login_error'])

    def test_login_redirects_to_safe_next_only(self):
        r = self.login('staff', 'x', next_url='/calendario/')
        self.assertRedirects(r, '/calendario/', fetch_redirect_response=False)
        self.client.logout()
        r = self.login('staff', 'x', next_url='https://evil.example/')
        self.assertRedirects(r, '/', fetch_redirect_response=False)

    @override_settings(CARTO_API_KEY='carto-k', MAPTILER_API_KEY='mt-k', STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
    def test_weather_page_loads_static_assets_and_config(self):
        self.client.force_login(self.staff)
        r = self.client.get('/meteorologia/')
        self.assertContains(r, '/static/core/firedpt.js')
        self.assertContains(r, '/static/core/firedpt.css')
        self.assertContains(r, '"maptilerKey": "mt-k"')
        self.assertContains(r, '"cartoKey": "carto-k"')

    def test_pages_require_login(self):
        for url in ['/', '/calendario/', '/meteorologia/', '/parcelas/', '/preplan/', '/operacionais/']:
            self.assertEqual(self.client.get(url).status_code, 302, url)


@override_settings(SECURE_SSL_REDIRECT=False)
class PasswordResetTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('maria', email='maria@example.com', password='Antiga-Pass-2026')

    def request_reset(self, email='maria@example.com'):
        with mock.patch('core.views._send_async') as send:
            r = self.client.post('/password/recuperar/', {'email': email})
        self.assertRedirects(r, '/password/recuperar/enviado/', fetch_redirect_response=False)
        return send

    def reset_link(self, send):
        body = send.call_args.args[1]
        return next(line for line in body.splitlines() if '/password/repor/' in line).split('testserver', 1)[1]

    def test_login_page_links_to_reset(self):
        self.assertContains(self.client.get('/login/'), '/password/recuperar/')

    def test_full_reset_flow(self):
        send = self.request_reset()
        self.assertEqual(send.call_args.args[2], ['maria@example.com'])
        self.assertIn('Recuperação de password', send.call_args.args[0])
        link = self.reset_link(send)

        r = self.client.get(link, follow=True)  # Django swaps the token for a session token
        self.assertTrue(r.context['validlink'])
        r = self.client.post(r.redirect_chain[-1][0], {'new_password1': STRONG_PW, 'new_password2': STRONG_PW})
        self.assertRedirects(r, '/password/repor/concluido/', fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(STRONG_PW))

        # Link is single-use
        r = self.client.get(link, follow=True)
        self.assertFalse(r.context['validlink'])

    def test_weak_new_password_rejected(self):
        link = self.reset_link(self.request_reset())
        r = self.client.get(link, follow=True)
        r = self.client.post(r.redirect_chain[-1][0], {'new_password1': '123', 'new_password2': '123'})
        self.assertEqual(r.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Antiga-Pass-2026'))

    def test_unknown_or_pending_email_sends_nothing(self):
        User.objects.create_user('pend', email='pend@example.com', password='x', is_active=False)
        self.assertFalse(self.request_reset('ninguem@example.com').called)
        self.assertFalse(self.request_reset('pend@example.com').called)

    def test_reset_requests_throttled(self):
        sends = [self.request_reset().called for _ in range(4)]
        self.assertEqual(sends, [True, True, True, False])

    def test_reset_lifts_login_lockout(self):
        for _ in range(10):
            self.client.post('/login/', {'form_type': 'login', 'username': 'maria', 'password': 'errada'})
        link = self.reset_link(self.request_reset())
        r = self.client.get(link, follow=True)
        self.client.post(r.redirect_chain[-1][0], {'new_password1': STRONG_PW, 'new_password2': STRONG_PW})
        r = self.client.post('/login/', {'form_type': 'login', 'username': 'maria', 'password': STRONG_PW})
        self.assertRedirects(r, '/', fetch_redirect_response=False)

    def test_invalid_token(self):
        r = self.client.get('/password/repor/MQ/token-invalido/')
        self.assertFalse(r.context['validlink'])
