import streamlit as st
from config import USUARIOS

def ensure_session_keys():
    if "usuario_email" not in st.session_state:
        st.session_state.usuario_email = None
        st.session_state.equipe = None
        st.session_state.usuario_nome = None
    if "menu" not in st.session_state:
        st.session_state.menu = None

def login_screen():
    st.title("Sistema de Organização de Notas Fiscais")
    usuario_input = st.text_input("Usuário (e-mail)")
    senha_input = st.text_input("Senha", type="password")
    if st.button("Login"):
        if usuario_input in USUARIOS and senha_input == USUARIOS[usuario_input]["senha"]:
            st.session_state.usuario_email = usuario_input
            st.session_state.equipe = USUARIOS[usuario_input]["equipe"]
            st.session_state.usuario_nome = USUARIOS[usuario_input]["usuario"]
            st.success(f"Bem-vindo(a) {st.session_state.usuario_nome}! "
                       f"Equipe: {st.session_state.equipe}")
            st.rerun()
        else:
            st.error("Usuário ou senha incorretos")

def signout_button():
    if st.sidebar.button("Sair"):
        st.session_state.usuario_email = None
        st.session_state.equipe = None
        st.session_state.usuario_nome = None
        st.session_state.menu = None
        st.rerun()
