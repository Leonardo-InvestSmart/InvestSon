import base64
import mimetypes
import os
import msal
import requests
import streamlit as st

## By: Juliana Moura ##
AZURE_TENANT_ID = st.secrets["AZURE_TENANT_ID"]
AZURE_CLIENT_ID = st.secrets["AZURE_CLIENT_ID"]
AZURE_CLIENT_SECRET = st.secrets["AZURE_CLIENT_SECRET"]
EMAIL_USER = st.secrets["EMAIL_USER"]

class Mail:
    def __init__(
        self,
        client_id: str = AZURE_CLIENT_ID,
        tenant_id: str = AZURE_TENANT_ID,
        client_secret: str = AZURE_CLIENT_SECRET,
        sender_email: str = EMAIL_USER,
    ):
        self.app = msal.ConfidentialClientApplication(
            client_id,
            authority=f"https://login.microsoftonline.com/{tenant_id}",
            client_credential=client_secret,
        )
        self.token = self.__get_token()
        self.sender_email = sender_email

    def __get_token(self):
        result = self.app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )
        if "access_token" in result:
            return result["access_token"]
        raise Exception("Erro na autenticação:", result)

    def send(self, email, subject, html, cc=None, attachment=None, filename=None, attachments=None):
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

        message = {
            "message": {
                "subject": subject,
                "body": {"contentType": "HTML", "content": html},
                "toRecipients": [{"emailAddress": {"address": email}}],
            },
            "saveToSentItems": "true",
        }

        if cc:
            if isinstance(cc, str):
                cc = [cc]
            message["message"]["ccRecipients"] = [
                {"emailAddress": {"address": address}} for address in cc
            ]

        # normaliza para lista de anexos
        files = []
        if attachments and isinstance(attachments, (list, tuple)):
            files = list(attachments)
        elif attachment:
            files = [attachment]

        if files:
            att_payload = []
            for path in files:
                with open(path, "rb") as f:
                    file_bytes = f.read()
                fn = filename or os.path.basename(path)
                mime_type, _ = mimetypes.guess_type(fn)
                if not mime_type:
                    mime_type = "application/octet-stream"
                b64_content = base64.b64encode(file_bytes).decode()
                att_payload.append({
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": fn,
                    "contentType": mime_type,
                    "contentBytes": b64_content,
                })
            message["message"]["attachments"] = att_payload

        response = requests.post(
            f"https://graph.microsoft.com/v1.0/users/{self.sender_email}/sendMail",
            headers=headers,
            json=message,
        )
        response.raise_for_status()
        return True
