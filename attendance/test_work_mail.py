from email.message import EmailMessage as MIMEMessage
from unittest.mock import ANY, Mock, call, patch
from cryptography.fernet import Fernet
from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from .mailbox_security import decrypt_password, encrypt_password
from .mailbox_service import MailConfig, _validate_host, list_messages, list_folder_metadata, test_connections
from .models import Category, Employee, Organization, OrganizationMembership, WorkMailbox


KEY_ONE = Fernet.generate_key().decode('ascii')
KEY_TWO = Fernet.generate_key().decode('ascii')


@override_settings(
    MAILBOX_ENCRYPTION_KEYS={'test-v1': KEY_ONE, 'test-v2': KEY_TWO},
    MAILBOX_ENCRYPTION_CURRENT_KEY_ID='test-v1',
)
class WorkMailboxTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Work Mail Co', slug='work-mail-co', setup_completed=True)
        self.user = User.objects.create_user('mail_member', email='profile@example.com', password='test-pass-123')
        self.membership = OrganizationMembership.objects.create(user=self.user, organization=self.org, role='employee')
        self.client = Client()
        self.client.force_login(self.user)

    def make_mailbox(self, user=None, org=None, email_address='work@example.net'):
        key_id, ciphertext = encrypt_password('work-secret')
        return WorkMailbox.objects.create(
            organization=org or self.org, user=user or self.user,
            email_address=email_address, username=email_address,
            password_ciphertext=ciphertext, encryption_key_id=key_id,
            imap_host='imap.example.net', imap_port=993, imap_security='ssl',
            smtp_host='smtp.example.net', smtp_port=587, smtp_security='starttls',
        )

    def config(self, **overrides):
        values = {
            'email_address': 'work@example.net', 'username': 'work@example.net', 'password': 'secret',
            'imap_host': 'imap.example.net', 'imap_port': 993, 'imap_security': 'ssl',
            'smtp_host': 'smtp.example.net', 'smtp_port': 587, 'smtp_security': 'starttls',
        }
        values.update(overrides)
        return MailConfig.from_mapping(values)

    def test_mailbox_credentials_are_encrypted_and_rotatable(self):
        mailbox = self.make_mailbox()
        self.assertNotIn('work-secret', mailbox.password_ciphertext)
        self.assertEqual(decrypt_password(mailbox.password_ciphertext, mailbox.encryption_key_id), 'work-secret')
        with override_settings(MAILBOX_ENCRYPTION_CURRENT_KEY_ID='test-v2'):
            from .mailbox_security import rotate_mailbox_credentials
            self.assertEqual(rotate_mailbox_credentials(), 1)
            mailbox.refresh_from_db()
            self.assertEqual(mailbox.encryption_key_id, 'test-v2')
            self.assertEqual(decrypt_password(mailbox.password_ciphertext, mailbox.encryption_key_id), 'work-secret')

    def test_connection_test_checks_both_secure_protocols(self):
        imap, smtp = Mock(), Mock()
        imap.select.return_value = ('OK', [b''])
        with patch('attendance.mailbox_service._validate_host'), \
             patch('attendance.mailbox_service.connect_imap', return_value=imap) as open_imap, \
             patch('attendance.mailbox_service.connect_smtp', return_value=smtp) as open_smtp:
            self.assertTrue(test_connections(self.config()))
        open_imap.assert_called_once()
        open_smtp.assert_called_once()
        imap.logout.assert_called_once()
        smtp.quit.assert_called_once()

    def test_transport_connectors_negotiate_tls_before_authentication(self):
        config = self.config(imap_security='starttls', smtp_security='starttls')
        imap, smtp = Mock(), Mock()
        with patch('attendance.mailbox_service._validate_host', return_value=[]), \
             patch('attendance.mailbox_service._PinnedIMAP', return_value=imap), \
             patch('attendance.mailbox_service._PinnedSMTP', return_value=smtp):
            from .mailbox_service import connect_imap, connect_smtp
            connect_imap(config)
            connect_smtp(config)
        self.assertLess(imap.method_calls.index(call.starttls(ssl_context=ANY)), imap.method_calls.index(call.login(config.username, config.password)))
        self.assertLess(smtp.method_calls.index(call.starttls(context=ANY)), smtp.method_calls.index(call.login(config.username, config.password)))

    def test_failed_authentication_closes_partially_open_connections(self):
        from .mailbox_service import connect_imap, connect_smtp
        config = self.config(imap_security='ssl', smtp_security='ssl')
        imap, smtp = Mock(), Mock()
        imap.login.side_effect = OSError('provider login rejected')
        smtp.login.side_effect = OSError('provider login rejected')
        with patch('attendance.mailbox_service._validate_host', return_value=[]), \
             patch('attendance.mailbox_service._PinnedIMAPSSL', return_value=imap), \
             patch('attendance.mailbox_service._PinnedSMTPSSL', return_value=smtp):
            with self.assertRaises(OSError): connect_imap(config)
            with self.assertRaises(OSError): connect_smtp(config)
        imap.logout.assert_called_once()
        smtp.quit.assert_called_once()

    def test_rejects_plaintext_transport_and_bad_ports(self):
        with self.assertRaisesRegex(ValueError, 'Unencrypted'):
            self.config(imap_security='none')
        with self.assertRaisesRegex(ValueError, 'ports'):
            self.config(smtp_port=70000)
        with self.assertRaisesRegex(ValueError, 'Private or reserved'):
            _validate_host('127.0.0.1')

    def test_socket_connects_to_the_validated_public_dns_result(self):
        import socket
        from .mailbox_service import _connect_to_pinned
        addresses = [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('93.184.216.34', 0))]
        connection = Mock()
        with patch('attendance.mailbox_service.socket.socket', return_value=connection) as create_socket, \
             patch('attendance.mailbox_service.socket.create_connection', side_effect=AssertionError('DNS must not be resolved again')):
            self.assertIs(_connect_to_pinned(addresses, 993, 12), connection)
        create_socket.assert_called_once_with(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP)
        connection.connect.assert_called_once_with(('93.184.216.34', 993))

    def test_provider_special_use_flags_override_localized_folder_names(self):
        mailbox = self.make_mailbox()
        imap = Mock()
        imap.list.return_value = ('OK', [
            b'(\\HasNoChildren \\Sent) "/" "Elementos enviados"',
            b'(\\HasNoChildren \\Trash) "/" "Corbeille"',
        ])
        with patch('attendance.mailbox_service.connect_imap', return_value=imap):
            folders = list_folder_metadata(mailbox)
        self.assertEqual({item['name']: item['kind'] for item in folders}, {
            'Elementos enviados': 'sent', 'Corbeille': 'trash',
        })

    def test_invalid_credentials_never_save_a_connection_or_leak_provider_error(self):
        data = {
            'email_address': 'work@example.net', 'username': 'work@example.net', 'password': 'top-secret-password',
            'imap_host': 'imap.example.net', 'imap_port': '993', 'imap_security': 'ssl',
            'smtp_host': 'smtp.example.net', 'smtp_port': '465', 'smtp_security': 'ssl',
            'action': 'save',
        }
        with patch('attendance.mailbox_views.test_connections', side_effect=OSError('bad password top-secret-password')):
            response = self.client.post(reverse('my_work_email'), data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(WorkMailbox.objects.exists())
        self.assertNotContains(response, 'top-secret-password')

    def test_connection_must_test_before_save_and_empty_state_is_personal(self):
        empty = self.client.get(reverse('mail_dashboard'))
        self.assertContains(empty, 'Connect work email')
        self.assertContains(empty, 'private to your account')
        data = {
            'email_address': 'alternate@company.org', 'username': '', 'password': 'secret',
            'imap_host': 'imap.example.net', 'imap_port': '993', 'imap_security': 'ssl',
            'smtp_host': 'smtp.example.net', 'smtp_port': '465', 'smtp_security': 'ssl', 'action': 'test',
        }
        with patch('attendance.mailbox_views.test_connections', return_value=True):
            response = self.client.post(reverse('my_work_email'), data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(WorkMailbox.objects.exists())
        self.assertContains(response, 'Nothing was saved')
        data['action'] = 'save'
        with patch('attendance.mailbox_views.test_connections', return_value=True):
            response = self.client.post(reverse('my_work_email'), data)
        mailbox = WorkMailbox.objects.get(user=self.user, organization=self.org)
        self.assertRedirects(response, reverse('mail_dashboard'))
        self.assertEqual(mailbox.email_address, 'alternate@company.org')
        self.assertEqual(mailbox.username, 'alternate@company.org')
        self.assertTrue(mailbox.is_connected)

    def test_send_uses_only_connected_mailbox_and_never_falls_back(self):
        mailbox = self.make_mailbox()
        smtp = Mock()
        with patch('attendance.mailbox_service.connect_smtp', return_value=smtp), \
             patch('attendance.mailbox_service.append_sent_copy', return_value=True):
            from .mailbox_service import send_message
            upload = SimpleUploadedFile('notes.txt', b'private attachment', content_type='text/plain')
            send_message(mailbox, to='recipient@example.org', subject='Hello', body='Message', attachments=[upload])
        sent = smtp.send_message.call_args
        self.assertEqual(sent.kwargs['from_addr'], mailbox.email_address)
        self.assertEqual(sent.args[0]['From'], mailbox.email_address)
        self.assertTrue(sent.args[0].is_multipart())
        smtp.quit.assert_called_once()
        with patch('attendance.mailbox_service.connect_smtp', side_effect=OSError('provider unavailable')):
            response = self.client.post(reverse('mail_compose'), {
                'action': 'send', 'to': 'recipient@example.org', 'subject': 'No fallback', 'body': 'Do not relay',
            })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'message could not be sent')

    def test_sent_copy_uses_provider_special_use_sent_folder(self):
        from .mailbox_service import append_sent_copy
        mailbox = self.make_mailbox()
        message = MIMEMessage()
        message['From'] = mailbox.email_address
        message['To'] = 'recipient@example.net'
        message['Subject'] = 'Hello'
        message.set_content('Message')
        imap = Mock()
        imap.list.return_value = ('OK', [b'(\\HasNoChildren \\Sent) "/" "Elementos enviados"'])
        imap.append.return_value = ('OK', [b'APPEND completed'])
        with patch('attendance.mailbox_service.connect_imap', return_value=imap):
            self.assertTrue(append_sent_copy(mailbox, message))
        self.assertEqual(imap.append.call_args.args[0], 'Elementos enviados')
        self.assertIn(b'Subject: Hello', imap.append.call_args.args[3])
        imap.logout.assert_called_once()

    def test_sent_copy_failure_does_not_raise_after_delivery(self):
        from .mailbox_service import append_sent_copy
        mailbox = self.make_mailbox()
        with patch('attendance.mailbox_service.connect_imap', side_effect=OSError('provider unavailable')):
            self.assertFalse(append_sent_copy(mailbox, MIMEMessage()))

    def test_imap_attachment_download_uses_mailbox_folder_and_uid(self):
        from email.message import EmailMessage
        from .mailbox_service import fetch_attachment
        mailbox = self.make_mailbox()
        message = EmailMessage()
        message['From'] = 'sender@example.org'
        message['To'] = mailbox.email_address
        message['Subject'] = 'With attachment'
        message.set_content('Hello')
        message.add_attachment(b'actual attachment bytes', maintype='application', subtype='octet-stream', filename='report.bin')
        raw = message.as_bytes()
        imap = Mock()
        imap.select.return_value = ('OK', [b''])
        imap.uid.side_effect = [
            ('OK', [(b'42 (RFC822.SIZE 500)', None)]),
            ('OK', [(b'42 (BODY[] {100})', raw)]),
        ]
        with patch('attendance.mailbox_service.connect_imap', return_value=imap):
            filename, content_type, data = fetch_attachment(mailbox, 'INBOX', '42', 2)
        self.assertEqual(filename, 'report.bin')
        self.assertEqual(content_type, 'application/octet-stream')
        self.assertEqual(data, b'actual attachment bytes')

    def test_attachment_rejects_invalid_uid_before_provider_call(self):
        from .mailbox_service import fetch_attachment
        mailbox = self.make_mailbox()
        imap = Mock()
        with patch('attendance.mailbox_service.connect_imap', return_value=imap):
            with self.assertRaisesRegex(ValueError, 'Invalid message identifier'):
                fetch_attachment(mailbox, 'INBOX', '1\\r\\nLOGOUT', 2)
        imap.uid.assert_not_called()

    def test_large_attachment_message_is_rejected_before_body_download(self):
        from .mailbox_service import MAX_MESSAGE_BYTES, fetch_attachment
        mailbox = self.make_mailbox()
        imap = Mock()
        imap.uid.return_value = ('OK', [(b'42 (RFC822.SIZE %d)' % (MAX_MESSAGE_BYTES + 1), None)])
        with patch('attendance.mailbox_service.connect_imap', return_value=imap):
            with self.assertRaisesRegex(ValueError, 'download limit'):
                fetch_attachment(mailbox, 'INBOX', '42', 2)
        self.assertEqual(imap.uid.call_count, 1)

    def test_list_messages_paginates_and_keeps_body_search_results(self):
        mailbox = self.make_mailbox()
        imap = Mock()
        imap.select.return_value = ('OK', [b''])
        # UID SEARCH has already matched a body occurrence; its headers need not repeat the term.
        imap.uid.side_effect = [
            ('OK', [b'1 2 3']),
            ('OK', [(b'2 (FLAGS () RFC822.SIZE 30 BODY[HEADER] {20}', b'Subject: Other subject\\r\\n\\r\\n')]),
        ]
        with patch('attendance.mailbox_service.connect_imap', return_value=imap):
            rows, page = list_messages(mailbox, query='needle', page=2, limit=1, return_page_info=True)
        self.assertEqual([row['uid'] for row in rows], ['2'])
        self.assertEqual(page, {'has_older': True, 'has_newer': True, 'page': 2})
        self.assertEqual(imap.uid.call_args_list[0].args, ('search', None, '(TEXT "needle")'))

    def test_friendly_mail_errors_do_not_echo_provider_details(self):
        import smtplib
        from .mailbox_service import friendly_mail_error
        error = smtplib.SMTPAuthenticationError(535, b'bad login secret-password')
        message = friendly_mail_error(error)
        self.assertIn('Check the username, password or app password', message)
        self.assertNotIn('secret-password', message)

    def test_live_imap_sync_returns_headers_and_no_saved_content(self):
        mailbox = self.make_mailbox()
        imap = Mock()
        imap.select.return_value = ('OK', [b''])
        imap.uid.side_effect = [
            ('OK', [b'42']),
            ('OK', [(b'42 (FLAGS (\\Seen \\Flagged) RFC822.SIZE 250 BODY[HEADER] {40}', b'From: Person <p@example.org>\r\nSubject: Annual review\r\nDate: Mon, 9 Nov 2026 09:00:00 +0000\r\n\r\n')]),
        ]
        with patch('attendance.mailbox_service.connect_imap', return_value=imap):
            rows = list_messages(mailbox)
        self.assertEqual(rows[0]['subject'], 'Annual review')
        self.assertTrue(rows[0]['is_read'])
        self.assertTrue(rows[0]['is_starred'])
        self.assertFalse(hasattr(mailbox, 'messages'))

    def test_search_and_star_actions_use_provider_imap_commands(self):
        from .mailbox_service import message_action
        mailbox = self.make_mailbox()
        imap = Mock()
        imap.select.return_value = ('OK', [b''])
        imap.uid.side_effect = [
            ('OK', [b'12']),
            ('OK', [(b'12 (FLAGS () BODY[HEADER] {20}', b'Subject: Search hit\r\n\r\n')]),
            ('OK', [b'']),
        ]
        with patch('attendance.mailbox_service.connect_imap', return_value=imap):
            result = list_messages(mailbox, query='hit')
            message_action(mailbox, 'INBOX', '12', 'star')
        self.assertEqual(result[0]['subject'], 'Search hit')
        self.assertEqual(imap.uid.call_args_list[0].args, ('search', None, '(TEXT "hit")'))
        self.assertIn(call('store', '12', '+FLAGS', '(\\Flagged)'), imap.uid.call_args_list)

    def test_mailbox_routes_resolve_only_authenticated_users_own_connection(self):
        self.make_mailbox()
        peer = User.objects.create_user('mail_peer', email='peer@example.net', password='test-pass-123')
        OrganizationMembership.objects.create(user=peer, organization=self.org, role='employee')
        peer_client = Client()
        peer_client.force_login(peer)
        own = self.client.get(reverse('my_work_email'))
        other = peer_client.get(reverse('my_work_email'))
        self.assertContains(own, 'work@example.net')
        self.assertNotContains(other, 'work@example.net')
        self.assertEqual(WorkMailbox.objects.filter(user=peer).count(), 0)

    def test_hr_and_cross_company_users_cannot_address_another_mailbox_by_url_or_parameter(self):
        staff_mailbox = self.make_mailbox()
        hr = User.objects.create_user('mail_hr', password='test-pass-123')
        OrganizationMembership.objects.create(user=hr, organization=self.org, role='hr_admin')
        hr_client = Client()
        hr_client.force_login(hr)
        another_org = Organization.objects.create(name='Other Mail Co', slug='other-mail-co', setup_completed=True)
        peer = User.objects.create_user('other_mail_user', password='test-pass-123')
        OrganizationMembership.objects.create(user=peer, organization=another_org, role='employee')
        peer_mailbox = self.make_mailbox(user=peer, org=another_org, email_address='other@company.org')
        peer_client = Client()
        peer_client.force_login(peer)
        with patch('attendance.mailbox_views.list_folder_metadata', return_value=[{'name': 'INBOX', 'kind': 'inbox'}]), \
             patch('attendance.mailbox_views.list_messages', side_effect=lambda mailbox, **kwargs: [{'uid':'7','from':mailbox.email_address,'to':'','subject':'Private','date':'','flags':'','folder':'INBOX','is_read':True,'is_starred':False}]) as listing:
            staff_page = self.client.get(reverse('mail_dashboard') + f'?mailbox_id={peer_mailbox.pk}')
            peer_page = peer_client.get(reverse('mail_dashboard') + f'?mailbox_id={staff_mailbox.pk}')
            self.assertContains(staff_page, staff_mailbox.email_address)
            self.assertNotContains(staff_page, peer_mailbox.email_address)
            self.assertContains(peer_page, peer_mailbox.email_address)
            self.assertNotContains(peer_page, staff_mailbox.email_address)
            self.assertEqual([call.args[0].user_id for call in listing.call_args_list], [self.user.pk, peer.pk])
        empty_for_hr = hr_client.get(reverse('mail_dashboard'))
        self.assertContains(empty_for_hr, 'Connect work email')
        self.assertNotContains(empty_for_hr, staff_mailbox.email_address)

    def test_platform_superuser_without_membership_cannot_use_company_mail_routes(self):
        admin = User.objects.create_superuser('mail_platform_admin', email='platform@example.org', password='pw123456')
        client = Client()
        client.force_login(admin)
        response = client.get(reverse('mail_dashboard'), follow=True)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(WorkMailbox.objects.filter(user=admin).exists())

    def test_onboarding_tracker_remains_separate_and_contains_no_shared_inbox(self):
        hr = User.objects.create_user('tracker_hr', password='test-pass-123')
        OrganizationMembership.objects.create(user=hr, organization=self.org, role='hr_admin')
        client = Client()
        client.force_login(hr)
        response = client.get(reverse('onboarding_mail_tracker'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Onboarding invitation tracker')
        self.assertNotContains(response, 'Recent Inbox')
        self.assertContains(response, reverse('applicant_invite'))

    def test_disconnect_erases_credentials_but_keeps_hr_account_and_employee(self):
        mailbox = self.make_mailbox()
        response = self.client.post(reverse('my_work_email'), {'action': 'disconnect'})
        mailbox.refresh_from_db()
        self.assertRedirects(response, reverse('my_work_email'))
        self.assertFalse(mailbox.is_connected)
        self.assertEqual(mailbox.password_ciphertext, '')
        self.assertEqual(mailbox.encryption_key_id, '')
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_membership_deactivation_removal_and_user_deactivation_revoke_credentials(self):
        mailbox = self.make_mailbox()
        self.membership.is_active = False
        self.membership.save(update_fields=['is_active'])
        mailbox.refresh_from_db()
        self.assertFalse(mailbox.is_connected)
        self.assertEqual(mailbox.password_ciphertext, '')
        client = Client()
        client.force_login(self.user)
        response = client.get(reverse('mail_dashboard'), follow=True)
        self.assertEqual(response.status_code, 403)

        self.membership.is_active = True
        self.membership.save(update_fields=['is_active'])
        mailbox.password_ciphertext = encrypt_password('again')[1]
        mailbox.encryption_key_id = 'test-v1'
        mailbox.is_connected = True
        mailbox.save()
        self.membership.delete()
        mailbox.refresh_from_db()
        self.assertFalse(mailbox.is_connected)
        self.assertEqual(mailbox.password_ciphertext, '')

        self.membership = OrganizationMembership.objects.create(user=self.user, organization=self.org, role='employee')
        mailbox.password_ciphertext = encrypt_password('again')[1]
        mailbox.encryption_key_id = 'test-v1'
        mailbox.is_connected = True
        mailbox.save()
        self.user.is_active = False
        self.user.save(update_fields=['is_active'])
        mailbox.refresh_from_db()
        self.assertFalse(mailbox.is_connected)
        self.assertEqual(mailbox.password_ciphertext, '')

    def test_bulk_membership_deactivation_and_bulk_update_revoke_credentials(self):
        mailbox = self.make_mailbox()
        OrganizationMembership.objects.filter(pk=self.membership.pk).update(is_active=False)
        mailbox.refresh_from_db()
        self.assertEqual(mailbox.password_ciphertext, '')
        self.membership.refresh_from_db()
        self.membership.is_active = True
        self.membership.save(update_fields=['is_active'])
        mailbox.password_ciphertext = encrypt_password('new-secret')[1]
        mailbox.encryption_key_id = 'test-v1'
        mailbox.is_connected = True
        mailbox.save()
        self.membership.is_active = False
        OrganizationMembership.objects.bulk_update([self.membership], ['is_active'])
        mailbox.refresh_from_db()
        self.assertFalse(mailbox.is_connected)
        self.assertEqual(mailbox.password_ciphertext, '')

    def test_bulk_user_deactivation_paths_revoke_credentials(self):
        mailbox = self.make_mailbox()
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        mailbox.refresh_from_db()
        self.assertEqual(mailbox.password_ciphertext, '')
        self.user.refresh_from_db()
        self.user.is_active = True
        self.user.save(update_fields=['is_active'])
        mailbox.password_ciphertext = encrypt_password('again')[1]
        mailbox.encryption_key_id = 'test-v1'
        mailbox.is_connected = True
        mailbox.save()
        self.user.is_active = False
        User.objects.bulk_update([self.user], ['is_active'])
        mailbox.refresh_from_db()
        self.assertFalse(mailbox.is_connected)
        self.assertEqual(mailbox.password_ciphertext, '')

    def test_employee_termination_and_bulk_deactivation_revoke_credentials(self):
        category = Category.objects.create(organization=self.org, name='Staff', code='STAFF')
        employee = Employee.objects.create(
            organization=self.org, user=self.user, employee_id='MAIL-1', category=category,
            first_name='Mail', last_name='Member', email='work@example.net', phone='08000000000', gender='FEMALE',
        )
        mailbox = self.make_mailbox()
        employee.employment_status = 'terminated'
        employee.save(update_fields=['employment_status', 'updated_at'])
        mailbox.refresh_from_db()
        self.assertFalse(mailbox.is_connected)
        employee.employment_status = 'active'
        employee.save(update_fields=['employment_status', 'updated_at'])
        mailbox.password_ciphertext = encrypt_password('again')[1]
        mailbox.encryption_key_id = 'test-v1'
        mailbox.is_connected = True
        mailbox.save()
        Employee.objects.filter(pk=employee.pk).update(is_active=False)
        mailbox.refresh_from_db()
        self.assertFalse(mailbox.is_connected)

    def test_settings_never_return_password_or_ciphertext(self):
        self.make_mailbox()
        response = self.client.get(reverse('my_work_email'))
        self.assertNotContains(response, 'work-secret')
        self.assertNotContains(response, 'password_ciphertext')


class MailConfigurationValidationTests(TestCase):
    def test_keyring_fails_closed_when_missing_or_unknown(self):
        from .mailbox_security import encrypt_password
        with override_settings(MAILBOX_ENCRYPTION_KEYS={}, MAILBOX_ENCRYPTION_CURRENT_KEY_ID=''):
            with self.assertRaises(ImproperlyConfigured): encrypt_password('secret')
        with override_settings(MAILBOX_ENCRYPTION_KEYS={'key': KEY_ONE}, MAILBOX_ENCRYPTION_CURRENT_KEY_ID='key'):
            with self.assertRaises(ImproperlyConfigured): decrypt_password('ciphertext', 'missing')


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
                   DEFAULT_FROM_EMAIL='system@example.test', EMAIL_HOST_USER='system-reply@example.test',
                   MAILBOX_ENCRYPTION_KEYS={'test-v1': KEY_ONE}, MAILBOX_ENCRYPTION_CURRENT_KEY_ID='test-v1')
class SystemEmailSeparationTests(TestCase):
    def test_birthday_system_email_uses_platform_sender_not_connected_user_mailbox(self):
        from datetime import date
        from django.core.management import call_command
        from .models import AttendanceSettings
        org = Organization.objects.create(name='System Email Co', slug='system-email-co', setup_completed=True)
        category = Category.objects.create(organization=org, name='Staff', code='STAFF')
        employee = Employee.objects.create(
            organization=org, employee_id='SYS-1', category=category, first_name='Sys', last_name='Person',
            email='birthday@example.test', phone='08000000000', gender='FEMALE', date_of_birth=date(1990, 11, 9),
        )
        user = User.objects.create_user('system_mailbox_user', password='test-pass-123')
        OrganizationMembership.objects.create(user=user, organization=org, role='employee')
        key_id, encrypted = encrypt_password('mail-secret')
        WorkMailbox.objects.create(
            organization=org, user=user, email_address='personal-work@example.test', username='personal-work@example.test',
            password_ciphertext=encrypted, encryption_key_id=key_id,
            imap_host='imap.example.test', imap_port=993, imap_security='ssl',
            smtp_host='smtp.example.test', smtp_port=465, smtp_security='ssl',
        )
        AttendanceSettings.objects.create(organization=org)
        call_command('send_birthday_messages', '--organization', org.slug, '--date', '2026-11-09')
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].from_email, 'system@example.test')
        self.assertEqual(mail.outbox[0].reply_to, ['system-reply@example.test'])
        self.assertEqual(mail.outbox[0].to, ['birthday@example.test'])
