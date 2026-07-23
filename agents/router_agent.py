# SPDX-License-Identifier: AGPL-3.0-or-later
import logging
from typing import Dict, Any, Optional
from .opnsense_agent import OPNsenseAgent
from .wireguard_agent import WireGuardAgent

logger = logging.getLogger(__name__)

class RouterAgent:
    """
    Agent unifié qui route les instructions vers l'agent spécialisé approprié.
    Utilise les modèles Ollama pour éviter de charger plusieurs LoRA en mémoire.
    """
    
    def __init__(
        self,
        config: Dict[str, Any]
    ):
        """
    Agent routeur principal.
    
    Responsabilités:
    1. Classifier l'intention de l'utilisateur
    2. Router vers l'agent spécialisé approprié
    3. Agréger la réponse
    """
    
    def __init__(self, config: Dict):
        self.config = config
        self.api_config = config.get('api', {})
        self.ollama_config = config.get('ollama', {})
        
        # Initialisation des agents spécialisés
        self.opnsense_agent = OPNsenseAgent(
            model_path=self.ollama_config.get('opnsense_model', 'opnsense-lora:v7'),
            api_config=self.api_config,
            ollama_config={
                "model": self.ollama_config.get('opnsense_model', 'opnsense-lora:v7'),
                "url": self.ollama_config.get('url', 'http://localhost:11434')
            }
        )
        
        self.wireguard_agent = WireGuardAgent(
            model_path=self.ollama_config.get('wireguard_model', 'wireguard-lora:v1'),
            api_config=self.api_config,
            ollama_config={
                "model": self.ollama_config.get('wireguard_model', 'wireguard-lora:v1'),
                "url": self.ollama_config.get('url', 'http://localhost:11434')
            }
        )

        self.crowdsec_agent = CrowdSecAgent(
            model_path=self.ollama_config.get('crowdsec_model', 'crowdsec-lora:v1'),
            api_config=self.api_config,
            ollama_config={
                "model": self.ollama_config.get('crowdsec_model', 'crowdsec-lora:v1'),
                "url": self.ollama_config.get('url', 'http://localhost:11434')
            }
        )

    async def route_instruction(self, instruction: str) -> Dict:
        """Route l'instruction vers le bon agent."""
        intent = self._classify_intent(instruction)
        logger.info(f"Identified intent: {intent}")
        
        result = None
        tool_name = intent
        
        if intent == "wireguard":
            # WireGuard a une interface légèrement différente (run_instruction vs execute)
            # Todo: standardiser
            wg_result = await self.wireguard_agent.run_instruction(instruction)
            return self._format_result("wireguard", wg_result)
            
        elif intent == "crowdsec":
            result = await self.crowdsec_agent.execute(instruction)
            
        else: # opnsense (default)
            result = await self.opnsense_agent.execute(instruction)
            
        return {
            "status": "success" if result and result.success else "error",
            "result": result.result if result else None,
            "tool": tool_name,
            "function": result.function if result else None,
            "args": result.args if result else None
        }

    def _format_result(self, tool_name: str, result: Dict) -> Dict:
        """Formate le résultat standard."""
        return {
            "status": result.get("status", "unknown"),
            "result": result,
            "tool": tool_name
        }

    def _classify_intent(self, instruction: str) -> str:
        """
        Classifie l'intention basée sur des mots-clés.
        
        Amélioration future: utiliser un petit modèle de classification ou le LLM lui-même.
        """
        instr_lower = instruction.lower()
        
        # Mots-clés CrowdSec
        if any(kw in instr_lower for kw in ['crowdsec', 'ban ip', 'unban ip', 'decision', 'alert', 'cscli']):
            # Vérifier si c'est explicitement lié à OPNsense (ex: "block ip on firewall")
            # Mais "ban ip" est souvent CrowdSec. "Block ip" est souvent Firewall.
            if "crowdsec" in instr_lower:
                return "crowdsec"
            if "decision" in instr_lower or "alert" in instr_lower:
                return "crowdsec"
            # Ambiguïté "ban ip" / "block ip"
            if "ban" in instr_lower: # CrowdSec utilise "ban"
                return "crowdsec"
        
        # Mots-clés WireGuard
        return 'opnsense'
