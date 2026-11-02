"""
Glossary shown in the user app (📖 Glossário + inline help in "modo iniciante").

PENDING REVIEW BY DOMAIN EXPERT — definitions written for v6.5.0 from general
power-systems knowledge and the conventions used in this app; they must be
validated before being treated as authoritative.
"""
import re

GLOSSARY_STATUS = "PENDING REVIEW BY DOMAIN EXPERT"

GLOSSARY = {
    "PV": "Barra de tensão controlada: a potência ativa (P) e o módulo da tensão (V) são "
          "especificados; o ANAREDE calcula a potência reativa necessária dentro dos limites "
          "Qmin/Qmax. No DBAR é o tipo 1.",
    "PQ": "Barra de carga: as potências ativa (P) e reativa (Q) são especificadas e a tensão "
          "é calculada pelo fluxo de potência. No DBAR é o tipo 0.",
    "Referência": "Barra de referência (slack, Vθ): tem tensão e ângulo fixos e fecha o balanço "
                  "de potência do sistema. Deve existir exatamente uma. No DBAR é o tipo 2.",
    "SAV": "Arquivo binário do ANAREDE com casos já convergidos (histórico de casos). É o "
           "ponto de partida dos estudos com bases do ONS e da EPE.",
    "PWF": "Arquivo texto do ANAREDE com códigos de execução e dados (DBAR, DLIN, …). Aqui é "
           "usado para as linhas de modificação ou, no modo rede do zero, para o caso completo.",
    "LST": "Arquivo de diagrama unifilar do ANAREDE, usado para visualizar a região de estudo "
           "e os resultados no diagrama.",
    "DBAR": "Código do ANAREDE para dados de barra: número, tipo, nome, tensão, geração, carga "
            "e limites de potência reativa.",
    "DLIN": "Código do ANAREDE para dados de circuitos (linhas e transformadores): barras de e "
            "para, circuito, R e X em %, susceptância em Mvar e, para transformadores, tap.",
    "DCER": "Código do ANAREDE para compensadores estáticos de reativos; é usado aqui para "
            "representar o STATCOM com seus limites de Q e a barra controlada.",
    "DCTG": "Código do ANAREDE para definir a lista de contingências (por exemplo, abertura de "
            "uma linha ou perda de um gerador) analisadas com o EXCT.",
    "N-1": "Critério de segurança: o sistema deve continuar operando dentro dos limites após a "
           "perda de qualquer elemento (uma linha, um transformador ou um gerador).",
    "hachura": "Marcação colorida no diagrama do ANAREDE que indica violação: vermelha para "
               "sobrecarga ou sobretensão, azul para subtensão.",
    "MVA": "Megavolt-ampère: unidade de potência aparente (S). Também é a base do sistema "
           "(normalmente 100 MVA) usada para os valores em pu e em %.",
    "Mvar": "Megavolt-ampère reativo: unidade de potência reativa (Q).",
    "pu": "Por unidade: valor dividido pelo valor de base (tensão base ou potência base). "
          "1,0 pu de tensão é a tensão nominal da barra.",
}

# v6.6.0 — terms of the ANATEM guide, kept apart from the ANAREDE terms above.
# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
GLOSSARY_ANATEM = {
    "ANATEM": "Programa do CEPEL para simulação no tempo da estabilidade eletromecânica "
              "(dinâmica) do sistema, a partir de um caso de fluxo de potência do ANAREDE.",
    "ANAT0": "Rotina acessada no ANAREDE (Análise > ANAT0) que prepara o caso para o ANATEM: "
             "distribui a geração de cada barra entre as máquinas da base dinâmica e gera um "
             "DMAQ com o número de unidades ajustado ao ponto de operação.",
    "STB": "Arquivo de entrada do ANATEM (.stb) que reúne os comandos da simulação: leitura do "
           "caso (.sav), arquivos de modelos, DMAQ, eventos (DEVT) e variáveis plotadas (DPLT).",
    "DMAQ": "Código do ANATEM com os dados das máquinas síncronas de cada barra: grupo, número "
            "de unidades e os modelos (CDUs) de seus controles.",
    "CDU": "Controlador Definido pelo Usuário: modelo de controle (regulador de tensão, de "
           "velocidade, PSS, conversores…) descrito em blocos e usado pelo ANATEM.",
    "DEVT": "Código do ANATEM para os eventos da simulação (ex: curto-circuito, abertura de "
            "linha, degrau).",
    "DPLT": "Código do ANATEM que define as variáveis gravadas para plotagem.",
    "DFNT": "Código do ANATEM que associa modelos (por exemplo, de usinas eólicas e "
            "fotovoltaicas) a barras do sistema.",
    "flat run": "Simulação sem perturbações usada para verificar a inicialização: com o caso "
                "bem inicializado, as variáveis ficam constantes.",
    "PLOTCEPEL": "Programa do CEPEL para visualizar os gráficos das variáveis gravadas pelo ANATEM.",
    "AVR": "Regulador automático de tensão da máquina síncrona: controla a tensão terminal "
           "atuando na excitação.",
    "GOV": "Regulador de velocidade da máquina (governador): controla a potência mecânica e, "
           "portanto, a potência ativa.",
    "PSS": "Estabilizador de sistema de potência: sinal adicional no regulador de tensão para "
           "amortecer oscilações eletromecânicas.",
}

# Everything the app shows (📖 Glossário, inline help) and matches in messages.
ALL_TERMS = {**GLOSSARY, **GLOSSARY_ANATEM}

# Case-sensitive acronyms; the rest match case-insensitively.
# "STB" also matches the file extension (.stb).
_CI_TERMS = {"Referência", "hachura", "flat run", "STB"}


def _pattern(term):
    flags = re.IGNORECASE if term in _CI_TERMS else 0
    return re.compile(r"(?<![\w-])" + re.escape(term) + r"(?![\w-])", flags)


_PATTERNS = {t: _pattern(t) for t in ALL_TERMS}


def find_terms(text):
    """Glossary terms mentioned in `text`, in glossary order."""
    t = text or ""
    return [term for term, pat in _PATTERNS.items() if pat.search(t)]
