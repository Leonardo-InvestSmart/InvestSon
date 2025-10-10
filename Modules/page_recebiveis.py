import streamlit as st
import pandas as pd
from datetime import date, datetime
import time
import calendar
import locale
from db import carregar_notas, salvar_nota, atualizar_nota, carregar_empresas
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
        pages = ["Solicitar Nota", "Minhas Notas"]
        icon_map = {"Solicitar Nota": "plus-circle", "Minhas Notas": "file-text"}
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
            "competencia_pagamento": competencia_dt.isoformat(),  # <-- NOVO (YYYY-MM-01)
            "usuario":        (usuario_nome or ""),
            "data_upload":    None,
            "pdf_path":       None,
            "xml_path":       None,
            "status":         "Pendente"
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

    pendentes = minhas[minhas["pdf_path"].isna()]
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
        dfp = pendentes[["razao_parceiro","valor","data_solicitacao","observacoes"]].copy()
        # formatações visuais
        dfp["valor"] = dfp["valor"].apply(_fmt_brl)
        dfp["data_solicitacao"] = dfp["data_solicitacao"].apply(_fmt_dt)
        # renomeia colunas
        dfp = dfp.rename(columns={
            "razao_parceiro": "Razão Parceiro",
            "valor": "Valor",
            "data_solicitacao": "Data Solicitação",
            "observacoes": "Observações",
        })
        st.dataframe(dfp, use_container_width=True)

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

