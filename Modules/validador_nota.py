import xml.etree.ElementTree as ET
import io

# Namespace usado no XML ABRASF
NS = {'ns': 'http://www.abrasf.org.br/ABRASF/arquivos/nfse.xsd'}


def extrair_dados_xml(file_or_bytes):
    """
    Lê XML de NFSe e retorna dict com os campos necessários já normalizados.
    Aceita:
        - bytes (xml_file.read())
        - io.BytesIO
        - caminho de arquivo (str ou Path)
    """

    def norm_str(v):
        return str(v).strip().upper() if v else ""

    def norm_float(v):
        if not v:
            return None
        return float(str(v).replace(",", ".").strip())

    # Detecta tipo da entrada
    if isinstance(file_or_bytes, (bytes, bytearray)):
        buffer = io.BytesIO(file_or_bytes)
    elif isinstance(file_or_bytes, io.BytesIO):
        buffer = file_or_bytes
    else:
        buffer = file_or_bytes  # caminho de arquivo ou file-like

    # Faz o parse
    tree = ET.parse(buffer)
    root = tree.getroot()

    comp = root.find('.//ns:CompNfse', NS)
    if comp is None:
        return None

    inf = comp.find('.//ns:InfNfse', NS)
    if inf is None:
        return None

    servico = inf.find('.//ns:Servico', NS)
    prestador = inf.find('.//ns:PrestadorServico', NS)
    tomador = inf.find('.//ns:TomadorServico', NS)

    return {
        "valor": norm_float(servico.find('.//ns:ValorServicos', NS).text if servico is not None else None),
        "cnpj_emissor": norm_str(prestador.find('.//ns:Cnpj', NS).text if prestador is not None else None),
        "razao_emissor": norm_str(prestador.find('ns:RazaoSocial', NS).text if prestador is not None else None),
        "cnpj_parceiro": norm_str(tomador.find('.//ns:CpfCnpj/ns:Cnpj', NS).text if tomador is not None else None),
        "razao_parceiro": norm_str(tomador.find('ns:RazaoSocial', NS).text if tomador is not None else None),
    }