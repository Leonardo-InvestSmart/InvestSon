import streamlit as st
import pandas as pd
import datetime
import time
from db import carregar_notas, salvar_nota, atualizar_nota, carregar_empresas
from .ui import inject_base_css
from utils_storage import download_bytes
from .api_email import Mail

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
    st.sidebar.header("Menu")
    if st.sidebar.button("Solicitar Nota"):
        st.session_state.menu = "Solicitar Nota"
    if st.sidebar.button("Minhas Notas"):
        st.session_state.menu = "Minhas Notas"

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
            "data_solicitacao": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
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

    st.subheader("Notas Pendentes")
    if pendentes.empty:
        st.success("Não há notas pendentes.")
    else:
        st.dataframe(pendentes[["razao_parceiro","valor","data_solicitacao","observacoes"]])

    st.subheader("Notas Emitidas")
    if emitidas.empty:
        st.info("Nenhuma nota emitida aguardando envio.")
    else:
        for _, row in emitidas.iterrows():
            col1, col2, col3, col4 = st.columns([2,1,1,1])
            with col1: st.write(row["razao_parceiro"])
            with col2: st.write(f"R$ {row['valor']:.2f}")
            with col3:
                if row["pdf_path"]:
                    file_name, mime, data = download_bytes("notas_fiscais", row["pdf_path"])
                    st.download_button("📥 Baixar PDF", data=data, file_name=file_name, mime=mime, use_container_width=True)
                else:
                    st.write("Sem PDF")
            with col4:
                if st.button("✅", key=f"enviar_{row['id']}"):
                    atualizar_nota(row["id"], {"status": "Enviada"})
                    st.rerun()

    st.subheader("Notas enviadas aos parceiros")
    if enviadas.empty:
        st.info("Nenhuma nota enviada ainda.")
    else:
        st.dataframe(enviadas[["razao_parceiro","valor","data_solicitacao"]])
