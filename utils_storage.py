from typing import Tuple
from mimetypes import guess_type
from config import supabase_service
import unicodedata, re
from typing import Tuple
from mimetypes import guess_type

def sanitize_filename(text: str) -> str:
    """Remove acentos e caracteres inválidos para nome de arquivo."""
    if text is None:
        return "sem_nome"
    t = unicodedata.normalize("NFKD", str(text))
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^A-Za-z0-9]+", "_", t).strip("_")
    return t or "sem_nome"

def make_unique_object_path(bucket: str, folder: str, base_stem: str, ext: str) -> str:
    """
    Gera um caminho único dentro de 'folder' no bucket:
    - base_stem + ext; se existir, base_stem_1 + ext; depois _2...
    Retorna "folder/arquivo.ext"
    """
    if supabase_service is None:
        raise RuntimeError("Configure SUPABASE_SERVICE_ROLE_KEY em .streamlit/secrets.toml")

    try:
        entries = supabase_service.storage.from_(bucket).list(folder) or []
    except Exception:
        entries = []

    # objetos vêm como dict com chave 'name' (storage3)
    existing = { (e.get("name") if isinstance(e, dict) else getattr(e, "name", "")) for e in entries }

    name = f"{base_stem}{ext}"
    if name in existing:
        i = 1
        while f"{base_stem}_{i}{ext}" in existing:
            i += 1
        name = f"{base_stem}_{i}{ext}"

    return f"{folder}/{name}"


def _ensure_service():
    if supabase_service is None:
        raise RuntimeError("Configure SUPABASE_SERVICE_ROLE_KEY em .streamlit/secrets.toml para usar Storage privado.")

def upload_streamlit_file(bucket: str, uploaded_file, destination_path: str, overwrite: bool = True) -> str:
    """
    Sobe arquivo para Supabase Storage. Alguns SDKs antigos quebram se 'upsert' for bool.
    Por isso, convertemos para strings nos headers.
    """
    if supabase_service is None:
        raise RuntimeError("Configure SUPABASE_SERVICE_ROLE_KEY em .streamlit/secrets.toml")

    # ler bytes do UploadedFile
    uploaded_file.seek(0)
    data = uploaded_file.read()

    # garantir string
    content_type = uploaded_file.type or guess_type(destination_path)[0] or "application/octet-stream"
    content_type = str(content_type)

    # 1ª tentativa: API “nova” (file_options com chaves canônicas)
    try:
        file_options = {
            "contentType": content_type,           # string
            "cacheControl": "3600",                # string
            "upsert": "true" if overwrite else "false",  # string para evitar bool nos headers
        }
        supabase_service.storage.from_(bucket).upload(destination_path, data, file_options=file_options)
    except TypeError:
        # Fallback: alguns builds esperam diretamente nomes de header
        file_options = {
            "content-type": content_type,
            "cache-control": "3600",
            "x-upsert": "true" if overwrite else "false",
        }
        supabase_service.storage.from_(bucket).upload(destination_path, data, file_options=file_options)

    return destination_path

def download_bytes(bucket: str, source_path: str) -> Tuple[str, str, bytes]:
    """
    Baixa bytes a partir do Supabase Storage para usar no st.download_button.
    """
    _ensure_service()
    data = supabase_service.storage.from_(bucket).download(source_path)  # bytes
    file_name = source_path.split("/")[-1]
    mime = guess_type(source_path)[0] or "application/octet-stream"
    return file_name, mime, data

def signed_url(bucket: str, source_path: str, expires_seconds: int = 3600) -> str:
    """
    (Opcional) Gera URL assinada caso queira link externo em vez de bytes.
    """
    _ensure_service()
    res = supabase_service.storage.from_(bucket).create_signed_url(source_path, expires_seconds)
    # SDKs podem retornar {"signedURL": "..."} ou {"signed_url": "..."} dependendo da versão
    return res.get("signedURL") or res.get("signed_url")
