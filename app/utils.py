"""
utils.py
Funções utilitárias usadas no pipeline (regras determinísticas).

Observação: o repositório foi reorganizado em backend/ e frontend/.
Este arquivo pertence ao repositório backend (app/).

Refatorado seguindo princípios SOLID:
- Single Responsibility: cada Rule tem uma responsabilidade única.
- Open/Closed: novas regras podem ser adicionadas criando subclasses de Rule sem
  modificar o RuleEngine.
- Dependency Inversion: o engine depende de abstrações (Rule), não de implementações concretas.
"""
from __future__ import annotations
from typing import List, Dict, Any
from abc import ABC, abstractmethod
from . import db

class Rule(ABC):
    """Interface (abstração) para uma regra que pode gerar alertas a partir de uma leitura."""

    @abstractmethod
    async def apply(self, reading: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Aplica a regra à leitura e retorna uma lista de alertas (pode ser vazia)."""
        pass


class ThresholdRule(Rule):
    """
    Regra de threshold genérica.
    Recebe um mapeamento de campo -> limite e nível/mensagem padrão.
    """

    def __init__(self, field: str, threshold: float, level: str, message: str):
        self.field = field
        self.threshold = threshold
        self.level = level
        self.message = message

    async def apply(self, reading: Dict[str, Any]) -> List[Dict[str, Any]]:
        val = reading.get(self.field)
        if val is None:
            return []
        try:
            # converte para float para comparação genérica
            v = float(val)
        except Exception:
            return []
        if v > self.threshold:
            return [{"level": self.level, "message": self.message, "value": v}]
        return []


class RuleEngine:
    """
    Motor de regras: coordena múltiplas regras e aplica-as a uma leitura.
    Segue o princípio de responsabilidade única: apenas orquestra execução das regras.
    """

    def __init__(self, rules: List[Rule]):
        self.rules = rules

    async def run(self, reading: Dict[str, Any]) -> List[Dict[str, Any]]:
        alerts: List[Dict[str, Any]] = []
        for rule in self.rules:
            res = await rule.apply(reading)
            if res:
                alerts.extend(res)
        return alerts


async def apply_threshold_rules(reading: dict) -> List[dict]:
    """
    Função compatível com o código existente. Busca as configurações do silo e
    constrói dinamicamente regras de threshold conforme settings.
    Mantém a assinatura anterior para compatibilidade.
    """
    alerts = []
    silo_id = reading.get("silo_id")
    if not silo_id:
        return alerts
    silo = await db.db.silos.find_one({"_id": silo_id})
    if not silo:
        return alerts
    settings = silo.get("settings", {})

    # Construir regras dinamicamente com base em settings.
    rules: List[Rule] = []

    # Exemplos: se existir um threshold no settings, cria uma ThresholdRule correspondente.
    temp_th = settings.get("temp_threshold")
    if temp_th is not None:
        rules.append(ThresholdRule(field="temp_C", threshold=temp_th, level="warning", message="Temperatura acima do limite"))

    co2_th = settings.get("co2_threshold")
    if co2_th is not None:
        rules.append(ThresholdRule(field="co2_ppm_est", threshold=co2_th, level="critical", message="CO2 acima do limite"))

    mq2_th = settings.get("mq2_threshold")
    if mq2_th is not None:
        rules.append(ThresholdRule(field="mq2_raw", threshold=mq2_th, level="warning", message="MQ2 alto"))

    # Aqui é simples: instanciamos o engine com as regras e executamos.
    engine = RuleEngine(rules=rules)
    alerts = await engine.run(reading)
    return alerts

# TODO: Para estender (ex.: regras de histerese, contagem de leituras consecutivas,
# tendências temporais), criar novas classes que implementem Rule e acrescentá-las
# na lista de 'rules' acima. Isso respeita OCP (aberto para extensão, fechado para modificação).
