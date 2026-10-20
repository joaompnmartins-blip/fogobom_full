from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from .models import Operative


@override_settings(SECURE_SSL_REDIRECT=False)
class OperativeTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user('u', password='x'))

    def test_create_with_optional_fields_empty(self):
        r = self.client.post('/operacionais/novo/', {'name': 'Op'})
        self.assertRedirects(r, '/operacionais/', fetch_redirect_response=False)
        self.assertEqual(Operative.objects.get().email, '')

    def test_invalid_input_rejected_and_kept(self):
        r = self.client.post('/operacionais/novo/', {'name': '', 'email': 'nao-email'})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Operative.objects.exists())
        self.assertContains(r, 'nao-email')

    def test_edit(self):
        op = Operative.objects.create(name='Op', email='a@example.com', phone='1', certification_level='A')
        self.client.post(f'/operacionais/{op.pk}/editar/', {'name': 'Op 2', 'phone': '2'})
        op.refresh_from_db()
        self.assertEqual((op.name, op.phone), ('Op 2', '2'))

    def test_only_staff_can_delete(self):
        op = Operative.objects.create(name='Op', email='a@example.com', phone='1', certification_level='A')
        self.client.post(f'/operacionais/{op.pk}/eliminar/')
        self.assertTrue(Operative.objects.exists())
