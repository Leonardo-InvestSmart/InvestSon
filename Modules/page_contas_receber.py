import streamlit as st
from datetime import datetime
import re
import time
import tempfile
import os
from db import carregar_notas, atualizar_nota
from utils_storage import upload_streamlit_file, make_unique_object_path, sanitize_filename
from .ui import inject_base_css
from .validador_nota import extrair_dados_xml
from .api_email import Mail
from streamlit_option_menu import option_menu

# ==============================
# Funções auxiliares
# ==============================
def norm_str(v):
    return str(v).strip().upper() if v else ""

def norm_float(v):
    if v in [None, ""]:
        return None
    return float(v)

def norm_cnpj(v):
    """Remove tudo que não for número e retorna só os dígitos do CNPJ"""
    if not v:
        return ""
    return re.sub(r"\D", "", str(v))

# ==============================
# Sidebar
# ==============================
def sidebar_contas_receber():
    st.sidebar.markdown('<div class="menu-nav">Menu de navegação</div>', unsafe_allow_html=True)

    with st.sidebar:
        pages = ["Upload de Nota", "Notas Pendentes"]
        icon_map = {"Upload de Nota": "cloud-upload", "Notas Pendentes": "hourglass-split"}
        icons = [icon_map.get(p, "circle") for p in pages]

        default_index = pages.index(st.session_state.get("menu", "Upload de Nota")) \
                        if st.session_state.get("menu") in pages else 0

        escolha = option_menu(
            menu_title=None,
            options=pages,
            icons=icons,
            default_index=default_index,
            styles={
                "container": {"padding": "0!important", "background-color": "#9966ff"},
                "icon": {"font-size": "16px"},
                "nav-link": {"font-size": "14px", "text-align": "left", "margin": "0px", "padding": "8px 16px"},
                "nav-link-selected": {"background-color": "#121212", "font-weight": "bold", "font-size": "14px"},
            },
        )

        if st.session_state.get("menu") != escolha:
            st.session_state.menu = escolha
            st.rerun()

# ==============================
# Página de upload de nota
# ==============================
def page_upload_nota():
    """Tela para fazer upload do PDF/XML de solicitações pendentes com validação automática."""
    inject_base_css()
    st.header("Upload de Nota Fiscal")

    historico = carregar_notas()
    if "pdf_path" not in historico.columns:
        st.info("Não existem notas cadastradas ainda.")
        return

    pendentes = historico[historico["pdf_path"].isna()]
    if pendentes.empty:
        st.info("Nenhuma solicitação pendente.")
        return

    nota_id = st.selectbox(
        "Selecione a solicitação:",
        pendentes["id"],
        format_func=lambda x: f"{pendentes.loc[pendentes['id']==x,'razao_parceiro'].values[0]} - "
                              f"{pendentes.loc[pendentes['id']==x,'valor'].values[0]}"
    )

    pdf_file = st.file_uploader("Upload PDF", type="pdf")
    xml_file = st.file_uploader("Upload XML", type="xml")

    if st.button("Enviar Nota"):
        subpasta = datetime.now().strftime("%Y/%m")
        parceiro_raw = pendentes.loc[pendentes["id"] == nota_id, "razao_parceiro"].values[0]
        parceiro = sanitize_filename(str(parceiro_raw))
        data_str = datetime.now().strftime("%Y_%m_%d")
        stem = f"{parceiro}_{data_str}"

        pdf_name = xml_name = None
        temp_pdf_path = temp_xml_path = None

        # Upload do PDF
        if pdf_file:
            destino_pdf = make_unique_object_path("notas_fiscais", subpasta, stem, ".pdf")
            pdf_name = upload_streamlit_file("notas_fiscais", pdf_file, destino_pdf, overwrite=False)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_pdf:
                tmp_pdf.write(pdf_file.read())
                temp_pdf_path = tmp_pdf.name

        # Upload + validação do XML
        if xml_file:
            xml_bytes = xml_file.read()
            xml_file.seek(0)
            destino_xml = make_unique_object_path("notas_fiscais", subpasta, stem, ".xml")
            xml_name = upload_streamlit_file("notas_fiscais", xml_file, destino_xml, overwrite=False)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".xml") as tmp_xml:
                tmp_xml.write(xml_bytes)
                temp_xml_path = tmp_xml.name

            dados_xml = extrair_dados_xml(xml_bytes)
            if dados_xml:
                esperado = pendentes.loc[pendentes["id"] == nota_id].iloc[0]
                erros = []

                # Comparações
                if dados_xml["valor"] != norm_float(esperado["valor"]):
                    erros.append(f"Valor divergente: esperado {esperado['valor']} / XML {dados_xml['valor']}")
                if norm_cnpj(dados_xml["cnpj_emissor"]) != norm_cnpj(esperado["cnpj_emissor"]):
                    erros.append(f"CNPJ emissor divergente: esperado {esperado['cnpj_emissor']} / XML {dados_xml['cnpj_emissor']}")
                if dados_xml["razao_emissor"] != norm_str(esperado["razao_emissor"]):
                    erros.append(f"Razão emissor divergente: esperado {esperado['razao_emissor']} / XML {dados_xml['razao_emissor']}")
                if norm_cnpj(dados_xml["cnpj_parceiro"]) != norm_cnpj(esperado["cnpj_parceiro"]):
                    erros.append(f"CNPJ parceiro divergente: esperado {esperado['cnpj_parceiro']} / XML {dados_xml['cnpj_parceiro']}")
                if dados_xml["razao_parceiro"] != norm_str(esperado["razao_parceiro"]):
                    erros.append(f"Razão parceiro divergente: esperado {esperado['razao_parceiro']} / XML {dados_xml['razao_parceiro']}")

                if erros:
                    st.error("❌ Nota rejeitada! Divergências encontradas:")
                    for e in erros:
                        st.write(f"- {e}")
                    # remove temporários
                    if temp_pdf_path and os.path.exists(temp_pdf_path):
                        os.remove(temp_pdf_path)
                    if temp_xml_path and os.path.exists(temp_xml_path):
                        os.remove(temp_xml_path)
                    return

        # Atualiza no banco
        atualizar_nota(nota_id, {
            "pdf_path":  pdf_name,
            "xml_path":  xml_name,
            "data_upload": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status":    "Emitida"
        })

        # ==============================
        # Envio automático de e-mail
        # ==============================
        esperado = pendentes.loc[pendentes["id"] == nota_id].iloc[0]
        envio_tipo = str(esperado.get("envio", "")).strip().lower()

        if envio_tipo == "email":
            emails = str(esperado.get("email_para", "")).split(";")
            corpo = f"""
            Prezados,<br><br>
            Segue a nota fiscal solicitada no valor de R$ {esperado['valor']:.2f}.<br><br>
            Qualquer dúvida nosso time está à disposição.<br><br>
            Att,<br>Time de Comissões
            """

            anexos = []
            if temp_pdf_path: anexos.append(temp_pdf_path)
            if temp_xml_path: anexos.append(temp_xml_path)

            for dest in emails:
                if dest.strip():
                    try:
                        Mail().send(
                            email=dest.strip(),
                            subject="Nota Fiscal Emitida",
                            html=corpo,
                            attachments=anexos
                        )
                    except Exception as e:
                        st.error(f"Erro ao enviar email para {dest}: {e}")

            atualizar_nota(nota_id, {"status": "Enviada"})

        # Mensagem de sucesso
        mensagem = st.empty()
        mensagem.success("✅ Nota aceita! Todos os dados conferem.")
        time.sleep(3)
        st.info("Nota processada com sucesso. Você pode selecionar outra solicitação.")

        # Remove arquivos temporários
        if temp_pdf_path and os.path.exists(temp_pdf_path):
            os.remove(temp_pdf_path)
        if temp_xml_path and os.path.exists(temp_xml_path):
            os.remove(temp_xml_path)

# ==============================
# Página de notas pendentes
# ==============================
def page_notas_pendentes():
    """Lista solicitações do ponto de vista do Contas a Receber."""
    inject_base_css()
    st.header("Notas Pendentes e Emitidas")

    historico = carregar_notas()
    if "pdf_path" not in historico.columns:
        st.info("Nenhuma nota cadastrada ainda.")
        return

    # ----------------------------
    # Notas Pendentes
    # ----------------------------
    pendentes = historico[historico["pdf_path"].isna()].copy()
    if not pendentes.empty:
        st.subheader("Notas Pendentes")
        colunas_exibir = [
            "razao_emissor",
            "cnpj_emissor",
            "razao_parceiro",
            "cnpj_parceiro",
            "valor",
            "data_solicitacao",
            "status"
        ]
        colunas_exibir = [c for c in colunas_exibir if c in pendentes.columns]
        st.dataframe(pendentes[colunas_exibir], width="stretch")
    else:
        st.subheader("Notas Pendentes")
        st.success("Não há pendências de upload no momento.")

    # ----------------------------
    # Notas Emitidas
    # ----------------------------
    emitidas = historico[historico["pdf_path"].notna()].copy()
    if not emitidas.empty:
        st.subheader("Notas Emitidas")
        colunas_exibir = [
            "razao_emissor",
            "cnpj_emissor",
            "razao_parceiro",
            "cnpj_parceiro",
            "valor",
            "data_upload"
        ]
        colunas_exibir = [c for c in colunas_exibir if c in emitidas.columns]
        st.dataframe(emitidas[colunas_exibir], width="stretch")
    else:
        st.subheader("Notas Emitidas")
        st.info("Nenhuma nota foi inserida ainda.")
