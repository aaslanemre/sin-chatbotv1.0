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
    
    # tratamento do tamanho dos vetores

    n_bar = len(vet_numero)

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

    # Cabeçario para o DBAR
    Script_AbreCod(linhas, "DBAR")
    linhas.append('(Num)OETGb(   nome   )Gl( V)( A)( Pg)( Qg)( Qn)( Qm)(Bc  )( Pl)( Ql)( Sh)Are(Vf)M(1)(2)(3)(4)(5)(6)(7)(8)(9)(10') #futuramente substituir por função para inserir regua

    for k in range(0, n_bar):
        numero = str(vet_numero[k]).rjust(5)[:5]
        operacao = str(vet_operacao[k]).rjust(1)[:1]
        estado = str(vet_estado[k]).rjust(1)[:51]
        tipo = str(vet_tipo[k]).rjust(1)[:5]
        GBT = str(vet_GBT[k]).rjust(2)[:2]
        nome = str(vet_nome[k]).rjust(12)[:12]
        GLT = str(vet_GLT[k]).rjust(2)[:5]
        Tensao = str(vet_Tensao[k])[:10]
        Angulo = str(vet_Angulo[k])[:10]
        geracao_P = str(vet_geracao_P[k])[:10]
        geracao_Q = str(vet_geracao_Q[k])[:10]
        limite_Q_min = str(vet_limite_Q_min[k])[:10]
        limite_Q_max = str(vet_limite_Q_max[k])[:10]
        Barra_Controlada = str(vet_Barra_Controlada[k]).rjust(6)[:6]
        carga_P = str(vet_carga_P[k])[:10]
        carga_Q = str(vet_carga_Q[k])[:10]
        Banco_Cap_Reat = str(vet_Banco_Cap_Reat[k])[:10]
        Area = str(vet_Area[k]).rjust(3)[:3]
        Tensao_def_carga = str(vet_Tensao_def_carga[k])[:10]


        Tensao = formatar_digitos_pimplic(Tensao,4)
        Angulo = formatar_digitos_pimplic(Angulo,4)
        geracao_P = formatar_digitos_pexplic(geracao_P,5)
        geracao_Q = formatar_digitos_pexplic(geracao_Q,5)
        limite_Q_min = formatar_digitos_pexplic(limite_Q_min,5)
        limite_Q_max = formatar_digitos_pexplic(limite_Q_max,5)
        Barra_Controlada = formatar_digitos_pexplic(Barra_Controlada,6)
        carga_P = formatar_digitos_pexplic(carga_P,5)
        carga_Q = formatar_digitos_pexplic(carga_Q,5)
        Banco_Cap_Reat = formatar_digitos_pexplic(Banco_Cap_Reat,5)
        Tensao_def_carga = formatar_digitos_pimplic(Tensao_def_carga,4)

        Script_adiciona_barra(linhas, numero, operacao, estado,
                              tipo, GBT, nome, GLT, Tensao, Angulo,
                              geracao_P, geracao_Q, limite_Q_min,
                              limite_Q_max, Barra_Controlada, carga_P,
                              carga_Q, Banco_Cap_Reat, Area, Tensao_def_carga)

    Script_FechaConjDados(linhas)

    Script.append(linhas)
    

    return Script

def formatar_argumentos(vetor, tamanho_esperado, tamanho_string):
    # Proteção contra argumentos nulos (None)
    if vetor is None:
        vetor = []

    # Normaliza o tamanho do vetor:
    if len(vetor) < tamanho_esperado:
        vetor.extend([""] * (tamanho_esperado - len(vetor)))
        
    # 2. Formata cada elemento com espaços à direita:
    vetor_formatado = [str(v).rjust(tamanho_string)[:tamanho_string] for v in vetor]
    
    return vetor_formatado
def formatar_digitos_pimplic(elemento,tamanho):
    # 1. Limpeza inicial: remove espaços em branco e padroniza o ponto
    texto = str(elemento).strip().replace(",", ".")
    
    try:
        valor = float(texto)
    except ValueError:
        # Retorno de segurança para valores não numéricos
        return texto[:tamanho].ljust(tamanho)
        
    # Conta a quantidade de algarismos originais (ignorando ponto e sinal)
    num_digitos = len(texto.replace(".", "").replace("-", ""))
    
    # 2. Avalia a necessidade ESTRITA do ponto decimal
    precisa_ponto = (abs(valor) >= 10) or (num_digitos < tamanho)
    
    # Previne que um arredondamento faça um número < 10 atingir a magnitude 10
    if not precisa_ponto and abs(round(valor, tamanho-1)) >= 10:
        precisa_ponto = True

    # 3. Calcula o espaço disponível e aplica o arredondamento
    if precisa_ponto:
        # O ponto ocupará 1 caractere.
        # Espaço disponível para dígitos = 3 (ou 2 se for negativo)
        espaco_digitos = tamanho-1 if valor >= 0 else tamanho-2
        int_digitos = len(str(int(abs(valor))))
        casas_decimais = max(0, espaco_digitos - int_digitos)
        
        # Formata com a precisão calculada (arredondamento automático)
        texto_formatado = f"{valor:.{casas_decimais}f}"
        
        # Garante a presença do ponto caso o arredondamento o tenha omitido (ex: 452.465 -> 452)
        if "." not in texto_formatado:
            texto_formatado += "."
            
    else:
        # Sem o ponto. Todos os 4 caracteres (ou 3 se negativo) são exclusivos para os dígitos.
        espaco_digitos = tamanho if valor >= 0 else tamanho-1
        int_digitos = len(str(int(abs(valor))))
        casas_decimais = max(0, espaco_digitos - int_digitos)
        
        # Formata com a precisão calculada (arredonda) e remove o ponto
        texto_formatado = f"{valor:.{casas_decimais}f}".replace(".", "")
        
    # Retorna os 4 primeiros caracteres, preenchendo com espaços à direita caso tenha ficado menor
    return texto_formatado[:tamanho].ljust(tamanho)
def formatar_digitos_pexplic(elemento, tamanho):
    # 1. Limpeza inicial
    texto = str(elemento).strip().replace(",", ".")
    
    try:
        valor = float(texto)
    except ValueError:
        # Retorno de segurança para valores não numéricos
        return texto[:tamanho].ljust(tamanho)
        
    # 2. Contabilização do espaço reservado (não-decimal)
    espaco_sinal = 1 if valor < 0 else 0
    int_digitos = len(str(int(abs(valor))))
    
    # O ponto decimal ocupa rigorosamente 1 caractere.
    # As casas decimais disponíveis são o restante do espaço da string.
    casas_decimais = tamanho - int_digitos - espaco_sinal - 1
    
    # 3. Formatação e Arredondamento
    if casas_decimais >= 0:
        # Formata aplicando arredondamento automático para as casas que cabem
        texto_formatado = f"{valor:.{casas_decimais}f}"
        
        # Se a formatação .0f omitir o ponto nativamente (ex: 452.4 -> 452),
        # força a inserção do ponto para garantir a leitura do dado como float
        # desde que o tamanho ainda permita.
        if "." not in texto_formatado and len(texto_formatado) < tamanho:
            texto_formatado += "."
            
    else:
        # Exceção: O número inteiro já ocupa todo o tamanho limite, 
        # logo não há espaço físico para o ponto decimal. Retorna o inteiro arredondado.
        texto_formatado = f"{int(round(valor, 0))}"
        
    # Retorna o valor fatiado (segurança) e preenchido com espaços à direita
    return texto_formatado[:tamanho].ljust(tamanho)

def Script_adiciona_barra(Script,
                         numero,
                         operacao,
                         estado,
                         tipo,
                         GBT,
                         nome, 
                         GLT, 
                         Tensao,
                         Angulo,
                         geracao_P, 
                         geracao_Q, 
                         limite_Q_min,
                         limite_Q_max, 
                         Barra_Controlada, 
                         carga_P, 
                         carga_Q, 
                         Banco_Cap_Reat, 
                         Area, 
                         Tensao_def_carga):

    cod_bar  = numero.rjust(5)           + operacao.rjust(1)         +\
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

def Script_AbreCod(Script, Cod): #Futuramente incluir verificação do código
    
    Script.append(Cod)

    return Script

def Script_FechaConjDados(Script): #Futuramente incluir verificação se tem código aberto e qual código é

    Script.append('99999')

    return Script

def Script_Inclui_DLIN(Script,
                       vet_tipo, # Indica se vai ser adicionado linhas (1 ou "L") ou transformadores (2 ou "T")
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
    
    # tratamento do tamanho dos vetores

    n_eqp = len(vet_Barra_De)

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

    # Cabeçario para o DBAR
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
        resistencia = str(vet_resistencia[k]).rjust(10)
        reatancia = str(vet_reatancia[k]).rjust(10)
        suceptancia = str(vet_suceptancia[k]).rjust(10)
        tap = str(vet_tap[k]).rjust(10)
        tap_min = str(vet_tap_min[k]).rjust(10)
        tap_max = str(vet_tap_max[k]).rjust(10)
        defasagem = str(vet_defasagem[k]).rjust(10)
        Barra_Controlada = str(vet_Barra_Controlada[k]).rjust(6)
        Capacidade_Normal = str(vet_Capacidade_Normal[k]).rjust(10)
        Capacidade_Emergencia = str(vet_Capacidade_Emergencia[k]).rjust(10)
        Numero_Taps = str(vet_Numero_Taps[k]).rjust(2)
        Capacidade_Equipamento = str(vet_Capacidade_Equipamento[k]).rjust(10)
        Numero_unidades = str(vet_Numero_unidades[k]).rjust(3)
        unidades_operacao = str(vet_unidades_operacao[k]).rjust(3)

        resistencia = formatar_digitos_pexplic(resistencia,6)
        reatancia = formatar_digitos_pexplic(reatancia,6)
        suceptancia = formatar_digitos_pexplic(suceptancia,6)
        tap = formatar_digitos_pexplic(tap,5)
        tap_min = formatar_digitos_pexplic(tap_min,5)
        tap_max = formatar_digitos_pexplic(tap_max,5)
        defasagem = formatar_digitos_pexplic(defasagem,5)
        Capacidade_Normal = formatar_digitos_pexplic(Capacidade_Normal,4)
        Capacidade_Emergencia = formatar_digitos_pexplic(Capacidade_Emergencia,4)
        Capacidade_Equipamento = formatar_digitos_pexplic(Capacidade_Equipamento,4)

        if   (tipo == "L") | (tipo == "1"):
            Script_adiciona_LT(linhas, Barra_De, Abertura_De, operacao, Abertura_Para, Barra_Para, circuito,
                  estado, proprietario, resistencia, reatancia, suceptancia, Capacidade_Normal, Capacidade_Emergencia,
                  Capacidade_Equipamento)
        elif (tipo == "T") | (tipo == "2"):
            Script_adiciona_Trafo(linhas, Barra_De, Abertura_De, operacao, Abertura_Para, Barra_Para, circuito,
                  estado, proprietario, modo_controle, resistencia, reatancia, suceptancia, tap,
                  tap_min, tap_max, defasagem, Barra_Controlada, Capacidade_Normal, Capacidade_Emergencia,
                  Numero_Taps, Capacidade_Equipamento, Numero_unidades, unidades_operacao)


    Script_FechaConjDados(linhas)

    Script.append(linhas)
    
    return Script

def Script_adiciona_LT(Script,
                       Barra_De, 
                       Abertura_De, 
                       operacao, 
                       Abertura_Para, 
                       Barra_Para,
                       circuito,
                       estado, 
                       proprietario, 
                       resistencia, 
                       reatancia, 
                       suceptancia, 
                       Capacidade_Normal, 
                       Capacidade_Emergencia,
                       Capacidade_Equipamento):
    
    espaco = "                              "

    cod_bar  = Barra_De.rjust(5)              + Abertura_De.rjust(1)               +\
               espaco[:1].rjust(1)            +\
               operacao.rjust(1)              + Abertura_Para.rjust(1)             +\
               espaco[:1].rjust(1)            +\
               Barra_Para.rjust(5)            + circuito.rjust(2)                  +\
               estado.rjust(1)                + proprietario.rjust(1)              +\
               espaco[:1].rjust(1)            + resistencia.rjust(6)               +\
               reatancia.rjust(6)             + suceptancia.rjust(6)               +\
               espaco[:20].rjust(20)          + espaco[:6].rjust(6)                +\
               Capacidade_Normal.rjust(4)     +\
               Capacidade_Emergencia.rjust(4) + espaco[:2].rjust(2)                +\
               Capacidade_Equipamento.rjust(4) 
    
    Script.append(cod_bar)

    return Script

def Script_adiciona_Trafo(Script,
                          Barra_De, 
                          Abertura_De, 
                          operacao, 
                          Abertura_Para, 
                          Barra_Para, 
                          circuito,
                          estado, 
                          proprietario, 
                          modo_controle, 
                          resistencia, 
                          reatancia, 
                          suceptancia, 
                          tap,
                          tap_min, 
                          tap_max, 
                          defasagem, 
                          Barra_Controlada, 
                          Capacidade_Normal, 
                          Capacidade_Emergencia,
                          Numero_Taps, 
                          Capacidade_Equipamento, 
                          Numero_unidades, 
                          unidades_operacao):
    
    espaco = "                              "

    cod_bar  = Barra_De.rjust(5)              + Abertura_De.rjust(1)               +\
               espaco[:1].rjust(1)            +\
               operacao.rjust(1)              + Abertura_Para.rjust(1)             +\
               espaco[:1].rjust(1)            +\
               Barra_Para.rjust(5)            + circuito.rjust(2)                  +\
               estado.rjust(1)                + proprietario.rjust(1)              +\
               modo_controle.rjust(1)         + resistencia.rjust(6)               +\
               reatancia.rjust(6)             + suceptancia.rjust(6)               +\
               tap.rjust(5)                   + tap_min.rjust(5)                   +\
               tap_max.rjust(5)               + defasagem.rjust(5)                 +\
               Barra_Controlada.rjust(6)      + Capacidade_Normal.rjust(4)         +\
               Capacidade_Emergencia.rjust(4) + Numero_Taps.rjust(2)               +\
               Capacidade_Equipamento.rjust(4)+ espaco[:10].rjust(10)              +\
               espaco[:20].rjust(20)          + Numero_unidades.rjust(3)           +\
               espaco[:1].rjust(1)            +\
               unidades_operacao.rjust(3)
    
    Script.append(cod_bar)

    return Script