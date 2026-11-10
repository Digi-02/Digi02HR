"""Live IMAP/SMTP operations. Message content is fetched on demand and never cached in Django."""
from dataclasses import dataclass
from email import message_from_bytes
from email.header import decode_header, make_header
from email.message import EmailMessage as MIMEMessage
from email.utils import formatdate, getaddresses, make_msgid
from html.parser import HTMLParser
import imaplib
import ipaddress
import re
import smtplib
import socket
import ssl
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from .mailbox_security import decrypt_password

TIMEOUT = 12
MAX_LIST = 100
PAGE_SIZE = 50
MAX_MESSAGE_BYTES = 20 * 1024 * 1024
MAX_ATTACHMENT_BYTES = 15 * 1024 * 1024
SECURITY = {'ssl', 'starttls'}


@dataclass(frozen=True)
class MailConfig:
    email_address: str
    username: str
    password: str
    imap_host: str
    imap_port: int
    imap_security: str
    smtp_host: str
    smtp_port: int
    smtp_security: str

    @classmethod
    def from_mapping(cls, data):
        email_address = (data.get('email_address') or '').strip()
        username = (data.get('username') or email_address).strip()
        try:
            validate_email(email_address)
            validate_email(username) if '@' in username else None
        except ValidationError as exc:
            raise ValueError('Enter a valid professional email address and username.') from exc
        result = cls(
            email_address=email_address, username=username,
            password=data.get('password') or '',
            imap_host=(data.get('imap_host') or '').strip().rstrip('.').lower(),
            imap_port=_port(data.get('imap_port')),
            imap_security=(data.get('imap_security') or 'ssl').lower(),
            smtp_host=(data.get('smtp_host') or '').strip().rstrip('.').lower(),
            smtp_port=_port(data.get('smtp_port')),
            smtp_security=(data.get('smtp_security') or 'ssl').lower(),
        )
        if not result.password:
            raise ValueError('Enter the mailbox password or app password.')
        if not result.imap_host or not result.smtp_host:
            raise ValueError('Enter both incoming and outgoing server hostnames.')
        if result.imap_security not in SECURITY or result.smtp_security not in SECURITY:
            raise ValueError('Choose SSL/TLS or STARTTLS. Unencrypted connections are not allowed.')
        return result

    @classmethod
    def from_mailbox(cls, mailbox):
        return cls(
            email_address=mailbox.email_address, username=mailbox.username,
            password=decrypt_password(mailbox.password_ciphertext, mailbox.encryption_key_id),
            imap_host=mailbox.imap_host, imap_port=mailbox.imap_port,
            imap_security=mailbox.imap_security, smtp_host=mailbox.smtp_host,
            smtp_port=mailbox.smtp_port, smtp_security=mailbox.smtp_security,
        )


def _port(value):
    try:
        port = int(value)
    except (ValueError, TypeError) as exc:
        raise ValueError('Enter a valid server port.') from exc
    if not 1 <= port <= 65535:
        raise ValueError('Server ports must be between 1 and 65535.')
    return port


def _validate_host(host):
    if not host or len(host) > 253 or any(ch.isspace() for ch in host):
        raise ValueError('Enter a valid mail server hostname.')
    if host.lower() in {'localhost', 'localhost.localdomain'} or host.endswith(('.local', '.internal', '.localhost')):
        raise ValueError('Mail server must use a public hostname.')
    try:
        address = ipaddress.ip_address(host.strip('[]'))
        if not address.is_global:
            raise ValueError('Private or reserved mail server addresses are not allowed.')
    except ValueError as exc:
        if str(exc).startswith(('Private', 'Mail server')):
            raise
        if not re.fullmatch(r'(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}', host, re.I):
            raise ValueError('Enter a valid public mail server hostname.') from exc
    try:
        addresses = socket.getaddrinfo(host.strip('[]'), None, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError('Mail server hostname could not be resolved.') from exc
    if not addresses or any(not ipaddress.ip_address(item[4][0].split('%')[0]).is_global for item in addresses):
        raise ValueError('Mail server must resolve only to public addresses.')
    return addresses


def _connect_to_pinned(addresses, port, timeout):
    """Connect to the exact public DNS result checked above; don't resolve it again."""
    last_error = None
    for family, socktype, proto, _canonname, sockaddr in addresses:
        connection = socket.socket(family, socktype, proto)
        try:
            connection.settimeout(timeout)
            target = list(sockaddr)
            target[1] = port
            connection.connect(tuple(target))
            return connection
        except OSError as exc:
            last_error = exc
            connection.close()
    if last_error:
        raise last_error
    raise OSError('No usable mail-server address.')


class _PinnedIMAP(imaplib.IMAP4):
    def __init__(self, host, port, *, timeout, addresses):
        self._pinned_addresses = addresses
        super().__init__(host, port, timeout=timeout)

    def _create_socket(self, timeout):
        return _connect_to_pinned(self._pinned_addresses, self.port, timeout)


class _PinnedIMAPSSL(imaplib.IMAP4_SSL):
    def __init__(self, host, port, *, timeout, ssl_context, addresses):
        self._pinned_addresses = addresses
        super().__init__(host, port, timeout=timeout, ssl_context=ssl_context)

    def _create_socket(self, timeout):
        raw_socket = _connect_to_pinned(self._pinned_addresses, self.port, timeout)
        try:
            return self.ssl_context.wrap_socket(raw_socket, server_hostname=self.host)
        except Exception:
            raw_socket.close()
            raise


class _PinnedSMTP(smtplib.SMTP):
    def __init__(self, host, port, *, timeout, addresses):
        self._pinned_addresses = addresses
        super().__init__(host, port, timeout=timeout)

    def _get_socket(self, host, port, timeout):
        return _connect_to_pinned(self._pinned_addresses, port, timeout)


class _PinnedSMTPSSL(smtplib.SMTP_SSL):
    def __init__(self, host, port, *, timeout, context, addresses):
        self._pinned_addresses = addresses
        super().__init__(host, port, timeout=timeout, context=context)

    def _get_socket(self, host, port, timeout):
        raw_socket = _connect_to_pinned(self._pinned_addresses, port, timeout)
        try:
            return self.context.wrap_socket(raw_socket, server_hostname=self._host)
        except Exception:
            raw_socket.close()
            raise


def connect_imap(config):
    addresses = _validate_host(config.imap_host)
    context = ssl.create_default_context()
    client = None
    if config.imap_security == 'ssl':
        client = _PinnedIMAPSSL(config.imap_host, config.imap_port, ssl_context=context, timeout=TIMEOUT, addresses=addresses)
    else:
        client = _PinnedIMAP(config.imap_host, config.imap_port, timeout=TIMEOUT, addresses=addresses)
    try:
        if config.imap_security == 'starttls':
            client.starttls(ssl_context=context)
        client.login(config.username, config.password)
    except Exception:
        try: client.logout()
        except Exception:
            try: client.shutdown()
            except Exception: pass
        raise
    return client


def connect_smtp(config):
    addresses = _validate_host(config.smtp_host)
    context = ssl.create_default_context()
    if config.smtp_security == 'ssl':
        client = _PinnedSMTPSSL(config.smtp_host, config.smtp_port, timeout=TIMEOUT, context=context, addresses=addresses)
    else:
        client = _PinnedSMTP(config.smtp_host, config.smtp_port, timeout=TIMEOUT, addresses=addresses)
    try:
        if config.smtp_security == 'starttls':
            client.ehlo()
            client.starttls(context=context)
            client.ehlo()
        client.login(config.username, config.password)
    except Exception:
        try: client.quit()
        except Exception:
            try: client.close()
            except Exception: pass
        raise
    return client


def test_connections(config):
    imap = smtp = None
    try:
        imap = connect_imap(config)
        status, _ = imap.select('INBOX', readonly=True)
        if status != 'OK':
            raise ValueError('The IMAP server could not open the inbox.')
        smtp = connect_smtp(config)
        return True
    finally:
        if imap:
            try: imap.logout()
            except Exception: pass
        if smtp:
            try: smtp.quit()
            except Exception: pass


def safe_connection_error(_exc):
    # Do not return provider responses; some servers echo the supplied username or password.
    return 'Could not connect securely. Check the server, port, security type and credentials.'


def friendly_mail_error(exc, operation='mailbox'):
    """Map provider failures to safe, useful text without echoing server responses."""
    detail = str(exc).casefold()
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return 'The mail server timed out. Check your connection and try again.'
    if isinstance(exc, socket.gaierror):
        return 'The mail server address could not be found. Check the server hostname.'
    if isinstance(exc, ssl.SSLError):
        return 'A secure connection could not be established. Check the SSL/TLS setting and port.'
    if isinstance(exc, (imaplib.IMAP4.error, smtplib.SMTPAuthenticationError)) or any(
        token in detail for token in ('authentication', 'auth failed', 'login failed', 'invalid credentials')
    ):
        return 'The mail server rejected the login. Check the username, password or app password.'
    if operation == 'send':
        return 'The message could not be sent. Check the recipients and outgoing server settings.'
    if operation == 'attachment':
        return 'The attachment could not be downloaded. It may be unavailable or too large.'
    if operation == 'sync':
        return 'The mailbox could not be refreshed. Check the connection and try again.'
    return 'The mailbox operation failed. Check your connection settings and try again.'


def _decode(value):
    if not value:
        return ''
    try:
        return str(make_header(decode_header(value)))
    except (LookupError, UnicodeError, TypeError):
        return str(value)


def _folder_name(raw):
    text = raw.decode('utf-8', errors='replace') if isinstance(raw, bytes) else str(raw)
    match = re.search(r'(?:"(?:[^"\\]|\\.)*"|NIL)\s+("(?:[^"\\]|\\.)*"|[^\s]+)$', text)
    if not match:
        return text.strip().strip('"')
    name = match.group(1).strip()
    if name.startswith('"') and name.endswith('"'):
        name = name[1:-1].replace('\\"', '"').replace('\\\\', '\\')
    try:
        return imaplib.IMAP4._decode_utf7(name)
    except Exception:
        return name


def _folder_special_use(raw):
    text = raw.decode('utf-8', errors='replace') if isinstance(raw, bytes) else str(raw)
    match = re.match(r'^\(([^)]*)\)', text)
    return {token.casefold() for token in re.findall(r'\\[A-Za-z]+', match.group(1))} if match else set()


def list_folder_metadata(mailbox):
    config = MailConfig.from_mailbox(mailbox)
    client = connect_imap(config)
    try:
        status, rows = client.list()
        if status != 'OK':
            raise ValueError('Folder list unavailable.')
        result = {}
        for row in rows or []:
            name = _folder_name(row)
            result[name] = {'name': name, 'kind': folder_kind(name, _folder_special_use(row))}
        return sorted(result.values(), key=lambda item: (item['name'].lower() != 'inbox', item['name'].lower()))
    finally:
        try: client.logout()
        except Exception: pass


def list_folders(mailbox):
    return [item['name'] for item in list_folder_metadata(mailbox)]


def folder_kind(name, special_use=()):
    special_use = set(special_use)
    for special, kind in ((r'\inbox', 'inbox'), (r'\sent', 'sent'), (r'\drafts', 'drafts'),
                          (r'\trash', 'trash'), (r'\archive', 'archive'), (r'\all', 'archive'),
                          (r'\junk', 'spam'), (r'\spam', 'spam')):
        if special in special_use:
            return kind
    low = name.lower().replace('[gmail]/', '').replace('\\', '/')
    if low == 'inbox': return 'inbox'
    if 'sent' in low: return 'sent'
    if 'draft' in low: return 'drafts'
    if 'trash' in low or 'deleted' in low: return 'trash'
    if 'archive' in low or 'all mail' in low: return 'archive'
    if 'spam' in low or 'junk' in low: return 'spam'
    return 'folder'


def _fetch_bytes(client, uid, query):
    status, data = client.uid('fetch', str(uid).encode('ascii'), query)
    if status != 'OK' or not data:
        raise ValueError('Message is unavailable.')
    for part in data:
        if isinstance(part, tuple) and isinstance(part[1], bytes):
            return part[1]
    raise ValueError('Message is unavailable.')


def _header_message(raw):
    return message_from_bytes(raw)


def list_messages(mailbox, folder='INBOX', query='', limit=PAGE_SIZE, page=1, return_page_info=False):
    limit = min(max(int(limit), 1), PAGE_SIZE)
    page = max(int(page), 1)
    if folder == '__STARRED__':
        combined = []
        for name in list_folders(mailbox):
            combined.extend(item for item in list_messages(mailbox, name, query, MAX_LIST) if item['is_starred'])
        combined.sort(key=lambda item: item['uid'], reverse=True)
        start = (page - 1) * limit
        result = combined[start:start + limit]
        info = {'has_older': start + limit < len(combined), 'has_newer': page > 1, 'page': page}
        return (result, info) if return_page_info else result
    client = connect_imap(MailConfig.from_mailbox(mailbox))
    try:
        status, _ = client.select(folder, readonly=True)
        if status != 'OK':
            raise ValueError('Folder is unavailable.')
        if query:
            safe_query = ''.join(char for char in query if char.isprintable()).replace('\\', '\\\\').replace('"', '\\"')
            status, data = client.uid('search', None, f'(TEXT "{safe_query}")')
        else:
            status, data = client.uid('search', None, 'ALL')
        if status != 'OK' or not data or not data[0]:
            return []
        all_uids = data[0].split()
        end = max(0, len(all_uids) - (page - 1) * limit)
        start = max(0, end - limit)
        uids = all_uids[start:end]
        messages = []
        for uid in reversed(uids):
            status, rows = client.uid('fetch', uid, '(FLAGS RFC822.SIZE BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE)])')
            if status != 'OK' or not rows:
                continue
            raw = next((row[1] for row in rows if isinstance(row, tuple) and isinstance(row[1], bytes)), b'')
            headers = _header_message(raw)
            item = {
                'uid': uid.decode('ascii'), 'from': _decode(headers.get('From')),
                'to': _decode(headers.get('To')), 'subject': _decode(headers.get('Subject')) or '(No subject)',
                'date': _decode(headers.get('Date')), 'flags': str(rows[0][0]) if rows and isinstance(rows[0], tuple) else '',
                'folder': folder,
            }
            item['is_read'] = '\\Seen' in item['flags']
            item['is_starred'] = '\\Flagged' in item['flags']
            messages.append(item)
        info = {'has_older': start > 0, 'has_newer': page > 1, 'page': page}
        return (messages, info) if return_page_info else messages
    finally:
        try: client.logout()
        except Exception: pass


def get_message(mailbox, folder, uid):
    if not str(uid).isdigit():
        raise ValueError('Invalid message identifier.')
    client = connect_imap(MailConfig.from_mailbox(mailbox))
    try:
        status, _ = client.select(folder, readonly=True)
        if status != 'OK': raise ValueError('Folder is unavailable.')
        size_status, size_data = client.uid('fetch', str(uid).encode('ascii'), '(RFC822.SIZE)')
        if size_status != 'OK' or not size_data:
            raise ValueError('Message is unavailable.')
        size_match = re.search(rb'RFC822\.SIZE\s+(\d+)', b' '.join(
            item[0] if isinstance(item, tuple) else item for item in size_data if isinstance(item, (bytes, tuple))
        ))
        if size_match and int(size_match.group(1)) > MAX_MESSAGE_BYTES:
            raise ValueError('Message exceeds the viewing limit.')
        message = message_from_bytes(_fetch_bytes(client, uid, '(BODY.PEEK[])'))
        text_parts, html_parts, attachments = [], [], []
        if message.is_multipart():
            for idx, part in enumerate(message.walk()):
                if part.is_multipart(): continue
                disposition = part.get_content_disposition()
                filename = part.get_filename()
                if disposition == 'attachment' or filename:
                    attachments.append({'part': idx, 'filename': _decode(filename) or f'attachment-{idx}', 'content_type': part.get_content_type()})
                    continue
                payload = part.get_payload(decode=True) or b''
                charset = part.get_content_charset() or 'utf-8'
                decoded = payload.decode(charset, errors='replace')
                if part.get_content_type() == 'text/plain': text_parts.append(decoded)
                elif part.get_content_type() == 'text/html': html_parts.append(decoded)
        else:
            payload = message.get_payload(decode=True) or b''
            text = payload.decode(message.get_content_charset() or 'utf-8', errors='replace')
            (html_parts if message.get_content_type() == 'text/html' else text_parts).append(text)
        from .views import html_to_text
        body = '\n\n'.join(text_parts).strip() or html_to_text('\n'.join(html_parts))
        return {
            'uid': str(uid), 'from': _decode(message.get('From')), 'to': _decode(message.get('To')),
            'cc': _decode(message.get('Cc')), 'subject': _decode(message.get('Subject')) or '(No subject)',
            'date': _decode(message.get('Date')), 'body': body, 'attachments': attachments,
            'message_id': message.get('Message-ID', ''),
        }
    finally:
        try: client.logout()
        except Exception: pass


def message_action(mailbox, folder, uid, action):
    if not str(uid).isdigit(): raise ValueError('Invalid message identifier.')
    client = connect_imap(MailConfig.from_mailbox(mailbox))
    try:
        status, _ = client.select(folder)
        if status != 'OK': raise ValueError('Folder is unavailable.')
        if action == 'read': client.uid('store', uid, '+FLAGS', '(\\Seen)')
        elif action == 'unread': client.uid('store', uid, '-FLAGS', '(\\Seen)')
        elif action == 'star': client.uid('store', uid, '+FLAGS', '(\\Flagged)')
        elif action == 'unstar': client.uid('store', uid, '-FLAGS', '(\\Flagged)')
        elif action in {'archive', 'trash'}:
            status, folders = client.list()
            kind = 'archive' if action == 'archive' else 'trash'
            entries = [{'name': _folder_name(row), 'kind': folder_kind(_folder_name(row), _folder_special_use(row))} for row in folders or []]
            target = next((item['name'] for item in entries if item['kind'] == kind), None)
            if not target: raise ValueError(f'No {kind} folder exists on this account.')
            client.uid('copy', uid, target)
            client.uid('store', uid, '+FLAGS', '(\\Deleted)')
            client.expunge()
        else: raise ValueError('Unsupported mailbox action.')
    finally:
        try: client.logout()
        except Exception: pass


def fetch_attachment(mailbox, folder, uid, part_index):
    if not str(uid).isdigit(): raise ValueError('Invalid message identifier.')
    client = connect_imap(MailConfig.from_mailbox(mailbox))
    try:
        client.select(folder, readonly=True)
        size_status, size_data = client.uid('fetch', str(uid).encode('ascii'), '(RFC822.SIZE)')
        if size_status != 'OK' or not size_data:
            raise ValueError('Message is unavailable.')
        size_raw = b' '.join(item[0] if isinstance(item, tuple) else item for item in size_data if isinstance(item, (bytes, tuple)))
        size_match = re.search(rb'RFC822\.SIZE\s+(\d+)', size_raw)
        if size_match and int(size_match.group(1)) > MAX_MESSAGE_BYTES:
            raise ValueError('Message exceeds the download limit.')
        raw = _fetch_bytes(client, uid, '(BODY.PEEK[])')
        msg = message_from_bytes(raw)
        parts = list(msg.walk()) if msg.is_multipart() else [msg]
        index = int(part_index)
        if index < 0 or index >= len(parts): raise ValueError('Attachment is unavailable.')
        part = parts[index]
        data = part.get_payload(decode=True) or b''
        if len(data) > MAX_ATTACHMENT_BYTES: raise ValueError('Attachment exceeds the download limit.')
        filename = _decode(part.get_filename()) or f'attachment-{index}'
        return filename.replace('\r', '').replace('\n', ''), part.get_content_type(), data
    finally:
        try: client.logout()
        except Exception: pass


def build_mime_message(mailbox, *, to, cc='', subject='', body='', attachments=(), in_reply_to='', references=''):
    config = MailConfig.from_mailbox(mailbox)
    for header in (to, cc, subject, in_reply_to, references):
        if '\r' in header or '\n' in header or len(header) > 4000:
            raise ValueError('Message headers contain invalid input.')
    recipients = [address for _name, address in getaddresses([to, cc]) if address]
    for address in recipients:
        try: validate_email(address)
        except ValidationError as exc: raise ValueError('Message contains an invalid recipient address.') from exc
    msg = MIMEMessage()
    msg['From'] = config.email_address
    msg['To'] = to
    if cc: msg['Cc'] = cc
    msg['Subject'] = subject
    msg['Date'] = formatdate(localtime=True)
    msg['Message-ID'] = make_msgid()
    if in_reply_to: msg['In-Reply-To'] = in_reply_to
    if references: msg['References'] = references
    msg.set_content(body)
    total = 0
    for item in attachments:
        content = item.read(MAX_ATTACHMENT_BYTES + 1)
        total += len(content)
        if total > MAX_ATTACHMENT_BYTES: raise ValueError('Attachments must total no more than 15 MB.')
        name = (item.name or 'attachment').replace('\r', '').replace('\n', '').replace('/', '_').replace('\\', '_')
        maintype, _, subtype = (getattr(item, 'content_type', 'application/octet-stream') or 'application/octet-stream').partition('/')
        if maintype in {'text', 'image', 'application', 'audio', 'video'} and subtype:
            msg.add_attachment(content, maintype=maintype, subtype=subtype, filename=name)
        else:
            msg.add_attachment(content, maintype='application', subtype='octet-stream', filename=name)
    return msg


def send_message(mailbox, *, to, cc='', subject='', body='', attachments=(), in_reply_to='', references=''):
    config = MailConfig.from_mailbox(mailbox)
    msg = build_mime_message(mailbox, to=to, cc=cc, subject=subject, body=body, attachments=attachments,
                             in_reply_to=in_reply_to, references=references)
    client = connect_smtp(config)
    try:
        recipients = [address for _, address in getaddresses([to, cc]) if address]
        if not recipients: raise ValueError('Enter at least one valid recipient.')
        client.send_message(msg, from_addr=config.email_address, to_addrs=recipients)
    finally:
        try: client.quit()
        except Exception: pass
    return append_sent_copy(mailbox, msg)


def append_sent_copy(mailbox, message):
    """Save a sent copy using the provider's advertised Sent folder when available."""
    client = None
    try:
        client = connect_imap(MailConfig.from_mailbox(mailbox))
        status, rows = client.list()
        if status != 'OK':
            return False
        target = next((
            _folder_name(row) for row in rows or []
            if folder_kind(_folder_name(row), _folder_special_use(row)) == 'sent'
        ), None)
        if not target:
            return False
        import time
        status, _ = client.append(target, '(\\Seen)', imaplib.Time2Internaldate(time.time()), message.as_bytes())
        return status == 'OK'
    except Exception:
        # The SMTP server has already accepted delivery; a Sent-copy failure must not
        # cause a retry that could send a duplicate message.
        return False
    finally:
        if client:
            try: client.logout()
            except Exception: pass


def save_draft(mailbox, *, to='', cc='', subject='', body='', attachments=()):
    config = MailConfig.from_mailbox(mailbox)
    msg = build_mime_message(mailbox, to=to, cc=cc, subject=subject, body=body, attachments=attachments)
    client = connect_imap(config)
    try:
        folders = list_folder_metadata(mailbox)
        target = next((folder['name'] for folder in folders if folder['kind'] == 'drafts'), None)
        if not target: raise ValueError('This mailbox has no Drafts folder.')
        import time
        status, _ = client.append(target, '(\\Draft)', imaplib.Time2Internaldate(time.time()), msg.as_bytes())
        if status != 'OK': raise ValueError('Draft could not be saved.')
    finally:
        try: client.logout()
        except Exception: pass
