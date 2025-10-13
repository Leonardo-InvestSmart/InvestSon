import streamlit as st
from Modules.ui import apply_theme, adicionar_logo_sidebar

# Tema + CSS + sidebar aberta (padrão SmartC)
apply_theme()
adicionar_logo_sidebar()

# Imports dos módulos
from Modules.auth import (
    ensure_session_keys,
    login_screen,
    signout_button,
)
from Modules.page_recebiveis import (
    sidebar_recebiveis,
    page_solicitar_nota,
    page_minhas_notas,
    page_cadastro_parceiro,
)
from Modules.page_contas_receber import (
    sidebar_contas_receber,
    page_upload_nota,
    page_notas_pendentes,
)

# Garante chaves de sessão
ensure_session_keys()

# Garante chave menu na sessão
if "menu" not in st.session_state:
    st.session_state.menu = None

# Fluxo principal
if st.session_state.usuario_email is None:
    # Tela de login
    login_screen()
else:
    # Usuário autenticado
    equipe = st.session_state.get("equipe")
    usuario_nome = st.session_state.get("usuario_nome", "")

    # Sidebar por equipe
    if equipe == "Recebiveis":
        sidebar_recebiveis()
        if st.session_state.menu is None:
            st.session_state.menu = "Solicitar Nota"

    elif equipe == "Contas a Receber":
        sidebar_contas_receber()
        if st.session_state.menu is None:
            st.session_state.menu = "Upload de Nota"

    # Botão de sair
    signout_button()

    # Roteamento por equipe/menu
    menu = st.session_state.menu

    if equipe == "Recebiveis":
        if menu == "Solicitar Nota":
            page_solicitar_nota(usuario_nome)
        elif menu == "Minhas Notas":
            page_minhas_notas(usuario_nome)
        elif menu == "Cadastro Parceiro":
            page_cadastro_parceiro()
        else:
            st.info("Selecione uma opção no menu lateral.")

    elif equipe == "Contas a Receber":
        if menu == "Upload de Nota":
            page_upload_nota()
        elif menu == "Notas Pendentes":
            page_notas_pendentes()
        else:
            st.info("Selecione uma opção no menu lateral.")

    else:
        st.warning("Equipe não reconhecida. Verifique suas permissões de acesso.")
