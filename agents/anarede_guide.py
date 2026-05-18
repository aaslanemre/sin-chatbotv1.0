"""
Anarede execution guide agent.
Tracks which step of the flowchart the user is on and returns
the next prompt/instruction to display.
"""
from enum import Enum
from typing import Optional


class FlowchartStep(Enum):
    OBJECTIVE = "objective"
    AREA_PERIOD = "area_period"
    SCENARIO_SELECTION = "scenario_selection"
    PWF_DOWNLOAD = "pwf_download"
    PWF_UPLOAD = "pwf_upload"
    PWF_MODIFICATION = "pwf_modification"
    CONTINGENCIES = "contingencies"
    EXECUTION = "execution"
    RESULTS_UPLOAD = "results_upload"
    ANALYSIS = "analysis"
    DONE = "done"


STEP_PROMPTS = {
    FlowchartStep.OBJECTIVE: (
        "Para começarmos o estudo no Anarede, qual é o objetivo principal? "
        "Por exemplo: localização de BESS, análise de contingência N-1, "
        "verificação de margem de escoamento, inserção de nova linha, etc."
    ),
    FlowchartStep.AREA_PERIOD: (
        "Qual área do SIN será estudada e qual período de planejamento? "
        "(Ex: Nordeste, horizonte 2030)"
    ),
    FlowchartStep.SCENARIO_SELECTION: (
        "Recomendo utilizar os casos da base EPE PDE 2035. Os 8 cenários disponíveis são:\n"
        "1. Máxima Diurna Seco\n2. Máxima Diurna Úmido\n"
        "3. Máxima Noturna Seco\n4. Máxima Noturna Úmido\n"
        "5. Mínima Noturna Seco\n6. Mínima Noturna Úmido\n"
        "7. Máxima Coincidente SIN\n8. Mínima Líquida Diurna Coincidente SIN\n\n"
        "Quais cenários são mais relevantes para seu estudo?"
    ),
    FlowchartStep.PWF_DOWNLOAD: (
        "Baixe o arquivo PWF do cenário selecionado no portal da EPE:\n"
        "https://www.epe.gov.br/pt/areas-de-atuacao/energia-eletrica/planejamento-da-transmissao/bases-de-dados-de-simulacao\n\n"
        "Após o download, faça o upload do arquivo usando o ícone 📎 na barra de chat."
    ),
    FlowchartStep.PWF_UPLOAD: (
        "Aguardando o upload do arquivo PWF. Use o ícone 📎 na barra de entrada para anexar o arquivo."
    ),
    FlowchartStep.PWF_MODIFICATION: (
        "Com base no objetivo do estudo, precisamos modificar o caso base. "
        "Qual elemento você deseja inserir ou modificar? "
        "(Ex: BESS de 100 MW na barra 1234, nova linha de transmissão, etc.)"
    ),
    FlowchartStep.CONTINGENCIES: (
        "Quais contingências N-1 devem ser simuladas? "
        "Informe os elementos críticos (linhas ou transformadores) da área de estudo."
    ),
    FlowchartStep.EXECUTION: (
        "Agora execute o Anarede com o arquivo PWF preparado:\n"
        "1. Abra o Anarede\n"
        "2. Carregue o arquivo PWF: Arquivo → Abrir\n"
        "3. Execute o fluxo de potência: Executar → Fluxo de Potência (Newton-Raphson)\n"
        "4. Salve o relatório de saída: Relatório → Salvar\n\n"
        "Após a execução, faça o upload do arquivo de resultados usando o ícone 📊."
    ),
    FlowchartStep.RESULTS_UPLOAD: (
        "Aguardando o upload do arquivo de resultados. Use o ícone 📊 na barra de entrada."
    ),
    FlowchartStep.ANALYSIS: (
        "Analisando os resultados da simulação..."
    ),
    FlowchartStep.DONE: (
        "Estudo concluído. Posso ajudá-lo a interpretar os resultados ou iniciar um novo estudo."
    ),
}


class AnaradeGuide:
    """Tracks the user's position in the Anarede study flowchart."""

    def __init__(self):
        self.current_step = FlowchartStep.OBJECTIVE
        self.completed_steps: list = []

    def get_current_prompt(self) -> str:
        return STEP_PROMPTS.get(self.current_step, "")

    def advance(self, to_step: Optional[FlowchartStep] = None):
        """Move to the next step or a specific step."""
        self.completed_steps.append(self.current_step)
        if to_step:
            self.current_step = to_step
        else:
            steps = list(FlowchartStep)
            idx = steps.index(self.current_step)
            if idx + 1 < len(steps):
                self.current_step = steps[idx + 1]

    def reset(self):
        self.current_step = FlowchartStep.OBJECTIVE
        self.completed_steps = []

    def progress_summary(self) -> str:
        completed = [s.value for s in self.completed_steps]
        return f"Steps completed: {', '.join(completed) if completed else 'none'} | Current: {self.current_step.value}"
