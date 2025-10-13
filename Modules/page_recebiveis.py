import streamlit as st
import pandas as pd
from datetime import date, datetime
import time
import calendar
import locale
from db import (
    carregar_notas, salvar_nota, atualizar_nota,
    carregar_empresas, salvar_empresa, atualizar_empresa
)
from .ui import inject_base_css
from utils_storage import download_bytes, signed_url
from .api_email import Mail
from streamlit_option_menu import option_menu

# Carrega o de-para do nome fantasia
DF_FANTASIA = carregar_empresas()

# Padroniza nomes de colunas para string minúscula
DF_FANTASIA.columns = [str(c).lower().strip() for c in DF_FANTASIA.columns]

colunas_necessarias = [
    "emissao_necessaria", "fantasia", "nome_empresa", "id_empresa",
    "nome_parceiro", "id_parceiro", "recebimento", "envio", "email_para"
]

for col in colunas_necessarias:
    if col not in DF_FANTASIA.columns:
        DF_FANTASIA[col] = ""

# Converte todas as colunas necessárias para string e preenche NaN
for col in colunas_necessarias:
    DF_FANTASIA[col] = DF_FANTASIA[col].fillna("").astype(str)

def sidebar_recebiveis():
    st.sidebar.markdown('<div class="menu-nav">Menu de navegação</div>', unsafe_allow_html=True)

    with st.sidebar:
        pages = ["Solicitar Nota", "Minhas Notas", "Cadastro Parceiro"]
        icon_map = {
            "Solicitar Nota": "plus-circle",
            "Minhas Notas": "file-text",
            "Cadastro Parceiro": "person-plus"
        }
        icons = [icon_map.get(p, "circle") for p in pages]

        default_index = pages.index(st.session_state.get("menu", "Solicitar Nota")) \
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


@st.cache_data(ttl=600, show_spinner=False)
def signed_download_url_cached(path: str) -> str:
    if not path:
        return ""
    try:
        res = signed_url("notas_fiscais", path)
        if not res:
            return ""
        filename = path.split("/")[-1]
        link = f"{res}&download={filename}" if "?" in res else f"{res}?download={filename}"
        if link.startswith("/"):
            link = f"https://{st.secrets['supabase']['url'].replace('https://','')}{link}"
        return link
    except Exception:
        return ""

def page_solicitar_nota(usuario_nome: str):
    inject_base_css()
    st.header("Solicitar Emissão de Nota Fiscal")

    # Filtra apenas empresas com emissao_necessaria == 'sim'
    if "emissao_necessaria" in DF_FANTASIA.columns:
        empresas_validas = DF_FANTASIA[
        DF_FANTASIA["emissao_necessaria"].str.strip().str.lower() == "sim"
    ]
    else:
        empresas_validas = pd.DataFrame()

    if empresas_validas.empty:
        st.warning("Nenhuma empresa configurada para emissão de nota.")
        return

    fantasia = st.selectbox("Selecione a Empresa", empresas_validas["fantasia"])
    valor = st.number_input("Valor da Nota", min_value=0.0, format="%.2f")

    # --- NOVO: Mês de competência (mês/ano) ---
    hoje = date.today()
    meses = list(range(1, 13))
    anos  = list(range(2022, hoje.year + 4))

    col_m, col_a = st.columns(2)
    # tenta ativar locale PT-BR; se não existir no SO, seguimos com o mapa
    for loc in ("pt_BR.utf8", "pt_BR.UTF-8", "pt_BR", "Portuguese_Brazil.1252"):
        try:
            locale.setlocale(locale.LC_TIME, loc)
            break
        except Exception:
            pass

    # nomes PT-BR garantidos (1..12); usamos capitalização igual ao SmartC
    MESES_PT = [
        None,
        "Janeiro","Fevereiro","Março","Abril","Maio","Junho",
        "Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"
    ]

    with col_m:
        mes_comp = st.selectbox(
            "Mês de Competência",
            meses,
            index=hoje.month - 1,
            format_func=lambda m: f"{m:02d} - {MESES_PT[m]}"
        )
    with col_a:
        ano_comp = st.selectbox("Ano de Competência", anos, index=anos.index(hoje.year))

    competencia_dt = date(ano_comp, mes_comp, 1)  # guardamos sempre o 1º dia do mês

    observacoes = st.text_area("Observações")

    if st.button("Enviar Solicitação"):
        empresa = empresas_validas.loc[
            empresas_validas["fantasia"] == fantasia
        ].iloc[0]

        nova_linha = {
            "razao_emissor":  empresa.get("nome_empresa", ""),
            "cnpj_emissor":   empresa.get("id_empresa", ""),
            "razao_parceiro": empresa.get("nome_parceiro", ""),
            "cnpj_parceiro":  empresa.get("id_parceiro", ""),
            "observacoes":    observacoes,
            "valor":          valor,
            "data_solicitacao": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "competencia_pagamento": competencia_dt.isoformat(),  # mantenha se existir no banco
            "usuario":        (usuario_nome or ""),
            "data_upload":    None,
            "pdf_path":       None,
            "xml_path":       None,
            "status":         "Pendente",
        }

        salvar_nota(nova_linha)

        # Texto condicional baseado no recebimento
        receb_msg = (
            "Esse valor já está no caixa da empresa."
            if empresa.get("recebimento", "").lower() == "anterior"
            else "Esse valor ainda será pago pelo parceiro."
        )

        corpo_email = f"""
        <p>Prezados,</p>
        <p>Poderiam por favor emitir uma nota para o seguinte parceiro:</p>
        <p>
        Empresa: {empresa.get('nome_empresa','')}<br>
        CNPJ: {empresa.get('id_empresa','')}<br>
        Empresa Tomadora: {empresa.get('nome_parceiro','')}<br>
        CNPJ: {empresa.get('id_parceiro','')}<br>
        Observações: {observacoes or '-'}<br>
        Valor: R$ {valor:,.2f}<br>
        {receb_msg}
        </p>
        <p>Não esqueçam de subir o PDF e o XML no nosso sistema!</p>
        <p>Obrigado!</p>
        <p>Att,<br>Time Comissões</p>
        """
        try:
            Mail().send(
                email="financeiro@investsmart.com.br",
                subject=f"Solicitação de nota {empresa.get('fantasia','')}",
                html=corpo_email,
                cc=["jedson.silva@investsmart.com.br"]
            )
        except Exception as e:
            st.error(f"Solicitação salva, mas houve erro ao enviar email: {e}")

        st.success("Nota solicitada! ✅")
        time.sleep(3)
        st.rerun()

def page_minhas_notas(usuario_nome: str):
    inject_base_css()
    st.header("Minhas Notas Fiscais")
    
    historico = carregar_notas().copy()

    if "usuario" not in historico.columns:
        historico["usuario"] = ""
        st.stop()

    u = (usuario_nome or "")
    minhas = historico.loc[historico["usuario"].fillna("") == u]

    # Garante que exista coluna pdf_path para evitar erro
    if "pdf_path" not in historico.columns:
        st.info("Ainda não existem notas cadastradas no sistema.")
        return

    # Se ficou vazio mas existem registros sem dono
    sem_dono = historico[historico["usuario"].isna() | (historico["usuario"] == "")]
    if minhas.empty and not sem_dono.empty:
        st.info("Você ainda não tem notas atribuídas. Existem solicitações sem dono:")
        for _, row in sem_dono.iterrows():
            cols = st.columns([3, 2, 2, 1])
            with cols[0]:
                st.write(f"**{row.get('razao_parceiro','')}**")
                st.caption(f"Obs.: {row.get('observacoes','')}")
            with cols[1]:
                st.write(row.get("valor", ""))
            with cols[2]:
                st.write(row.get("data_solicitacao",""))
            with cols[3]:
                if st.button("Atribuir a mim", key=f"claim_{row['id']}"):
                    atualizar_nota(int(row["id"]), {"usuario": u})
                    st.rerun()

    # Se ainda não houver nada para mostrar
    if minhas.empty:
        st.success("Não há notas pendentes ou emitidas para você.")
        return

    pendentes = minhas[(minhas["pdf_path"].isna()) & (minhas["status"].fillna("") == "Pendente")]
    emitidas  = minhas[(minhas["pdf_path"].notna()) & (minhas["status"] == "Emitida")]
    enviadas  = minhas[minhas["status"] == "Enviada"]

    # --- helpers de formatação (somente visual) ---
    def _fmt_brl(v):
        try:
            v = float(v)
            s = f"{v:,.2f}"
            return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")
        except Exception:
            return v

    def _fmt_dt(v):
        if pd.isna(v) or v in ("", None):
            return ""
        try:
            # remove microssegundos e normaliza formato ISO
            v = str(v).split(".")[0]
            dt = pd.to_datetime(v, errors="coerce", utc=True)
            if pd.isna(dt):
                return str(v)
            # converte para horário local (Brasília)
            dt = dt.tz_convert("America/Sao_Paulo")
            return dt.strftime("%d/%m/%Y %H:%M")
        except Exception:
            return str(v)

    st.subheader("Notas Pendentes")
    if pendentes.empty:
        st.success("Não há notas pendentes.")
    else:
        # --- monta dataframe com ID para permitir ação por linha ---
        dfp = pendentes[["id", "razao_parceiro", "valor", "data_solicitacao", "observacoes"]].copy()

        # formatações visuais
        dfp["Razão Parceiro"]   = dfp["razao_parceiro"]
        dfp["Valor"]            = dfp["valor"].apply(_fmt_brl)
        dfp["Data Solicitação"] = dfp["data_solicitacao"].apply(_fmt_dt)
        dfp["Observações"]      = dfp["observacoes"]

        # usa o ID como índice (oculto na UI)
        dfp = dfp.set_index("id", drop=True)
        dfp.index = dfp.index.astype(int)

        # estado persistente das seleções (por usuário)
        sel_key_pend = f"__pendentes_sel__{u}"
        if sel_key_pend not in st.session_state:
            st.session_state[sel_key_pend] = {}  # {id:int -> bool}

        # hidrata checkbox a partir do estado
        dfp["Cancelar Nota"] = dfp.index.to_series().map(
            lambda i: bool(st.session_state[sel_key_pend].get(int(i), False))
        ).fillna(False)

        edited_pend = st.data_editor(
            dfp[["Razão Parceiro", "Valor", "Data Solicitação", "Observações", "Cancelar Nota"]],
            hide_index=True,
            use_container_width=True,
            key="editor_pendentes",
            column_config={
                "Razão Parceiro":   st.column_config.TextColumn("Razão Parceiro"),
                "Valor":            st.column_config.TextColumn("Valor"),
                "Data Solicitação": st.column_config.TextColumn("Data Solicitação"),
                "Observações":      st.column_config.TextColumn("Observações"),
                "Cancelar Nota":    st.column_config.CheckboxColumn(
                    "Cancelar Nota",
                    help="Marque para cancelar esta nota (status: Cancelada)",
                    default=False
                ),
            }
        )

        # sincroniza estado com o que o usuário marcou
        st.session_state[sel_key_pend] = {
            int(i): bool(v) for i, v in edited_pend["Cancelar Nota"].items()
        }

        # ids marcados para cancelar
        ids_to_cancel = [i for i, v in st.session_state[sel_key_pend].items() if v]

        # chaves de estado do modal
        modal_flag_key = "__show_cancel_modal__"
        modal_ids_key  = "__cancel_ids__"

        # --- 1) Defina o dialog uma única vez no topo da função page_minhas_notas ---
        @st.dialog("Confirmar cancelamento", width="large")
        def confirmar_cancelamento_dialog(ids_sel: list[int], df_preview: pd.DataFrame):
            st.write("Você realmente deseja cancelar a(s) nota(s) abaixo:")
            st.dataframe(df_preview, hide_index=True, use_container_width=True)

            c1, c2 = st.columns(2)
            with c1:
                if st.button("Voltar", key="dlg_voltar"):
                    # fecha o diálogo apenas
                    st.rerun()  # fecha o modal e reroda a página

            with c2:
                if st.button("Confirmar Cancelamento", type="primary", key="dlg_confirmar"):
                    for _id in ids_sel:
                        atualizar_nota(int(_id), {"status": "Cancelada"})
                    # limpa seleções e informa sucesso; o rerun fecha o modal
                    st.session_state[sel_key_pend] = {}
                    st.success(f"{len(ids_sel)} nota(s) cancelada(s) com sucesso.")
                    st.rerun()

        # --- 2) Mais abaixo, na parte dos botões, chame o dialog ---
        # ids marcados para cancelar
        ids_to_cancel = [i for i, v in st.session_state[sel_key_pend].items() if v]

        if ids_to_cancel:
            if st.button("Aplicar mudanças", key="btn_pendentes_apply"):
                # monte o preview com as colunas já formatadas que estão em dfp
                resumo_cols = ["Razão Parceiro", "Valor", "Data Solicitação", "Observações"]
                try:
                    df_preview = dfp.loc[list(map(int, ids_to_cancel)), resumo_cols].copy()
                except Exception:
                    disponiveis = [c for c in resumo_cols if c in dfp.columns]
                    df_preview = dfp.loc[list(map(int, ids_to_cancel)), disponiveis].copy()

                # abre o modal
                confirmar_cancelamento_dialog(list(map(int, ids_to_cancel)), df_preview)


    st.subheader("Notas Emitidas")
    if emitidas.empty:
        st.info("Nenhuma nota emitida aguardando envio.")
    else:
        # --- monta dataframe para exibição/edição ---
        dfe = emitidas[["id","razao_parceiro","valor","data_solicitacao","pdf_path","xml_path"]].copy()
        
        # --- formatações visuais ---
        dfe["Razão Parceiro"] = dfe["razao_parceiro"]
        dfe["Valor"] = dfe["valor"].apply(_fmt_brl)
        dfe["Data Solicitação"] = dfe["data_solicitacao"].apply(_fmt_dt)

        dfe["PDF"] = dfe["pdf_path"].map(signed_download_url_cached)
        dfe["XML"] = dfe["xml_path"].map(signed_download_url_cached)

        # adiciona coluna de ação (checkbox) e usa o ID como índice oculto
        # use a coluna id como índice e garanta tipo int
        dfe = dfe.set_index("id", drop=True)
        dfe.index = dfe.index.astype(int)

        # estado persistente das seleções
        sel_key_emit = f"__emitidas_sel__{u}"
        if sel_key_emit not in st.session_state:
            st.session_state[sel_key_emit] = {}  # {id:int -> bool}

        # hidrate a coluna a partir do estado
        dfe["Confirmar envio"] = dfe.index.to_series().map(
            lambda i: bool(st.session_state[sel_key_emit].get(int(i), False))
        ).fillna(False)

        edited = st.data_editor(
            dfe[["Razão Parceiro","Valor","Data Solicitação","PDF","XML","Confirmar envio"]],
            hide_index=True,
            use_container_width=True,
            key="editor_emitidas",  # << chave estável
            column_config={
                "Razão Parceiro": st.column_config.TextColumn("Razão Parceiro"),
                "Valor": st.column_config.TextColumn("Valor"),
                "Data Solicitação": st.column_config.TextColumn("Data Solicitação"),
                "PDF": st.column_config.LinkColumn("PDF", display_text="📥 PDF"),
                "XML": st.column_config.LinkColumn("XML", display_text="📥 XML"),
                "Confirmar envio": st.column_config.CheckboxColumn(
                    "Confirmar envio",
                    help="Marque para confirmar que a nota foi enviada ao parceiro",
                    default=False
                )
            }
        )

        # sincronize o que o usuário marcou com o session_state
        st.session_state[sel_key_emit] = {
            int(i): bool(v) for i, v in edited["Confirmar envio"].items()
        }

        ids_to_send = [i for i, v in st.session_state[sel_key_emit].items() if v]

        # botão com chave única; aparece só quando houver seleção
        if ids_to_send:
            if st.button("Aplicar mudanças", key="btn_emitidas_apply"):
                for _id in ids_to_send:
                    atualizar_nota(int(_id), {"status": "Enviada"})
                st.session_state[sel_key_emit] = {}  # limpa seleção
                st.success(f"{len(ids_to_send)} nota(s) marcada(s) como 'Enviada'.")
                st.rerun()


    st.subheader("Notas enviadas aos parceiros")
    if enviadas.empty:
        st.info("Nenhuma nota enviada ainda.")
    else:
        # monta dataframe para exibição/edição
        dfe = enviadas[["id","razao_parceiro","valor","data_solicitacao"]].copy()
        dfe["valor"] = dfe["valor"].apply(_fmt_brl)
        dfe["data_solicitacao"] = dfe["data_solicitacao"].apply(_fmt_dt)
        dfe = dfe.rename(columns={
            "razao_parceiro": "Razão Parceiro",
            "valor": "Valor",
            "data_solicitacao": "Data Solicitação",
        })

        # adiciona coluna de ação (checkbox) e usa o ID como índice oculto
        dfe = dfe.set_index("id", drop=True)
        dfe.index = dfe.index.astype(int)

        sel_key_env = f"__enviadas_sel__{u}"
        if sel_key_env not in st.session_state:
            st.session_state[sel_key_env] = {}

        dfe["Desfazer envio"] = dfe.index.to_series().map(
            lambda i: bool(st.session_state[sel_key_env].get(int(i), False))
        ).fillna(False)

        edited = st.data_editor(
            dfe[["Razão Parceiro","Valor","Data Solicitação","Desfazer envio"]],
            hide_index=True,
            use_container_width=True,
            key="editor_enviadas",
            column_config={
                "Desfazer envio": st.column_config.CheckboxColumn(
                    "Desfazer envio",
                    help="Marque para desfazer o envio desta nota",
                    default=False
                )
            }
        )

        st.session_state[sel_key_env] = {
            int(i): bool(v) for i, v in edited["Desfazer envio"].items()
        }

        ids_to_undo = [i for i, v in st.session_state[sel_key_env].items() if v]
        if ids_to_undo:
            if st.button("Aplicar mudanças", key="btn_enviadas_apply"):
                for _id in ids_to_undo:
                    atualizar_nota(int(_id), {"status": "Emitida"})
                st.session_state[sel_key_env] = {}
                st.success(f"{len(ids_to_undo)} nota(s) revertida(s) para 'Emitida'.")
                st.rerun()

def page_cadastro_parceiro():
    """
    Tela para cadastrar e editar registros de public.de_para_empresas.
    Campos:
      - nome_empresa (obrigatório)
      - id_empresa   (obrigatório)
      - nome_parceiro, id_parceiro, fantasia
      - emissao_necessaria, recebimento, envio
      - email_para
    """
    inject_base_css()
    st.header("Cadastro Parceiro")

    # Carrega base atual
    df = carregar_empresas().copy()
    df.columns = [str(c).lower().strip() for c in df.columns]

    # Garante colunas esperadas
    cols = ["id","nome_empresa","id_empresa","nome_parceiro","id_parceiro",
            "fantasia","emissao_necessaria","recebimento","envio","email_para","created_at"]
    for c in cols:
        if c not in df.columns:
            df[c] = "" if c != "id" else None

    # ---- Lista atual (visão rápida) ----
    st.subheader("Parceiros cadastrados")
    vis = df[["id","fantasia","nome_empresa","id_empresa","nome_parceiro","id_parceiro",
            "emissao_necessaria","recebimento","envio","email_para"]].copy()
    st.dataframe(vis, use_container_width=True)

    st.markdown("---")
    st.subheader("Cadastrar / Editar")

    # Seletor para edição
    ids = [int(x) for x in df["id"].dropna().astype(int).tolist()] if not df.empty else []
    modo_col1, modo_col2 = st.columns([1, 3])
    with modo_col1:
        modo = st.radio("Modo", ["Novo", "Editar"], horizontal=True)

    # Mapeia rótulos "id — fantasia"
    label_map = {}
    if not df.empty:
        for _, r in df[["id", "fantasia", "nome_parceiro"]].dropna(subset=["id"]).iterrows():
            _id = int(r["id"])
            _fant = str(r.get("fantasia") or "").strip()
            if not _fant:
                _fant = str(r.get("nome_parceiro") or "").strip()
            label_map[_id] = f"{_id} — {_fant}"

    id_sel = None
    with modo_col2:
        if modo == "Editar":
            options = [int(x) for x in df["id"].dropna().astype(int).tolist()]
            id_sel = st.selectbox(
                "Selecionar registro para editar",
                options,
                format_func=lambda i: label_map.get(int(i), str(i))
            )

    # Dados base (carrega se edição)
    registro = {}
    if modo == "Editar" and id_sel:
        registro = df.loc[df["id"] == id_sel].iloc[0].to_dict()

    # ---- Formulário ----
    with st.form("form_empresa", clear_on_submit=False):
        colA, colB = st.columns([2,2])
        with colA:
            nome_empresa = st.text_input("Nome da Empresa *", value=registro.get("nome_empresa",""))
            id_empresa   = st.text_input("CNPJ da Empresa *", value=registro.get("id_empresa",""))
            fantasia     = st.text_input("Fantasia *", value=registro.get("fantasia",""))
            emissao_necessaria = st.selectbox("Emissão necessária?", ["", "sim", "nao"],
                                              index=["","sim","nao"].index(str(registro.get("emissao_necessaria","")).lower() if registro else ""))
        with colB:
            nome_parceiro = st.text_input("Nome do Parceiro *", value=registro.get("nome_parceiro",""))
            id_parceiro   = st.text_input("CNPJ do Parceiro *", value=registro.get("id_parceiro",""))
            recebimento   = st.selectbox("Recebimento (anterior / posterior)", ["", "anterior", "posterior"],
                                         index=["","anterior","posterior"].index(str(registro.get("recebimento","")).lower() if registro else ""))
            envio         = st.selectbox("Envio (ex.: email / portal / nao necessario)", ["", "email", "portal", "nao necessario"],
                                         index=["", "email", "portal", "nao necessario"].index(str(registro.get("envio","")).lower() if registro else ""))

        email_para = st.text_input("E-mails para envio (separar por ';')", value=registro.get("email_para",""))

        submitted = st.form_submit_button("Salvar" if modo=="Novo" else "Atualizar")

    # ---- Validação mínima e gravação ----
    if submitted:
        obrigatorios_ok = all([
            nome_empresa.strip(),
            id_empresa.strip(),
            nome_parceiro.strip(),
            id_parceiro.strip(),
            fantasia.strip(),
        ])
        if not obrigatorios_ok:
            st.error(
                "Preencha os campos obrigatórios: Nome da Empresa, CNPJ da Empresa, "
                "Nome do Parceiro, CNPJ do Parceiro e Fantasia."
            )
            return

        payload = {
            "nome_empresa": nome_empresa.strip(),
            "id_empresa":   id_empresa.strip(),
            "nome_parceiro": (nome_parceiro or "").strip(),
            "id_parceiro":   (id_parceiro or "").strip(),
            "fantasia":      (fantasia or "").strip(),
            "emissao_necessaria": (emissao_necessaria or "").strip(),
            "recebimento":   (recebimento or "").strip(),
            "envio":         (envio or "").strip(),
            "email_para":    (email_para or "").strip(),
        }

        try:
            if modo == "Novo":
                salvar_empresa(payload)
                st.success("Parceiro cadastrado com sucesso! ✅")
            else:
                atualizar_empresa(int(id_sel), payload)
                st.success("Parceiro atualizado com sucesso! ✅")

            # Recarrega DF global usado em "Solicitar Nota", para refletir alterações
            try:
                global DF_FANTASIA
                DF_FANTASIA = carregar_empresas()
                DF_FANTASIA.columns = [str(c).lower().strip() for c in DF_FANTASIA.columns]
                for c in ["emissao_necessaria","fantasia","nome_empresa","id_empresa",
                          "nome_parceiro","id_parceiro","recebimento","envio","email_para"]:
                    if c not in DF_FANTASIA.columns:
                        DF_FANTASIA[c] = ""
                    DF_FANTASIA[c] = DF_FANTASIA[c].fillna("").astype(str)
            except Exception:
                pass

            time.sleep(2)
            st.rerun()
        except Exception as e:
            st.error(f"Erro ao salvar: {e}")
