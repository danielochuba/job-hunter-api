"""Gmail adapter for the Mailer port (OAuth web flow, send, read thread metadata)."""
import base64
import json
from email.message import EmailMessage
from email.utils import parseaddr

SCOPES = ["https://www.googleapis.com/auth/gmail.send", "https://www.googleapis.com/auth/gmail.readonly"]


def build_message(sender, to, subject, body, attachment=None):
    """Base64url MIME message. attachment: (filename, bytes, mimetype) or None."""
    msg = EmailMessage()
    msg["To"] = to
    msg["From"] = sender
    msg["Subject"] = subject
    msg.set_content(body)
    if attachment:
        name, data, mime = attachment
        maintype, _, subtype = mime.partition("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


class GmailMailer:
    def __init__(self, client_id, client_secret, redirect_uri):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    def configured(self):
        return bool(self.client_id and self.client_secret)

    def _flow(self, state=None):
        from google_auth_oauthlib.flow import Flow
        config = {"web": {"client_id": self.client_id, "client_secret": self.client_secret,
                          "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                          "token_uri": "https://oauth2.googleapis.com/token"}}
        flow = Flow.from_client_config(config, scopes=SCOPES, state=state, autogenerate_code_verifier=False)
        flow.redirect_uri = self.redirect_uri
        return flow

    def auth_url(self, state):
        url, _ = self._flow(state).authorization_url(access_type="offline", prompt="consent",
                                                     include_granted_scopes="true")
        return url

    def exchange_code(self, code, state):
        flow = self._flow(state)
        flow.fetch_token(code=code)
        creds = flow.credentials
        email = self._service(creds).users().getProfile(userId="me").execute()["emailAddress"]
        return json.loads(creds.to_json()), email

    def _creds(self, token, on_token):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        creds = Credentials.from_authorized_user_info(token, SCOPES)
        if not creds.valid and creds.refresh_token:
            creds.refresh(Request())
            on_token(json.loads(creds.to_json()))
        return creds

    @staticmethod
    def _service(creds):
        from googleapiclient.discovery import build
        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    def send(self, token, sender, to, subject, body, attachment, on_token):
        svc = self._service(self._creds(token, on_token))
        raw = build_message(sender, to, subject, body, attachment)
        sent = svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        return sent["id"], sent.get("threadId")

    def thread_messages(self, token, thread_id, on_token):
        svc = self._service(self._creds(token, on_token))
        thread = svc.users().threads().get(userId="me", id=thread_id, format="metadata",
                                           metadataHeaders=["From", "Subject"]).execute()
        out = []
        for m in thread.get("messages", []):
            headers = {h["name"].lower(): h["value"] for h in (m.get("payload") or {}).get("headers", [])}
            out.append({"from": parseaddr(headers.get("from", ""))[1].lower(),
                        "internal_ms": int(m.get("internalDate", 0)), "snippet": m.get("snippet", "")})
        return out
