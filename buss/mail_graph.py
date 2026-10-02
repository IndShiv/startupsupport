"""Django email backend that sends through Microsoft Graph (client-credentials flow).

Needs an Entra ID app registration with the *Mail.Send* application permission.
Restrict it to the BUSS mailbox with an Exchange application access policy, so the
app cannot send as anyone else. Settings: GRAPH_TENANT_ID, GRAPH_CLIENT_ID,
GRAPH_CLIENT_SECRET and GRAPH_SENDER (the mailbox to send from).
"""

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from email.utils import parseaddr

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
SEND_URL = "https://graph.microsoft.com/v1.0/users/{sender}/sendMail"

_token_lock = threading.Lock()
_token_cache = {"value": None, "expires": 0.0}


class GraphError(Exception):
    pass


def _post(url, data, headers, timeout):
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            return response.status, body
    except urllib.error.HTTPError as exc:
        raise GraphError(f"Graph returned HTTP {exc.code}: {exc.read()[:500].decode(errors='replace')}") from exc


def get_token(timeout=20):
    with _token_lock:
        if _token_cache["value"] and _token_cache["expires"] > time.time() + 60:
            return _token_cache["value"]
        data = urllib.parse.urlencode({
            "client_id": settings.GRAPH_CLIENT_ID,
            "client_secret": settings.GRAPH_CLIENT_SECRET,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        }).encode()
        _status, body = _post(TOKEN_URL.format(tenant=settings.GRAPH_TENANT_ID), data,
                              {"Content-Type": "application/x-www-form-urlencoded"}, timeout)
        payload = json.loads(body)
        _token_cache["value"] = payload["access_token"]
        _token_cache["expires"] = time.time() + int(payload.get("expires_in", 3600))
        return _token_cache["value"]


def _recipients(addresses):
    result = []
    for address in addresses:
        name, email = parseaddr(address)
        entry = {"address": email}
        if name:
            entry["name"] = name
        result.append({"emailAddress": entry})
    return result


def message_to_graph(message):
    """Convert a Django EmailMessage into a Graph sendMail payload."""
    content, content_type = message.body, "Text"
    for alternative, mimetype in getattr(message, "alternatives", []):
        if mimetype == "text/html":
            content, content_type = alternative, "HTML"
    payload = {
        "subject": message.subject,
        "body": {"contentType": content_type, "content": content},
        "toRecipients": _recipients(message.to),
    }
    if message.cc:
        payload["ccRecipients"] = _recipients(message.cc)
    if message.bcc:
        payload["bccRecipients"] = _recipients(message.bcc)
    if message.reply_to:
        payload["replyTo"] = _recipients(message.reply_to)
    return {"message": payload, "saveToSentItems": True}


class GraphEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        sent = 0
        for message in email_messages:
            try:
                token = get_token(settings.EMAIL_TIMEOUT)
                sender = urllib.parse.quote(settings.GRAPH_SENDER)
                _post(
                    SEND_URL.format(sender=sender),
                    json.dumps(message_to_graph(message)).encode(),
                    {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    settings.EMAIL_TIMEOUT,
                )
                sent += 1
            except Exception:
                if not self.fail_silently:
                    raise
        return sent
