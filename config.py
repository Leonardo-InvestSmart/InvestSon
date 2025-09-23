import streamlit as st
from supabase import create_client
from st_supabase_connection import SupabaseConnection  # <-- NOVO

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]  # anon
SERVICE_KEY  = st.secrets.get("SUPABASE_SERVICE_ROLE_KEY")  # para Storage privado

# clients existentes (DB):
supabase_anon    = create_client(SUPABASE_URL, SUPABASE_KEY)
supabase_service = create_client(SUPABASE_URL, SERVICE_KEY) if SERVICE_KEY else None

# conexão do CONECTOR (Storage + DB + Auth) — passamos a service key p/ acesso ao bucket privado
st_supabase_client = st.connection(
    name="supabase_connection",
    type=SupabaseConnection,
    url=SUPABASE_URL,
    key=SERVICE_KEY or SUPABASE_KEY,
    ttl=None,
)

TENANT_ID     = st.secrets.get("AZURE_TENANT_ID")
CLIENT_ID     = st.secrets.get("AZURE_CLIENT_ID")
CLIENT_SECRET = st.secrets.get("AZURE_CLIENT_SECRET")
EMAIL_USER    = st.secrets.get("EMAIL_USER")
USUARIOS      = st.secrets.get("usuarios", {})