import streamlit as st
from datetime import datetime
import re
import time
import tempfile
import pandas as pd
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

def _fmt_moeda_ptbr(s):
    # aceita str/float; retorna "R$ 264.821,33"
    v = pd.to_numeric(s, errors="coerce")
    return v.map(lambda x: "" if pd.isna(x) else "R$ " + f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

def _fmt_data_ptbr(s):
    # aceita ISO, datetime ou str; retorna "dd/mm/aaaa às HH:MM:SS"
    dt = pd.to_datetime(s, errors="coerce")
    return dt.dt.strftime("%d/%m/%Y às %H:%M:%S").fillna("")

def _normalize_envio(value: str) -> str:
    """
    Normaliza o texto do campo 'envio' para facilitar a comparação.
    Ex.: 'E-mail', 'email', 'EMAIL ', 'e mail' -> 'email'
    """
    s = (value or "").strip().lower()
    s = re.sub(r"[^a-z]", "", s)  # remove espaços, hífens, etc.
    return s  # 'email', 'portal', 'naonecessario', ...

def _read_uploadedfile_bytes(uploaded_file) -> bytes:
    """
    Garante a leitura dos bytes completos de um st.file_uploader UploadedFile
    mesmo após outras leituras.
    """
    if uploaded_file is None:
        return b""
    try:
        uploaded_file.seek(0)
    except Exception:
        pass
    return uploaded_file.read() or b""

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

    pendentes = historico[
        historico.get("status", "").fillna("") == "Pendente"
    ].copy()
    if pendentes.empty:
        st.info("Nenhuma solicitação pendente.")
        return

    nota_id = st.selectbox(
        "Selecione a solicitação:",
        pendentes["id"],
        format_func=lambda x: f"{pendentes.loc[pendentes['id']==x,'razao_parceiro'].values[0]} - "
                            f"{pendentes.loc[pendentes['id']==x,'valor'].values[0]}"
    )

    # NOVO: mostra observações da solicitação selecionada, se houver
    try:
        obs_sel = pendentes.loc[pendentes["id"] == nota_id, "observacoes"].astype(str).values[0]
        if obs_sel and obs_sel.strip() and obs_sel.strip().lower() not in ("nan", "none"):
            st.info(f"**Observações da solicitação:** {obs_sel.strip()}")
    except Exception:
        pass

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
            # 1) Envia ao Storage
            pdf_name = upload_streamlit_file("notas_fiscais", pdf_file, destino_pdf, overwrite=False)
            # 2) Gera cópia temporária com bytes válidos para anexar no e-mail
            pdf_bytes = _read_uploadedfile_bytes(pdf_file)  # <-- garante reposicionar e ler tudo
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_pdf:
                tmp_pdf.write(pdf_bytes)
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

        # --- 1) Carregar 'envio' e 'email_para' preferencialmente do de_para_empresas ---
        envio_tipo = str(esperado.get("envio", "")).strip()  # pode vir vazio na nota
        emails_raw = (esperado.get("email_para") or "").strip()

        try:
            from .page_recebiveis import DF_FANTASIA  # cache global carregado no módulo
            chave_cnpj = str(esperado.get("cnpj_parceiro") or "").strip()
            df_cand = DF_FANTASIA[
                DF_FANTASIA.get("id_parceiro", "").astype(str).str.strip() == chave_cnpj
            ]
            if df_cand.empty:
                # fallback por nome parceiro
                nomep = str(esperado.get("razao_parceiro") or "").strip().lower()
                if "nome_parceiro" in DF_FANTASIA.columns:
                    df_cand = DF_FANTASIA[DF_FANTASIA["nome_parceiro"].str.lower().str.strip() == nomep]

            if not df_cand.empty:
                # Se 'envio' da base de-para estiver preenchido, priorize-o
                envio_tipo = df_cand.iloc[0].get("envio", envio_tipo)
                # Se e-mails da nota estiverem vazios, pegue do de-para
                if not emails_raw:
                    emails_raw = str(df_cand.iloc[0].get("email_para", "")).strip()
        except Exception as _e:
            # não bloqueia; segue com o que já temos
            pass

        envio_norm = _normalize_envio(envio_tipo)

        # --- 2) Só dispara e-mail se a configuração do parceiro indicar 'email' ---
        if envio_norm == "email":
            emails = [e.strip() for e in (emails_raw or "").split(";") if e.strip()]
            if not emails:
                st.warning("Configuração 'envio = email', mas nenhum destinatário encontrado (email_para vazio).")
            else:
                # Corpo do e-mail
                try:
                    valor_fmt = float(esperado["valor"])
                    valor_fmt = f"{valor_fmt:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                except Exception:
                    valor_fmt = str(esperado.get("valor", ""))
                # --- Corpo do e-mail (texto solicitado) ---
                corpo = (
                    "Prezados, boa tarde.<br><br>"
                    "Segue, em anexo, a nota fiscal.<br><br>"
                    "Gentileza confirmar o recebimento.<br><br>"
                    "Atenciosamente,<br>"
                    "Time de Comissões"
                )

                # --- Descobrir 'fantasia' a partir do de-para (prioriza CNPJ; fallback por nome do parceiro) ---
                fantasia_txt = None
                try:
                    from .page_recebiveis import DF_FANTASIA  # base de-para já carregada e normalizada
                    chave_cnpj = str(esperado.get("cnpj_parceiro") or "").strip()

                    # 1) Match por CNPJ do parceiro
                    df_cand = DF_FANTASIA[
                        DF_FANTASIA.get("id_parceiro", "").astype(str).str.strip() == chave_cnpj
                    ]

                    # 2) Fallback por nome do parceiro (razao_parceiro)
                    if df_cand.empty and "nome_parceiro" in DF_FANTASIA.columns:
                        nomep = str(esperado.get("razao_parceiro") or "").strip().lower()
                        df_cand = DF_FANTASIA[
                            DF_FANTASIA["nome_parceiro"].str.lower().str.strip() == nomep
                        ]

                    if not df_cand.empty and "fantasia" in df_cand.columns:
                        fantasia_txt = str(df_cand.iloc[0].get("fantasia") or "").strip()
                except Exception:
                    pass

                # 3) Último fallback: usa razao_parceiro se não achar no de-para
                if not fantasia_txt:
                    fantasia_txt = str(esperado.get("razao_parceiro") or "").strip()

                # Normaliza removendo parenteses e conteúdo interno
                fantasia_limpa = re.sub(r"\s*\(.*?\)\s*", "", fantasia_txt).strip()

                # --- Nome do anexo: NF_{fantasia}_{data_upload}.pdf ---
                data_upload_fmt = datetime.now().strftime("%d%m%Y")
                pdf_filename_final = f"NF_{fantasia_limpa}_{data_upload_fmt}.pdf"

                # --- Apenas o PDF será anexado e com cópia para o Jedson ---
                erros_envio = []
                for dest in emails:
                    try:
                        Mail().send(
                            email=dest,
                            subject=f"Nota Fiscal - BeSmart - {fantasia_limpa}",
                            html=corpo,
                            cc=["jedson.silva@investsmart.com.br"],
                            attachment=temp_pdf_path,          # só o PDF
                            filename=pdf_filename_final        # força o nome correto do arquivo
                        )
                        st.info(f"E-mail enviado para: {dest}")
                    except Exception as e:
                        erros_envio.append((dest, str(e)))
                        st.error(f"Erro ao enviar email para {dest}: {e}")


                # Atualiza status se ao menos 1 e-mail foi enviado com sucesso
                if len(emails) > len(erros_envio):
                    atualizar_nota(nota_id, {"status": "Enviada"})
                else:
                    st.warning("Nenhum e-mail foi enviado com sucesso — status mantido em 'Emitida'.")

        else:
            # envios configurados como 'portal' ou 'nao necessario' não disparam e-mail
            if envio_norm not in ("", "email"):
                st.info(f"Envio configurado como '{envio_tipo}'. Nenhum e-mail será disparado.")

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
    # Filtra pendentes SEM upload e NÃO canceladas
    pendentes = historico[
        (historico["pdf_path"].isna()) &
        (historico.get("status", "").fillna("") != "Cancelada")
    ].copy()

    st.subheader("Notas Pendentes")
    if not pendentes.empty:
        # Seleção e formatação (inclui 'observacoes')
        cols_pend = [
            "razao_emissor","cnpj_emissor","razao_parceiro","cnpj_parceiro",
            "valor","data_solicitacao","observacoes"
        ]
        cols_pend = [c for c in cols_pend if c in pendentes.columns]
        dfp = pendentes[cols_pend].copy()

        # Formatações
        if "valor" in dfp:              dfp["valor"] = _fmt_moeda_ptbr(dfp["valor"])
        if "data_solicitacao" in dfp:   dfp["data_solicitacao"] = _fmt_data_ptbr(dfp["data_solicitacao"])

        # Cabeçalhos
        rename_pend = {
            "razao_emissor":    "Razão Emissor",
            "cnpj_emissor":     "CNPJ Emissor",
            "razao_parceiro":   "Razão Parceiro",
            "cnpj_parceiro":    "CNPJ Parceiro",
            "valor":            "Valor",
            "data_solicitacao": "Data Solicitação",
            "observacoes":      "Observações",
        }
        dfp = dfp.rename(columns={k: v for k, v in rename_pend.items() if k in dfp.columns})

        st.dataframe(dfp, use_container_width=True, hide_index=True)
    else:
        st.success("Não há pendências de upload no momento.")

    # ----------------------------
    # Notas Emitidas
    # ----------------------------
    emitidas = historico[historico["pdf_path"].notna()].copy()
    st.subheader("Notas Emitidas")
    if not emitidas.empty:
        cols_em = ["razao_emissor","cnpj_emissor","razao_parceiro","cnpj_parceiro","valor","data_upload"]
        cols_em = [c for c in cols_em if c in emitidas.columns]
        dfe = emitidas[cols_em].copy()

        # Formatações
        if "valor" in dfe:         dfe["valor"] = _fmt_moeda_ptbr(dfe["valor"])
        if "data_upload" in dfe:   dfe["data_upload"] = _fmt_data_ptbr(dfe["data_upload"])

        # Cabeçalhos
        rename_em = {
            "razao_emissor":  "Razão Emissor",
            "cnpj_emissor":   "CNPJ Emissor",
            "razao_parceiro": "Razão Parceiro",
            "cnpj_parceiro":  "CNPJ Parceiro",
            "valor":          "Valor",
            "data_upload":    "Data Upload",
        }
        dfe = dfe.rename(columns={k:v for k,v in rename_em.items() if k in dfe.columns})

        st.dataframe(dfe, use_container_width=True, hide_index=True)
    else:
        st.info("Nenhuma nota foi inserida ainda.")

