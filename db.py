import pandas as pd
from postgrest import APIError
from config import supabase_anon, supabase_service
import streamlit as st
import os

TABLE = "notas_fiscais"
TABLE_EMPRESAS = "de_para_empresas"

def carregar_notas() -> pd.DataFrame:
    resp = supabase_anon.table(TABLE).select("*").execute()
    return pd.DataFrame(resp.data or [])

def _assert_service():
    if supabase_service is None:
        # Mensagem clara no front e interrupção segura
        st.error("Configuração ausente: defina SUPABASE_SERVICE_ROLE_KEY em .streamlit/secrets.toml para permitir gravações.")
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY ausente")

def salvar_nota(nota: dict) -> None:
    _assert_service()
    supabase_service.table(TABLE).insert(nota).execute()

def atualizar_nota(id_: int, dados: dict) -> None:
    _assert_service()
    supabase_service.table(TABLE).update(dados).eq("id", id_).execute()

def carregar_empresas(use_service_fallback: bool = True) -> pd.DataFrame:
    """
    Lê public.de_para_empresas com anon; se vier vazio e houver service key,
    tenta novamente com supabase_service (bypass de RLS).
    """
    try:
        resp = supabase_anon.table(TABLE_EMPRESAS).select("*", count="exact").execute()
        df = pd.DataFrame(resp.data or [])
        if df.empty and use_service_fallback and supabase_service is not None:
            resp2 = supabase_service.table(TABLE_EMPRESAS).select("*", count="exact").execute()
            df = pd.DataFrame(resp2.data or [])
        return df
    except Exception as e:
        st.error(f"Erro ao carregar 'de_para_empresas': {e}")
        return pd.DataFrame()