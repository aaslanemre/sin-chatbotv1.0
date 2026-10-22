import math
import re

# ── Fixed-width numeric fields ────────────────────────────────────────────────
# Hard limit of the ANAREDE version in use (confirmed by the domain experts): a
# numeric field never carries more than 4 digits after the decimal point.
MAX_DECIMALS = 4

# Accepted by the product owner: smallest non-zero value within ANAREDE's
# 4-decimal limit; the earlier value 0.00001 cannot be written.
COUPLING_LINE_X_PCT = 0.0001

# DLIN transmission-line (LT) field widths written by Script_adiciona_LT.
DLIN_R_WIDTH, DLIN_X_WIDTH, DLIN_S_WIDTH = 6, 8, 6


def format_ansi_field(value, width, max_decimals=MAX_DECIMALS):
    """
    Text of one numeric field of an ANAREDE record, right-justified in `width`.

    - never longer than `width` and never more than `max_decimals` (at most 4)
      digits after the decimal point: the value is rounded to fit;
    - never scientific notation;
    - an int (or a text without a decimal point, e.g. "417") is written as an
      integer; any other value keeps an explicit decimal point ("12." if no
      decimal fits);
    - None or "" → blank field.
    Raises ValueError when the value cannot be written in the field at all.
    """
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return " " * width
    if isinstance(value, bool):
        raise ValueError(f"Valor inválido para campo numérico: {value!r}")
    max_decimals = max(0, min(int(max_decimals), MAX_DECIMALS))
    text = str(value).strip().replace(",", ".")
    if isinstance(value, int) or (isinstance(value, str) and re.fullmatch(r"[-+]?\d+", text)):
        s = str(int(text))
        if len(s) > width:
            raise ValueError(f"O valor {value} não cabe no campo de {width} colunas do ANAREDE.")
        return s.rjust(width)
    v = float(text)  # ValueError for non-numeric text
    if not math.isfinite(v):
        raise ValueError(f"Valor inválido para campo numérico: {value!r}")
    for decimals in range(max_decimals, -1, -1):
        s = f"{v:.{decimals}f}" + ("" if decimals else ".")
        if float(s) == 0:
            s = s.lstrip("-")
        if len(s) <= width:
            return s.rjust(width)
    raise ValueError(f"O valor {value} não cabe no campo de {width} colunas do ANAREDE.")


def field_text(value, width, max_decimals=MAX_DECIMALS):
    """The value exactly as written in the field, without padding (for user-facing text)."""
    return format_ansi_field(value, width, max_decimals).strip()


def rounds_to_zero(value, width, max_decimals=MAX_DECIMALS):
    """True when a non-zero value is written as zero in the field."""
    try:
        v = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return False
    return v != 0 and float(field_text(value, width, max_decimals)) == 0


def _valores_brutos(vetor, n):
    """Copy of a vector padded with "": numbers keep full precision until formatted."""
    v = list(vetor or [])
    return v + [""] * (n - len(v))


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
    bruto = {nome: _valores_brutos(vet, n_bar) for nome, vet in (
        ("Pg", vet_geracao_P), ("Qg", vet_geracao_Q), ("Qn", vet_limite_Q_min),
        ("Qm", vet_limite_Q_max), ("Bc", vet_Barra_Controlada), ("Pl", vet_carga_P),
        ("Ql", vet_carga_Q), ("Sh", vet_Banco_Cap_Reat))}

    vet_numero = formatar_argumentos(vet_numero, n_bar, 5)
    vet_operacao = formatar_argumentos(vet_operacao, n_bar, 1)
    vet_estado = formatar_argumentos(vet_estado, n_bar, 1)
    vet_tipo = formatar_argumentos(vet_tipo, n_bar, 1)
    vet_GBT = formatar_argumentos(vet_GBT, n_bar, 5)
    vet_nome = formatar_argumentos(vet_nome, n_bar, 12)
    vet_GLT = formatar_argumentos(vet_GLT, n_bar, 2)
    vet_Tensao = formatar_argumentos(vet_Tensao, n_bar, 10)
    vet_Angulo = formatar_argumentos(vet_Angulo, n_bar, 10)
    vet_geracao_P = formatar_argumentos(vet_geracao_P, n_bar, 10)
    vet_geracao_Q = formatar_argumentos(vet_geracao_Q, n_bar, 10)
    vet_limite_Q_min = formatar_argumentos(vet_limite_Q_min, n_bar, 10)
    vet_limite_Q_max = formatar_argumentos(vet_limite_Q_max, n_bar, 10)
    vet_Barra_Controlada = formatar_argumentos(vet_Barra_Controlada, n_bar, 5)
    vet_carga_P = formatar_argumentos(vet_carga_P, n_bar, 10)
    vet_carga_Q = formatar_argumentos(vet_carga_Q, n_bar, 10)
    vet_Banco_Cap_Reat = formatar_argumentos(vet_Banco_Cap_Reat, n_bar, 10)
    vet_Area = formatar_argumentos(vet_Area, n_bar, 3)
    vet_Tensao_def_carga = formatar_argumentos(vet_Tensao_def_carga, n_bar, 10)

    linhas = []

    Script_AbreCod(linhas, "DBAR")
    linhas.append('(Num)OETGb(   nome   )Gl( V)( A)( Pg)( Qg)( Qn)( Qm)(Bc  )( Pl)( Ql)( Sh)Are(Vf)M(1)(2)(3)(4)(5)(6)(7)(8)(9)(10')

    for k in range(0, n_bar):
        numero = str(vet_numero[k]).rjust(5)[:5]
        operacao = str(vet_operacao[k]).rjust(1)[:1]
        estado = str(vet_estado[k]).rjust(1)[:1]        # FIXED: was [:51]
        tipo = str(vet_tipo[k]).rjust(1)[:1]            # FIXED: was [:5]
        GBT = str(vet_GBT[k]).rjust(2)[:2]
        nome = str(vet_nome[k]).rjust(12)[:12]
        GLT = str(vet_GLT[k]).rjust(2)[:2]
        Tensao = str(vet_Tensao[k])[:10]
        Angulo = str(vet_Angulo[k])[:10]
        Area = str(vet_Area[k]).rjust(3)[:3]
        Tensao_def_carga = str(vet_Tensao_def_carga[k])[:10]

        # V, A and Vf keep the implicit-decimal convention of the DBAR ruler.
        Tensao = formatar_digitos_pimplic(Tensao, 4)
        Angulo = formatar_digitos_pimplic(Angulo, 4)
        geracao_P = format_ansi_field(bruto["Pg"][k], 5)
        geracao_Q = format_ansi_field(bruto["Qg"][k], 5)
        limite_Q_min = format_ansi_field(bruto["Qn"][k], 5)
        limite_Q_max = format_ansi_field(bruto["Qm"][k], 5)
        Barra_Controlada = format_ansi_field(bruto["Bc"][k], 6)
        carga_P = format_ansi_field(bruto["Pl"][k], 5)
        carga_Q = format_ansi_field(bruto["Ql"][k], 5)
        Banco_Cap_Reat = format_ansi_field(bruto["Sh"][k], 5)
        Tensao_def_carga = formatar_digitos_pimplic(Tensao_def_carga, 4)

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


def formatar_digitos_pimplic(elemento, tamanho):
    texto = str(elemento).strip().replace(",", ".")
    try:
        valor = float(texto)
    except ValueError:
        return texto[:tamanho].ljust(tamanho)

    num_digitos = len(texto.replace(".", "").replace("-", ""))
    precisa_ponto = (abs(valor) >= 10) or (num_digitos < tamanho)

    if not precisa_ponto and abs(round(valor, tamanho-1)) >= 10:
        precisa_ponto = True

    if precisa_ponto:
        espaco_digitos = tamanho-1 if valor >= 0 else tamanho-2
        int_digitos = len(str(int(abs(valor))))
        casas_decimais = max(0, espaco_digitos - int_digitos)
        texto_formatado = f"{valor:.{casas_decimais}f}"
        if "." not in texto_formatado:
            texto_formatado += "."
    else:
        espaco_digitos = tamanho if valor >= 0 else tamanho-1
        int_digitos = len(str(int(abs(valor))))
        casas_decimais = max(0, espaco_digitos - int_digitos)
        texto_formatado = f"{valor:.{casas_decimais}f}".replace(".", "")

    return texto_formatado[:tamanho].ljust(tamanho)


def formatar_digitos_pexplic(elemento, tamanho):
    # v6.5.1: explicit-decimal fields go through format_ansi_field (max 4 decimals,
    # no exponential notation, never wider than the field). Non-numeric text keeps
    # the old behaviour.
    texto = str(elemento).strip().replace(",", ".")
    try:
        float(texto)
    except ValueError:
        return texto[:tamanho].ljust(tamanho)
    return format_ansi_field(texto, tamanho)


def Script_adiciona_barra(Script, numero, operacao, estado, tipo, GBT,
                          nome, GLT, Tensao, Angulo, geracao_P, geracao_Q,
                          limite_Q_min, limite_Q_max, Barra_Controlada,
                          carga_P, carga_Q, Banco_Cap_Reat, Area,
                          Tensao_def_carga):

    cod_bar = numero.rjust(5)           + operacao.rjust(1)         +\
              estado.rjust(1)           + tipo.rjust(1)             +\
              GBT.rjust(2)              + nome.rjust(12)            +\
              GLT.rjust(2)              + Tensao.rjust(4)           +\
              Angulo.rjust(4)           + geracao_P.rjust(5)        +\
              geracao_Q.rjust(5)        + limite_Q_min.rjust(5)     +\
              limite_Q_max.rjust(5)     + Barra_Controlada.rjust(6) +\
              carga_P.rjust(5)          + carga_Q.rjust(5)          +\
              Banco_Cap_Reat.rjust(5)   + Area.rjust(3)             +\
              Tensao_def_carga.rjust(4)

    Script.append(cod_bar)
    return Script


def Script_AbreCod(Script, Cod):
    Script.append(Cod)
    return Script


def Script_FechaConjDados(Script):
    Script.append('99999')
    return Script


def Script_Inclui_DLIN(Script,
                       vet_tipo,
                       vet_Barra_De,
                       vet_Abertura_De,
                       vet_operacao,
                       vet_Barra_Para,
                       vet_Abertura_Para,
                       vet_circuito,
                       vet_estado,
                       vet_proprietario,
                       vet_modo_controle,
                       vet_resistencia,
                       vet_reatancia,
                       vet_suceptancia,
                       vet_tap,
                       vet_tap_min,
                       vet_tap_max,
                       vet_defasagem,
                       vet_Barra_Controlada,
                       vet_Capacidade_Normal,
                       vet_Capacidade_Emergencia,
                       vet_Numero_Taps,
                       vet_Capacidade_Equipamento,
                       vet_Numero_unidades,
                       vet_unidades_operacao):

    n_eqp = len(vet_Barra_De)
    bruto = {nome: _valores_brutos(vet, n_eqp) for nome, vet in (
        ("R", vet_resistencia), ("X", vet_reatancia), ("S", vet_suceptancia),
        ("Tap", vet_tap), ("Tmin", vet_tap_min), ("Tmax", vet_tap_max),
        ("Def", vet_defasagem), ("Cn", vet_Capacidade_Normal),
        ("Ce", vet_Capacidade_Emergencia), ("Ceq", vet_Capacidade_Equipamento))}

    vet_tipo = formatar_argumentos(vet_tipo, n_eqp, 1)
    vet_Barra_De = formatar_argumentos(vet_Barra_De, n_eqp, 5)
    vet_Abertura_De = formatar_argumentos(vet_Abertura_De, n_eqp, 1)
    vet_operacao = formatar_argumentos(vet_operacao, n_eqp, 1)
    vet_Abertura_Para = formatar_argumentos(vet_Abertura_Para, n_eqp, 1)
    vet_Barra_Para = formatar_argumentos(vet_Barra_Para, n_eqp, 5)
    vet_circuito = formatar_argumentos(vet_circuito, n_eqp, 2)
    vet_estado = formatar_argumentos(vet_estado, n_eqp, 1)
    vet_proprietario = formatar_argumentos(vet_proprietario, n_eqp, 1)
    vet_modo_controle = formatar_argumentos(vet_modo_controle, n_eqp, 1)
    vet_resistencia = formatar_argumentos(vet_resistencia, n_eqp, 10)
    vet_reatancia = formatar_argumentos(vet_reatancia, n_eqp, 10)
    vet_suceptancia = formatar_argumentos(vet_suceptancia, n_eqp, 10)
    vet_tap = formatar_argumentos(vet_tap, n_eqp, 10)
    vet_tap_min = formatar_argumentos(vet_tap_min, n_eqp, 10)
    vet_tap_max = formatar_argumentos(vet_tap_max, n_eqp, 10)
    vet_defasagem = formatar_argumentos(vet_defasagem, n_eqp, 10)
    vet_Barra_Controlada = formatar_argumentos(vet_Barra_Controlada, n_eqp, 6)
    vet_Capacidade_Normal = formatar_argumentos(vet_Capacidade_Normal, n_eqp, 10)
    vet_Capacidade_Emergencia = formatar_argumentos(vet_Capacidade_Emergencia, n_eqp, 10)
    vet_Numero_Taps = formatar_argumentos(vet_Numero_Taps, n_eqp, 2)
    vet_Capacidade_Equipamento = formatar_argumentos(vet_Capacidade_Equipamento, n_eqp, 10)
    vet_Numero_unidades = formatar_argumentos(vet_Numero_unidades, n_eqp, 3)
    vet_unidades_operacao = formatar_argumentos(vet_unidades_operacao, n_eqp, 3)

    linhas = []
    Script_AbreCod(linhas, "DLIN")

    for k in range(0, n_eqp):
        tipo = str(vet_tipo[k]).rjust(1)
        Barra_De = str(vet_Barra_De[k]).rjust(5)
        Abertura_De = str(vet_Abertura_De[k]).rjust(1)
        operacao = str(vet_operacao[k]).rjust(1)
        Abertura_Para = str(vet_Abertura_Para[k]).rjust(1)
        Barra_Para = str(vet_Barra_Para[k]).rjust(5)
        circuito = str(vet_circuito[k]).rjust(2)
        estado = str(vet_estado[k]).rjust(1)
        proprietario = str(vet_proprietario[k]).rjust(1)
        modo_controle = str(vet_modo_controle[k]).rjust(1)
        Barra_Controlada = str(vet_Barra_Controlada[k]).rjust(6)
        Numero_Taps = str(vet_Numero_Taps[k]).rjust(2)
        Numero_unidades = str(vet_Numero_unidades[k]).rjust(3)
        unidades_operacao = str(vet_unidades_operacao[k]).rjust(3)

        # The LT record has an 8-column X field; the transformer record keeps 6.
        e_linha = tipo in ("L", "1")
        resistencia = format_ansi_field(bruto["R"][k], DLIN_R_WIDTH)
        reatancia = format_ansi_field(bruto["X"][k], DLIN_X_WIDTH if e_linha else 6)
        suceptancia = format_ansi_field(bruto["S"][k], DLIN_S_WIDTH)
        tap = format_ansi_field(bruto["Tap"][k], 5)
        tap_min = format_ansi_field(bruto["Tmin"][k], 5)
        tap_max = format_ansi_field(bruto["Tmax"][k], 5)
        defasagem = format_ansi_field(bruto["Def"][k], 5)
        Capacidade_Normal = format_ansi_field(bruto["Cn"][k], 4)
        Capacidade_Emergencia = format_ansi_field(bruto["Ce"][k], 4)
        Capacidade_Equipamento = format_ansi_field(bruto["Ceq"][k], 4)

        if (tipo == "L") or (tipo == "1"):
            Script_adiciona_LT(linhas, Barra_De, Abertura_De, operacao,
                               Abertura_Para, Barra_Para, circuito, estado,
                               proprietario, resistencia, reatancia,
                               suceptancia, Capacidade_Normal,
                               Capacidade_Emergencia, Capacidade_Equipamento)
        elif (tipo == "T") or (tipo == "2"):
            Script_adiciona_Trafo(linhas, Barra_De, Abertura_De, operacao,
                                  Abertura_Para, Barra_Para, circuito, estado,
                                  proprietario, modo_controle, resistencia,
                                  reatancia, suceptancia, tap, tap_min,
                                  tap_max, defasagem, Barra_Controlada,
                                  Capacidade_Normal, Capacidade_Emergencia,
                                  Numero_Taps, Capacidade_Equipamento,
                                  Numero_unidades, unidades_operacao)

    Script_FechaConjDados(linhas)
    Script.append(linhas)
    return Script


def Script_adiciona_LT(Script, Barra_De, Abertura_De, operacao,
                       Abertura_Para, Barra_Para, circuito, estado,
                       proprietario, resistencia, reatancia, suceptancia,
                       Capacidade_Normal, Capacidade_Emergencia,
                       Capacidade_Equipamento):

    espaco = "                              "
    cod_bar = Barra_De.rjust(5)              + Abertura_De.rjust(1)              +\
              espaco[:1].rjust(1)            +\
              operacao.rjust(1)              + Abertura_Para.rjust(1)            +\
              espaco[:1].rjust(1)            +\
              Barra_Para.rjust(5)            + circuito.rjust(2)                 +\
              estado.rjust(1)                + proprietario.rjust(1)             +\
              espaco[:1].rjust(1)            + resistencia.rjust(6)              + ' ' +\
              reatancia.rjust(8)             + ' ' + suceptancia.rjust(6)        +\
              espaco[:20].rjust(20)          + espaco[:6].rjust(6)               +\
              Capacidade_Normal.rjust(4)     +\
              Capacidade_Emergencia.rjust(4) + espaco[:2].rjust(2)               +\
              Capacidade_Equipamento.rjust(4)
    Script.append(cod_bar)
    return Script


def Script_adiciona_Trafo(Script, Barra_De, Abertura_De, operacao,
                          Abertura_Para, Barra_Para, circuito, estado,
                          proprietario, modo_controle, resistencia, reatancia,
                          suceptancia, tap, tap_min, tap_max, defasagem,
                          Barra_Controlada, Capacidade_Normal,
                          Capacidade_Emergencia, Numero_Taps,
                          Capacidade_Equipamento, Numero_unidades,
                          unidades_operacao):

    espaco = "                              "
    cod_bar = Barra_De.rjust(5)              + Abertura_De.rjust(1)              +\
              espaco[:1].rjust(1)            +\
              operacao.rjust(1)              + Abertura_Para.rjust(1)            +\
              espaco[:1].rjust(1)            +\
              Barra_Para.rjust(5)            + circuito.rjust(2)                 +\
              estado.rjust(1)                + proprietario.rjust(1)             +\
              modo_controle.rjust(1)         + resistencia.rjust(6)              +\
              reatancia.rjust(6)             + suceptancia.rjust(6)              +\
              tap.rjust(5)                   + tap_min.rjust(5)                  +\
              tap_max.rjust(5)               + defasagem.rjust(5)                +\
              Barra_Controlada.rjust(6)      + Capacidade_Normal.rjust(4)        +\
              Capacidade_Emergencia.rjust(4) + Numero_Taps.rjust(2)              +\
              Capacidade_Equipamento.rjust(4)+ espaco[:10].rjust(10)             +\
              espaco[:20].rjust(20)          + Numero_unidades.rjust(3)          +\
              espaco[:1].rjust(1)            +\
              unidades_operacao.rjust(3)
    Script.append(cod_bar)
    return Script


def calculate_q_limits(S_mva, P_mw):
    """Returns (q_min, q_max) as integers in Mvar."""
    q = math.sqrt(max(0, float(S_mva)**2 - float(P_mw)**2))
    return (-int(round(q)), int(round(q)))


def Script_Inclui_DCER(Script,
                       vet_barra,
                       vet_operacao,
                       vet_grupo,
                       vet_unidades,
                       vet_barra_controlada,
                       vet_inclinacao,
                       vet_geracao_Q,
                       vet_limite_Q_min,
                       vet_limite_Q_max,
                       vet_modo_controle,
                       vet_estado,
                       vet_modo_correcao):

    n_cer = len(vet_barra)
    bruto = {nome: _valores_brutos(vet, n_cer) for nome, vet in (
        ("incl", vet_inclinacao), ("Qg", vet_geracao_Q),
        ("Qn", vet_limite_Q_min), ("Qm", vet_limite_Q_max))}

    vet_barra = formatar_argumentos(vet_barra, n_cer, 5)
    vet_operacao = formatar_argumentos(vet_operacao, n_cer, 1)
    vet_grupo = formatar_argumentos(vet_grupo, n_cer, 2)
    vet_unidades = formatar_argumentos(vet_unidades, n_cer, 2)
    vet_barra_controlada = formatar_argumentos(vet_barra_controlada, n_cer, 5)
    vet_inclinacao = formatar_argumentos(vet_inclinacao, n_cer, 6)
    vet_geracao_Q = formatar_argumentos(vet_geracao_Q, n_cer, 5)
    vet_limite_Q_min = formatar_argumentos(vet_limite_Q_min, n_cer, 5)
    vet_limite_Q_max = formatar_argumentos(vet_limite_Q_max, n_cer, 5)
    vet_modo_controle = formatar_argumentos(vet_modo_controle, n_cer, 1)
    vet_estado = formatar_argumentos(vet_estado, n_cer, 1)
    vet_modo_correcao = formatar_argumentos(vet_modo_correcao, n_cer, 1)

    linhas = []
    Script_AbreCod(linhas, "DCER")

    for k in range(n_cer):
        barra = str(vet_barra[k]).rjust(5)[:5]
        operacao = str(vet_operacao[k]).rjust(1)[:1]
        grupo = str(vet_grupo[k]).rjust(2)[:2]
        unidades = str(vet_unidades[k]).rjust(2)[:2]
        barra_controlada = str(vet_barra_controlada[k]).rjust(5)[:5]
        inclinacao = format_ansi_field(bruto["incl"][k], 6)
        geracao_Q = format_ansi_field(bruto["Qg"][k], 5)
        limite_Q_min = format_ansi_field(bruto["Qn"][k], 5)
        limite_Q_max = format_ansi_field(bruto["Qm"][k], 5)
        modo_controle = str(vet_modo_controle[k]).rjust(1)[:1]
        estado = str(vet_estado[k]).rjust(1)[:1]
        modo_correcao = str(vet_modo_correcao[k]).rjust(1)[:1]

        # Build line per ANAREDE manual column positions:
        # col 1-5: barra, col 6: space, col 7: operacao
        # col 8: space, col 9-10: grupo, col 11: space
        # col 12-13: unidades, col 14: space
        # col 15-19: barra_controlada, col 20: space
        # col 21-26: inclinacao, col 27: space
        # col 28-32: geracao_Q, col 33-37: limite_Q_min
        # col 38-42: limite_Q_max, col 43: space
        # col 44: modo_controle, col 45: space
        # col 46: estado, col 47: space
        # col 48: modo_correcao
        cod_cer = (barra.rjust(5) + ' ' +
                   operacao.rjust(1) + ' ' +
                   grupo.rjust(2) + ' ' +
                   unidades.rjust(2) + ' ' +
                   barra_controlada.rjust(5) + ' ' +
                   inclinacao.rjust(6) + ' ' +
                   geracao_Q.rjust(5) +
                   limite_Q_min.rjust(5) +
                   limite_Q_max.rjust(5) + ' ' +
                   modo_controle.rjust(1) + ' ' +
                   estado.rjust(1) + ' ' +
                   modo_correcao.rjust(1))

        linhas.append(cod_cer)

    Script_FechaConjDados(linhas)
    Script.append(linhas)
    return Script
