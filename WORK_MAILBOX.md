# Individual work email

Each active, non-viewer member connects one personal work mailbox from **Mail → My work email**. Enter the provider's IMAP and SMTP hostnames, ports, SSL/TLS or STARTTLS options, username, and mailbox or app password. The page tests both incoming and outgoing connections before saving. Staff, HR and owners can only see their own mailbox; HR and platform administrators cannot read staff messages. The provider remains the source of messages and folders; DIGI HR does not persist message bodies or attachment files.

## Provider compatibility

Standard IMAP and SMTP over implicit SSL/TLS or STARTTLS are supported. Common ports are IMAP 993 (SSL/TLS), IMAP 143 (STARTTLS), SMTP 465 (SSL/TLS), and SMTP 587 (STARTTLS); use the actual values documented by the provider. The app requires certificate-verified TLS and rejects hosts that resolve to private or reserved IP addresses. Provider folder names are read from IMAP LIST and common names such as Sent, Drafts, Trash, Archive, Spam and Gmail's localized folders are recognized by name. Providers that use nonstandard folder names may require folder action adjustments. Drafts require a provider Drafts folder; archive and trash need matching folders.

Inbox pages retrieve at most 50 headers at a time. Individual message display is limited to 20 MiB, and attachment downloads are rejected if the full provider message exceeds that limit or the selected attachment exceeds 15 MiB. Data is fetched on demand; there is no background synchronization service or local message cache. Page reloads make new provider requests.

## Encryption key configuration

Mailbox passwords are encrypted with Fernet authenticated encryption. Keys live outside the database in deployment secrets; the app does not generate or persist keys. Generate one for a local development environment with:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Set these variables in the process environment or local `.env` file (never commit real values):

```text
MAILBOX_ENCRYPTION_KEYS={"v1":"<generated-urlsafe-fernet-key>"}
MAILBOX_ENCRYPTION_CURRENT_KEY_ID=v1
```

If the keyring or current ID is missing or invalid, the app fails closed for connection saves and credential reads. Development may use a dedicated test key. Production must use a secret manager, unique high-entropy keys, restricted access, and encrypted backups. Do not reuse a committed/example key.

### Rotate a key

1. Generate a new key ID and key.
2. Deploy both keys in `MAILBOX_ENCRYPTION_KEYS`, with `MAILBOX_ENCRYPTION_CURRENT_KEY_ID` set to the new ID.
3. Run `python manage.py rotate_work_mailbox_keys`.
4. Check the number reported and verify users can reconnect/read their mail.
5. Keep the previous key available for backups and rollback. Remove it only after verifying all live credentials were re-encrypted and the backup retention window has passed.

## Disconnect and lifecycle

From **Mail → My work email**, choose **Disconnect**. This erases the saved ciphertext and key ID and disables the DIGI HR connection; it does not delete the provider account or messages. Deactivating/removing the organization membership, deactivating the user, or terminating/deactivating their employee record also clears the saved credentials. Reconnecting requires testing and saving the provider configuration again.

## System email remains separate

Password resets, invitations, access-request notifications, onboarding messages, birthday notices and other platform emails continue using the existing `DJANGO_EMAIL_*` / `EMAIL_*` settings. They do not use an employee's mailbox and personal SMTP sending has no fallback to platform SMTP.

## Local and production configuration

For local development, use mock clients in automated tests or a disposable provider test mailbox and keep its password/key only in a local, ignored `.env`. For production, configure platform SMTP separately, store the Fernet keyring in the deployment secret manager, enforce HTTPS and secure session cookies, and allow controlled outbound access to the organization's approved mail providers. Configure process and proxy request-size limits for compose uploads; the app limits attachments to 15 MiB total per message. The database needs no new schema changes after migrations 0048–0049. No Redis, Celery or worker is required by the current on-demand design.

## Troubleshooting

- **Login rejected:** confirm the full mailbox username, password or provider app password, and whether IMAP/SMTP access is enabled by the provider.
- **Server address not found:** verify the exact incoming/outgoing hostnames from the provider.
- **Secure connection failed:** check the port/security pair and provider TLS certificate. Plaintext transport is not supported.
- **Refresh/send timed out:** check outbound firewall/DNS access and provider availability; retry after the connection is restored.
- **Folder action unavailable:** the account needs a provider folder recognizable as Drafts, Archive or Trash. Provider names/capabilities vary.
- **Credential decryption error:** restore the key ID used by the stored credential from the secret manager or backup. Do not delete old keys until all connections have been rotated.
- **Message/attachment too large:** open or download it from the provider's own webmail client.

## Manual provider test before production

Automated tests mock IMAP and SMTP and are not evidence of successful provider interoperability. With a disposable, authorized mailbox, test SSL/TLS and STARTTLS as offered by that provider: connect; receive a message and reply; send to an external test address; reply and forward; inspect Inbox/Sent/Drafts/Archive/Trash and provider-specific folders; change read/unread and starred flags; save a draft; send and download a safe attachment; test a large attachment; disconnect and reconnect; then confirm membership deactivation blocks access. Record provider, date, ports/security, folder names and outcome without recording the password or message content. No real-provider credentials are configured in the current development workspace, so these checks remain outstanding.
