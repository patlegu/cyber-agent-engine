# SPDX-License-Identifier: AGPL-3.0-or-later
import requests
import json
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class OllamaClient:
    """Client pour interagir avec l'API Ollama locale."""
    
    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url.rstrip('/')
        
    def generate(self, model: str, prompt: str, options: Optional[Dict] = None) -> Dict:
        """
        Génère une réponse via l'API /api/generate.
        
        Args:
            model: Nom du modèle (ex: "wireguard-lora:v1")
            prompt: Le prompt complet
            options: Options de génération (temperature, etc.)
            
        Returns:
            La réponse JSON complète
        """
        url = f"{self.base_url}/api/generate"
        
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            **(options or {})
        }
        
        try:
            response = requests.post(url, json=payload)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Erreur Ollama API: {e}")
            raise

    def chat(self, model: str, messages: list, options: Optional[Dict] = None) -> Dict:
        """
        Génère une réponse via l'API /api/chat.
        
        Args:
            model: Nom du modèle
            messages: Liste de messages [{"role": "user", "content": "..."}]
            options: Options de génération
            
        Returns:
            La réponse JSON complète
        """
        url = f"{self.base_url}/api/chat"
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            **(options or {})
        }
        
        try:
            response = requests.post(url, json=payload)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Erreur Ollama API (chat): {e}")
            raise
