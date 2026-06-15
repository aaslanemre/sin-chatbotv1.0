import os
import time
import math

def Script_Inclui_DBAR(Script,
                       vet_numero,
                       vet_operacao,
                       vet_estado,
                       vet_tipo,
                       vet_GBT,
                       vet_nome,
                       vet_GLT,
                       vet_Tensao,
                       vet_Angulo,
                       vet_geracao_P,
                       vet_geracao_Q,
                       vet_limite_Q_min,
                       vet_limite_Q_max,
                       vet_Barra_Controlada,
                       vet_carga_P,
                       vet_carga_Q,
                       vet_Banco_Cap_Reat,
                       vet_Area,
                       vet_Tensao_def_carga):

    n_bar = len(vet_numero)

    vet_numero = formatar_argumentos(vet_numero, n_bar, 5)
    vet_operacao = formatar_argumentos(vet_operacao, n_bar, 1)
    vet_estado = formatar_argumentos(vet_estado, n_bar, 1)
    vet_tipo = formatar_argumentos(vet_tipo, n_bar, 1)
    vet_GBT = formatar_argumentos(vet_GBT, n_bar, 5)
    vet_nome = formatar_argumentos(vet_nome, n_bar, 10)
    vet_GLT = formatar_argumentos(vet_GLT, n_bar, 2)
    vet_Tensao = formatar_argumentos(vet_Tensao, n_bar, 4)
    vet_Angulo = formatar_argumentos(vet_Angulo, n_bar, 4)
    vet_geracao_P = formatar_argumentos(vet_geracao_P, n_bar, 5)
    vet_geracao_Q = formatar_argumentos(vet_geracao_Q, n_bar, 5)
    vet_limite_Q_min = formatar_argumentos(vet_limite_Q_min, n_bar, 5)
    vet_limite_Q_max = formatar_argumentos(vet_limite_Q_max, n_bar, 5)
    vet_Barra_Controlada = formatar_argumentos(vet_Barra_Controlada, n_bar, 5)
    vet_carga_P = formatar_argumentos(vet_carga_P, n_bar, 5)
    vet_carga_Q = formatar_argumentos(vet_carga_Q, n_bar, 5)
    vet_Banco_Cap_Reat = formatar_argumentos(vet_Banco_Cap_Reat, n_bar, 5)
    vet_Area = formatar_argumentos(vet_Area, n_bar, 5)
    vet_Tensao_def_carga = formatar_argumentos(vet_Tensao_def_carga, n_bar, 5)

    linhas = []

    Script_AbreCod(linhas, "DBAR")
    linhas.append('(Num)OETGb(   nome   )Gl( V)( A)( Pg)( Qg)( Qn)( Qm)(Bc  )( Pl)( Ql)( Sh)Are(Vf)M(1)(2)(3)(4)(5)(6)(7)(8)(9)(10')

    for k in range(0, n_bar):
        numero = str(vet_numero[k]).rjust(5)[:5]
        operacao = str(vet_operacao[k]).rjust(1)[:5]
        estado = str(vet_estado[k]).rjust(1)[:5]
        tipo = str(vet_tipo[k]).rjust(1)[:5]
        GBT = str(vet_GBT[k]).rjust(2)[:5]
        nome = str(vet_nome[k]).rjust(10)[:5]
        GLT = str(vet_GLT[k]).rjust(2)[:5]
        Tensao = str(vet_Tensao[k]).rjust(4)[:5]
        Angulo = str(vet_Angulo[k]).rjust(4)[:5]
        geracao_P = str(vet_geracao_P[k]).rjust(5)[:5]
        geracao_Q = str(vet_geracao_Q[k]).rjust(5)[:5]
        limite_Q_min = str(vet_limite_Q_min[k]).rjust(5)[:5]
        limite_Q_max = str(vet_limite_Q_max[k]).rjust(5)[:5]
        Barra_Controlada = str(vet_Barra_Controlada[k]).rjust(6)[:5]
        carga_P = str(vet_carga_P[k]).rjust(5)[:5]
        carga_Q = str(vet_carga_Q[k]).rjust(5)[:5]
        Banco_Cap_Reat = str(vet_Banco_Cap_Reat[k]).rjust(5)[:5]
        Area = str(vet_Area[k]).rjust(5)[:5]
        Tensao_def_carga = str(vet_Tensao_def_carga[k]).rjust(5)[:5]

        Script_adiciona_barra(linhas, numero, operacao, estado,
                              tipo, GBT, nome, GLT, Tensao, Angulo,
                              geracao_P, geracao_Q, limite_Q_min,
                              limite_Q_max, Barra_Controlada, carga_P,
                              carga_Q, Banco_Cap_Reat, Area, Tensao_def_carga)

    Script_FechaConjDados(linhas)
    Script.append(linhas)
    return Script


def formatar_argumentos(vetor, tamanho_esperado, tamanho_string):
    if vetor is None:
        vetor = []
    if len(vetor) < tamanho_esperado:
        vetor.extend([""] * (tamanho_esperado - len(vetor)))
    vetor_formatado = [str(v).rjust(tamanho_string)[:tamanho_string] for v in vetor]
    return vetor_formatado


def Script_adiciona_barra(Script, numero, operacao, estado, tipo, GBT,
                          nome, GLT, Tensao, Angulo, geracao_P, geracao_Q,
                          limite_Q_min, limite_Q_max, Barra_Controlada,
                          carga_P, carga_Q, Banco_Cap_Reat, Area,
                          Tensao_def_carga):

    cod_bar = numero.rjust(5)           + operacao.rjust(1)         +\
              estado.rjust(1)           + tipo.rjust(1)             +\
              GBT.rjust(2)              + nome.rjust(10)            +\
              GLT.rjust(2)              + Tensao.rjust(4)           +\
              Angulo.rjust(4)           + geracao_P.rjust(5)        +\
              geracao_Q.rjust(5)        + limite_Q_min.rjust(5)     +\
              limite_Q_max.rjust(5)     + Barra_Controlada.rjust(6) +\
              carga_P.rjust(5)          + carga_Q.rjust(5)          +\
              Banco_Cap_Reat.rjust(5)   + Area.rjust(5)             +\
              Tensao_def_carga.rjust(5)

    Script.append(cod_bar)
    return Script


def Script_AbreCod(Script, Cod):
    Script.append(Cod)
    return Script


def Script_FechaConjDados(Script):
    Script.append('99999')
    return Script


def calculate_q_limits(S_mva, P_mw):
    """Calculate reactive power limits from apparent and active power.
    Returns (q_min, q_max) in Mvar."""
    q = math.sqrt(max(0, S_mva**2 - P_mw**2))
    return (-round(q, 1), round(q, 1))
