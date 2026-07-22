"""
Classe de base pour les agents-outils.

Un agent-outil est spécialisé pour UN SEUL outil (firewall, IDPS, etc.)
et utilise un LoRA dédié pour décider quelle fonction appeler.
"""

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import json
import os

from .errors import ErrorCode
from clients.tool_call_schema import TOOL_CALL_SCHEMA

logger = logging.getLogger(__name__)


class NoInferenceBackend(RuntimeError):
    """Aucun backend d'inférence NL configuré pour cet agent (execute_direct reste dispo)."""


@dataclass
class FunctionCall:
    """Représente un appel de fonction décidé par le LoRA."""
    function: str
    args: Dict[str, Any]
    confidence: float = 1.0
    reasoning: str = ""
    raw_output: str = ""


@dataclass
class ToolResult:
    """Résultat de l'exécution d'une fonction sur l'outil."""
    success: bool
    function: str
    args: Dict[str, Any]
    result: Any
    error: Optional[str] = None
    error_code: Optional[ErrorCode] = None
    tool_name: str = ""
    reasoning: str = ""
    execution_time_ms: float = 0.0


class ToolAgent(ABC):
    """
    Classe de base pour les agents-outils.

    Un agent-outil est spécialisé pour UN SEUL outil (firewall, IDPS, etc.)
    et utilise un LoRA dédié pour décider quelle fonction appeler.

    Principes:
    - Un LoRA par outil (pas de routage multi-outils)
    - Pas de raisonnement complexe (juste mapping requête → fonction)
    - Exécution directe sur l'API de l'outil
    - Métriques strictes (FNR < 3%, Accuracy > 95%)
    """

    # Sous-classes peuvent surcharger ces attributs de classe pour personnaliser
    # le prompt système envoyé au LoRA.
    #
    # agent_role   : description courte du rôle de l'agent (ex: "OPNsense firewall agent")
    #                Utilisée dans le system prompt de _infer_with_vllm() si system_prompt est vide.
    # system_prompt: prompt système complet utilisé à l'inférence vLLM.
    #                Doit correspondre exactement au prompt système du dataset d'entraînement.
    #                Si vide (""), _infer_with_vllm() construit un prompt générique à partir de agent_role.
    # chat_format  : format du template de conversation.
    #                "phi3" → <|system|>…<|end|><|user|>…<|end|><|assistant|>
    #                "qwen" → <|im_start|>system…<|im_end|><|im_start|>user…<|im_end|><|im_start|>assistant\n
    agent_role:    str = "tool agent"
    system_prompt: str = ""
    chat_format:   str = "phi3"

    def __init__(  # noqa: PLR0913 -- 5 backends d'inférence enfichables
        self,
        tool_name: str,
        model_path: str,
        api_config: Optional[Dict] = None,
        ollama_config: Optional[Dict] = None,
        vllm_client: Any = None,
        openai_client: Any = None,
        lora_model: str = "",
    ):
        """
        Initialise l'agent-outil.

        Args:
            tool_name: Nom de l'outil (ex: "stormshield", "opnsense")
            model_path: Chemin vers le LoRA adapté à cet outil (local)
            api_config: Configuration API de l'outil (optionnel)
            ollama_config: Config Ollama override {"model": "...", "url": "..."}
            openai_client: Client HTTP OpenAI-compatible (OpenAICompatClient) pour
                servir le LoRA via un endpoint /chat/completions (ex: vLLM multi-LoRA)
            lora_model: Nom du LoRA à passer comme `model` à openai_client
        """
        self.tool_name = tool_name
        self.model_path = model_path
        self.api_config = api_config or {}
        self.ollama_config = ollama_config
        self.vllm_client = vllm_client
        self.openai_client = openai_client
        self.lora_model = lora_model

        # Client Ollama (lazy init)
        self.ollama_client = None
        if self.ollama_config and self.ollama_config.get('model'):
            from clients.ollama_client import OllamaClient
            self.ollama_client = OllamaClient(
                base_url=self.ollama_config.get('url', 'http://localhost:11434')
            )
        
        # Enregistrer les fonctions disponibles
        self._functions = self._register_functions()

        # Cache de résolution des noms de fonctions (fuzzy matching)
        # func_name_lower -> (resolved_name, confidence) | None si inconnu
        self._function_resolution_cache: Dict[str, Optional[tuple]] = {}

        # Charger le modèle LoRA si disponible
        self.model = None
        self.tokenizer = None
        self._load_model()
        
        logger.info(
            f"Agent {tool_name} initialisé avec {len(self._functions)} fonctions"
        )

    @abstractmethod
    def _register_functions(self) -> Dict[str, callable]:
        """
        Enregistre les fonctions disponibles pour cet outil.

        Returns:
            Dict mapping nom_fonction → callable
        """
        pass

    def get_available_functions(self) -> List[str]:
        """Retourne la liste des fonctions disponibles."""
        return list(self._functions.keys())

    def _classify_exception(self, e: Exception) -> ErrorCode:
        """Classifie une exception en ErrorCode pour le coordinateur."""
        msg = str(e).lower()
        if any(w in msg for w in ["timeout", "connect", "unreachable", "refused", "network", "nodename"]):
            return ErrorCode.API_UNREACHABLE
        if any(w in msg for w in ["401", "403", "unauthorized", "forbidden", "permission"]):
            return ErrorCode.PERMISSION_DENIED
        return ErrorCode.EXECUTION_ERROR

    def get_capabilities(self) -> List[Dict]:
        """
        Retourne les specs OpenAI function-calling de toutes les fonctions.

        Déduplique les alias (même callable → un seul schéma avec `aliases`).
        Extrait les enums depuis les annotations Literal[...] et les descriptions
        de paramètres depuis les lignes ':param name: ...' du docstring.
        Utilisé par GET /capabilities pour la découverte par le coordinateur.
        """
        import inspect
        import re
        import typing

        def _get_literal_values(ann) -> List[str]:
            """Extrait les valeurs d'un Literal[...] si applicable."""
            origin = getattr(ann, "__origin__", None)
            if origin is typing.Literal:
                return [str(v) for v in ann.__args__]
            return []

        def _parse_param_docs(docstring: str) -> Dict[str, str]:
            """Extrait les descriptions ':param name: ...' du docstring."""
            docs: Dict[str, str] = {}
            if not docstring:
                return docs
            for m in re.finditer(r":param (\w+):\s*(.+?)(?=\n\s*:|$)", docstring, re.DOTALL):
                docs[m.group(1)] = " ".join(m.group(2).split())
            return docs

        result: List[Dict] = []
        seen_callables: Dict[int, int] = {}  # id(callable) → index dans result

        for func_name, func in self._functions.items():
            # Unwrap les décorateurs (@safety_snapshot, @functools.wraps)
            underlying = func
            for attr in ("__wrapped__", "__func__"):
                if hasattr(underlying, attr):
                    underlying = getattr(underlying, attr)

            uid = id(underlying)
            if uid in seen_callables:
                result[seen_callables[uid]]["aliases"].append(func_name)
                continue

            docstring = inspect.getdoc(func) or f"Fonction {func_name}"
            description = docstring.split('\n')[0].strip()
            param_docs = _parse_param_docs(docstring)

            try:
                sig = inspect.signature(func)
            except (ValueError, TypeError):
                sig = None

            properties: Dict = {}
            required: List[str] = []

            if sig:
                for param_name, param in sig.parameters.items():
                    if param_name in ('self', 'kwargs', 'args'):
                        continue
                    if param.kind in (inspect.Parameter.VAR_KEYWORD, inspect.Parameter.VAR_POSITIONAL):
                        continue

                    ann = param.annotation
                    literal_vals = _get_literal_values(ann)

                    ptype = "string"
                    if not literal_vals:
                        if ann == int:
                            ptype = "integer"
                        elif ann == bool:
                            ptype = "boolean"
                        elif ann in (list, List):
                            ptype = "array"
                        elif ann in (dict, Dict):
                            ptype = "object"

                    prop: Dict = {"type": ptype}
                    if literal_vals:
                        prop["enum"] = literal_vals
                    if param_name in param_docs:
                        prop["description"] = param_docs[param_name]

                    properties[param_name] = prop

                    if param.default == inspect.Parameter.empty:
                        required.append(param_name)

            schema = {
                "name": func_name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
                "aliases": [],
            }
            seen_callables[uid] = len(result)
            result.append(schema)

        return result

    async def _call_function(self, function_call: "FunctionCall", start_time: float) -> "ToolResult":
        """
        Valide et exécute un FunctionCall déjà résolu (fonction + args).

        Mutualisé entre execute() (mode naturel) et execute_direct() (mode structuré).
        Effectue : vérification d'existence, sanitisation des args, détection de
        placeholders, puis appel réel de la fonction.
        """
        import inspect
        import re as _re
        import time as _time

        # 1. Valider que la fonction existe
        if function_call.function not in self._functions:
                return ToolResult(
                    success=False,
                    function=function_call.function,
                    args=function_call.args,
                    result=None,
                    error=f"Fonction inconnue: {function_call.function}",
                    error_code=ErrorCode.FUNCTION_UNKNOWN,
                    tool_name=self.tool_name,
                    execution_time_ms=(time.time() - start_time) * 1000
                )

            # 2. Exécuter la fonction
        func = self._functions[function_call.function]

        # Sanitisation des arguments
        sig = inspect.signature(func)
        sanitized_args = {}
        missing_mandatory = []

        for param_name, param in sig.parameters.items():
            if param_name == 'self':
                continue
            if param_name in function_call.args:
                sanitized_args[param_name] = function_call.args[param_name]
            elif param.default == inspect.Parameter.empty and param.kind not in [
                inspect.Parameter.VAR_KEYWORD, inspect.Parameter.VAR_POSITIONAL
            ]:
                missing_mandatory.append(param_name)

        if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
            for k, v in function_call.args.items():
                if k not in sanitized_args:
                    sanitized_args[k] = v

        if missing_mandatory:
            err_msg = f"Missing mandatory argument(s) for {function_call.function}: {', '.join(missing_mandatory)}"
            logger.error(err_msg)
            return ToolResult(
                success=False,
                function=function_call.function,
                args=function_call.args,
                result=None,
                error=err_msg,
                error_code=ErrorCode.MISSING_ARG,
                tool_name=self.tool_name,
                reasoning=function_call.reasoning,
                execution_time_ms=(_time.time() - start_time) * 1000
            )

        # Rejeter les placeholders LLM comme <UUID_de_la_règle> ou [some-id]
        _PLACEHOLDER_RE = _re.compile(r'^[<\[].+[>\]]$')
        placeholder_args = [
            k for k, v in sanitized_args.items()
            if isinstance(v, str) and _PLACEHOLDER_RE.match(v.strip())
        ]
        if placeholder_args:
            err_msg = (
                f"Placeholder value(s) detected for {function_call.function}: "
                + ", ".join(f"{k}={sanitized_args[k]!r}" for k in placeholder_args)
                + ". Fetch the real identifier first (e.g. list the resources), then retry with the actual value."
            )
            logger.error(err_msg)
            return ToolResult(
                success=False,
                function=function_call.function,
                args=function_call.args,
                result=None,
                error=err_msg,
                error_code=ErrorCode.MISSING_ARG,
                tool_name=self.tool_name,
                reasoning=function_call.reasoning,
                execution_time_ms=(_time.time() - start_time) * 1000
            )

        result = await func(**sanitized_args)

        return ToolResult(
            success=True,
            function=function_call.function,
            args=sanitized_args,
            result=result,
            tool_name=self.tool_name,
            reasoning=function_call.reasoning,
            execution_time_ms=(_time.time() - start_time) * 1000
        )

    async def execute(self, user_request: str) -> ToolResult:
        """
        Exécute une requête en langage naturel.

        Le vLLM / LoRA interprète la commande et décide quelle fonction appeler.
        Pour bypasser l'inférence LLM, utiliser execute_direct().

        Args:
            user_request: Requête en langage naturel

        Returns:
            Résultat de l'exécution
        """
        import time
        start_time = time.time()

        try:
            function_call = await self._infer_function(user_request)
            return await self._call_function(function_call, start_time)

        except Exception as e:
            logger.error(f"Erreur lors de l'exécution: {e}")
            return ToolResult(
                success=False,
                function="unknown",
                args={},
                result=None,
                error=str(e),
                error_code=self._classify_exception(e),
                tool_name=self.tool_name,
                execution_time_ms=(time.time() - start_time) * 1000
            )

    async def execute_direct(self, function: str, args: Dict[str, Any]) -> ToolResult:
        """
        Exécute directement une fonction par son nom et ses arguments.

        Bypass complet du LLM — aucune inférence. Utilisé par le coordinateur
        quand la fonction et ses arguments sont déjà connus (ex : après reformulation
        structurée ou résolution d'UUID depuis des résultats de tâches précédentes).

        Args:
            function: Nom exact de la fonction (ex: "delete_filter_rule")
            args:     Arguments de la fonction (ex: {"uuid": "f9ed38a8-..."})

        Returns:
            ToolResult (même format que execute())
        """
        import time

        from .coercion import CoercionError, coerce_args
        start_time = time.time()
        func = self._functions.get(function)
        if func is not None:
            try:
                args = coerce_args(func, args)
            except CoercionError as exc:
                return ToolResult(
                    success=False,
                    function=function,
                    args=args,
                    result=None,
                    error=str(exc),
                    error_code=ErrorCode.MISSING_ARG,
                    tool_name=self.tool_name,
                    execution_time_ms=(time.time() - start_time) * 1000,
                )
        function_call = FunctionCall(
            function=function,
            args=args,
            confidence=1.0,
            reasoning="[direct call — no LLM inference]",
        )
        try:
            return await self._call_function(function_call, start_time)
        except Exception as e:
            import time as _t
            logger.error(f"Erreur execute_direct({function}): {e}")
            return ToolResult(
                success=False,
                function=function,
                args=args,
                result=None,
                error=str(e),
                error_code=self._classify_exception(e),
                tool_name=self.tool_name,
                execution_time_ms=(_t.time() - start_time) * 1000
            )

    def _load_model(self):
        """
        Charge le modèle LoRA si disponible.
        
        Si le modèle n'est pas disponible, l'agent fonctionnera en mode simulation.
        """
        # Si mode Ollama activé, on ne charge pas de modèle local
        if self.ollama_client:
            logger.info(f"Mode Ollama activé (modèle: {self.ollama_config['model']})")
            return

        # Vérifier si le chemin du modèle est fourni et existe
        if self.model_path is None or not os.path.exists(self.model_path):
            if self.model_path is None:
                # Mode Tools-Only (pas d'erreur, juste informatif)
                logger.info("ℹ️ Agent initialisé en mode 'Tools-Only' (pas de modèle LoRA local)")
            else:
                logger.warning(f"⚠️ Modèle LoRA non trouvé au chemin spécifié: {self.model_path}")
            
            # Message informatif sur l'inférence
            if self.ollama_client:
                logger.info(f"✅ Inférence déportée active via Ollama")
            else:
                logger.info("ℹ️ Inférence locale désactivée (mode simulation pour les requêtes NL)")
            return
        
        try:
            # Essayer d'importer unsloth
            from unsloth import FastLanguageModel
            
            logger.info(f"Chargement du modèle LoRA depuis {self.model_path}...")
            
            # Charger le modèle avec unsloth
            self.model, self.tokenizer = FastLanguageModel.from_pretrained(
                model_name=self.model_path,
                max_seq_length=2048,
                dtype=None,  # Auto-détection
                load_in_4bit=True,  # Quantification pour économiser la mémoire
            )
            
            # Passer en mode inférence (plus rapide)
            FastLanguageModel.for_inference(self.model)
            
            logger.info("✓ Modèle LoRA chargé avec succès")
            
        except ImportError:
            logger.info("ℹ️ Unsloth n'est pas installé (utilisé pour l'inférence LoRA locale)")
        except Exception as e:
            logger.error(f"❌ Erreur lors du chargement du modèle LoRA: {e}")
            logger.error(f"❌ Erreur lors du chargement du modèle LoRA: {e}")
            logger.info("ℹ️ Fallback sur le mode simulation pour l'inférence")

    async def _infer_with_vllm(self, user_request: str) -> FunctionCall:
        """Inférence via Native vLLM Client (Multi-LoRA)."""
        try:
            # 1. Construire le prompt selon le format déclaré par l'agent.
            # system_prompt de la classe doit correspondre exactement au prompt
            # utilisé dans le dataset d'entraînement. Si vide, on construit un
            # prompt générique (moins optimal, mais fonctionnel en fallback).
            if self.system_prompt:
                system_content = self.system_prompt
            else:
                functions_list = ', '.join(self._functions.keys())
                system_content = (
                    f"You are a {self.agent_role}.\n\n"
                    "STRICT INSTRUCTIONS:\n"
                    "1. YOU MUST FIRST provide your reasoning inside <thought>...</thought> tags.\n"
                    "2. THEN provide the JSON tool call list.\n"
                    "3. Use the same language as the user for reasoning.\n"
                    "4. DO NOT write anything else.\n\n"
                    f"Valid functions: {functions_list}"
                )

            if self.chat_format == "qwen":
                formatted_prompt = (
                    f"<|im_start|>system\n{system_content}<|im_end|>\n"
                    f"<|im_start|>user\n{user_request}<|im_end|>\n"
                    "<|im_start|>assistant\n"
                )
            else:  # phi3 (défaut)
                formatted_prompt = (
                    f"<|system|>\n{system_content}\n<|end|>\n"
                    f"<|user|>\n{user_request}\n<|end|>\n"
                    "<|assistant|>\n"
                )
            
            # 2. Appel au client partagé
            # On passe le nom de l'outil comme nom d'adapter (ex: "wireguard", "opnsense")
            # IMPORTANT: vLLM.generate est bloquant, on doit le décharger dans un thread
            loop = asyncio.get_running_loop()
            generated_text = await loop.run_in_executor(
                None,
                lambda: self.vllm_client.complete(
                    formatted_prompt,
                    adapter_name=self.tool_name,
                    json_schema=TOOL_CALL_SCHEMA,
                )
            )
            
            logger.info(f"vLLM output ({self.tool_name}): {generated_text[:100]}...")
            
            # 3. Parsing
            return self._parse_model_output(generated_text, user_request)

        except Exception as e:
            logger.error(f"Erreur inférence vLLM: {e}")
            return await self._infer_with_simulation(user_request)

    async def _infer_with_openai_compat(self, user_request: str) -> "FunctionCall":
        """Inférence NL via un endpoint OpenAI-compatible servant le LoRA de l'outil."""
        messages = self._build_chat_messages(user_request)
        content = await self.openai_client.chat(messages, model=self.lora_model)
        return self._parse_model_output(content, user_request)

    async def _infer_function(self, user_request: str) -> FunctionCall:
        """
        Utilise le LoRA pour inférer quelle fonction appeler.

        Ordre de sélection du backend (le premier configuré gagne) :
        openai_client → ollama_client → vllm_client → model local (unsloth).
        Si aucun backend n'est configuré, échoue fermé (NoInferenceBackend) —
        le chemin structuré execute_direct() reste disponible sans modèle.

        Args:
            user_request: Requête utilisateur

        Returns:
            FunctionCall avec la fonction et les arguments
        """
        # Si un endpoint OpenAI-compatible est configuré (Priorité absolue)
        if self.openai_client:
            return await self._infer_with_openai_compat(user_request)

        # Si client Ollama configuré
        if self.ollama_client:
            return await self._infer_with_ollama(user_request)

        # Si vLLM client est disponible
        if self.vllm_client:
            return await self._infer_with_vllm(user_request)

        # Si le modèle est chargé (Unsloth), utiliser l'inférence LoRA locale
        if self.model is not None and self.tokenizer is not None:
            return await self._infer_with_lora(user_request)

        # Sinon, échouer fermé : pas de simulation silencieuse pour le chemin NL
        raise NoInferenceBackend(
            "Aucun backend d'inférence configuré (AGENT_INFER_BASE_URL/ollama/[gpu]). "
            "Le chemin structuré execute_direct reste disponible sans modèle."
        )

    async def _infer_with_lora(self, user_request: str) -> FunctionCall:
        """
        Inférence avec le modèle LoRA.
        
        Args:
            user_request: Requête utilisateur
            
        Returns:
            FunctionCall avec la fonction et les arguments
        """
        try:
            # Construire le prompt au format du dataset d'entraînement
            prompt = self._build_inference_prompt(user_request)
            
            # Tokenizer
            inputs = self.tokenizer(
                prompt,
                return_tensors="pt",
                truncation=True,
                max_length=2048
            )
            
            # Déplacer sur le bon device
            inputs = {k: v.to(self.model.device) for k, v in inputs.items()}
            
            # Générer la réponse avec constrained decoding
            # On force le modèle à utiliser les noms de fonctions valides
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=256,
                temperature=0.1,
                do_sample=True,
                top_p=0.9,
                pad_token_id=self.tokenizer.eos_token_id,
                repetition_penalty=1.1  # Éviter les répétitions
            )
            
            # Décoder la sortie (uniquement les nouveaux tokens)
            input_length = inputs["input_ids"].shape[-1]
            generated_tokens = outputs[0][input_length:]
            generated_text = self.tokenizer.decode(generated_tokens, skip_special_tokens=True)
            print(f"DEBUG - Generated Text: {generated_text}")
            
            # Parser la sortie pour extraire la fonction et les arguments
            function_call = self._parse_model_output(generated_text, user_request)
            
            logger.info(f"LoRA inférence: {function_call.function} (confidence: {function_call.confidence:.2f})")
            
            return function_call
            
        except Exception as e:
            logger.error(f"Erreur lors de l'inférence LoRA: {e}")
            logger.warning("Fallback sur la simulation")
            return await self._infer_with_simulation(user_request)

    async def _infer_with_ollama(self, user_request: str) -> FunctionCall:
        """Inférence via Ollama API."""
        try:
            # On utilise le même prompt builder, mais on récupère le string
            # Le prompt builder actuel utilise self.tokenizer... 
            # Il faut adapter _build_inference_prompt pour qu'il n'ait pas besoin de tokenizer si Ollama
            
            # Pour Ollama, on peut passer les messages directement au format chat
            messages = self._build_chat_messages(user_request)
            
            model_name = self.ollama_config['model']
            logger.info(f"Appel Ollama ({model_name})...")
            
            response = self.ollama_client.chat(
                model=model_name,
                messages=messages,
                options={
                    "temperature": 0.1,
                    "top_p": 0.9
                }
            )
            
            content = response.get('message', {}).get('content', '')
            logger.info(f"Réponse Ollama: {content[:100]}...")
            
            return self._parse_model_output(content, user_request)
            
        except Exception as e:
            logger.error(f"Erreur inférence Ollama: {e}")
            return await self._infer_with_simulation(user_request)

    def _build_chat_messages(self, user_request: str) -> List[Dict]:
        """Construit les messages pour le chat Ollama."""
        # Récupérer la liste des fonctions
        functions_list = sorted(self._functions.keys())
        
        system_prompt = """You are an OPNsense firewall agent.

CRITICAL RULES:
1. YOU MUST ALWAYS start your response with <thought> explaining your analysis </thought>.
2. Use the same language as the user for reasoning.
3. AFTER the thought block, provide exactly one JSON list of tool calls.
4. Function names must be EXACTLY as defined below.
5. No other text or explanations allowed.

Valid function names: {}""".format(', '.join(functions_list))

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_request}
        ]

    
    def _build_inference_prompt(self, user_request: str) -> str:
        """
        Construit le prompt pour l'inférence.
        
        Format similaire au dataset d'entraînement (OpenAI function calling).
        """
        import inspect
        
        # Construire la liste des fonctions disponibles au format OpenAI
        functions_list = []
        for func_name, func in self._functions.items():
            # Extraire la description
            docstring = inspect.getdoc(func) or f"Fonction {func_name}"
            description = docstring.split('\n')[0].strip()
            
            # Extraire les paramètres
            sig = inspect.signature(func)
            parameters = {}
            required = []
            
            for param_name, param in sig.parameters.items():
                if param_name == 'self':
                    continue
                
                # Type du paramètre (simplifié)
                param_type = "string"
                if param.annotation != inspect.Parameter.empty:
                    if param.annotation == int:
                        param_type = "integer"
                    elif param.annotation == bool:
                        param_type = "boolean"
                    elif param.annotation in [list, List]:
                        param_type = "array"
                    elif param.annotation in [dict, Dict]:
                        param_type = "object"
                
                parameters[param_name] = {
                    "type": param_type,
                    "description": f"Paramètre {param_name}"
                }
                
                if param.default == inspect.Parameter.empty:
                    required.append(param_name)
            
            func_schema = {
                "name": func_name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": parameters,
                    "required": required
                }
            }
            functions_list.append(func_schema)
        
        # Créer le prompt au MÊME FORMAT que le dataset d'entraînement
        # Format OpenAI function calling avec messages
        # STRICT A2A PROTOCOL: English only, no translation, function names must be exact
        messages = [
            {
                "role": "system",
                "content": """You are an OPNsense firewall agent.

STRICT PROTOCOL:
1. START with <thought> reasoning </thought> in the user's language.
2. FOLLOW with a JSON list of tool calls.
3. Use ONLY the functions listed below for the '{}' tool.
4. If no function matches, return [].

Valid function names: {}""".format(self.tool_name, ', '.join(sorted(self._functions.keys())))
            },
            {
                "role": "user",
                "content": user_request
            }
        ]
        
        # Utiliser apply_chat_template comme pendant l'entraînement
        prompt = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True
        )
        
        return prompt
    
    
    def _parse_model_output(self, generated_text: str, user_request: str) -> FunctionCall:
        """
        Parse la sortie du modèle pour extraire la fonction et les arguments.
        
        Le modèle génère une liste de tool calls au format JSON.
        Exemple: [{"name": "func", "arguments": "{\"arg\": \"val\"}"}]
        """
        import json
        import re
        
        raw_text = generated_text.strip()
        
        # 0. Extract reasoning
        reasoning = ""
        # 0a. Standard tag search
        thought_match = re.search(r'<thought>([\s\S]*?)</thought>', raw_text)
        if thought_match:
            reasoning = thought_match.group(1).strip()
        # 0b. Primed output search (start of text up to closing tag)
        elif "</thought>" in raw_text:
            reasoning = raw_text.split("</thought>")[0].strip()
        # 0c. Fallback for text before JSON or special tags
        elif not raw_text.strip().startswith("[") and not raw_text.strip().startswith("<|tool_calls|>"):
            # Text before first [ or <|tool_calls|> or <details>
            delimiter = None
            for d in ["<|tool_calls|>", "[", "{", "<details>"]:
                if d in raw_text:
                    if delimiter is None or raw_text.find(d) < raw_text.find(delimiter):
                        delimiter = d
            if delimiter:
                reasoning = raw_text.split(delimiter)[0].strip()
        
        # 0d. French / English explicit markers (Pensée:, Reasoning:)
        if not reasoning or reasoning.lower() == "none":
            marker_reasoning = ""
            markers = [r'Pensée\s*:', r'Reasoning\s*:', r'Analysis\s*:']
            for marker in markers:
                m = re.search(marker + r'([\s\S]*?)(?:\[|\{|<|tool_calls|$)', raw_text, re.IGNORECASE)
                if m:
                    marker_reasoning = m.group(1).strip()
                    break
            if marker_reasoning:
                reasoning = marker_reasoning
        
        # 1. Nettoyage des tags connus pour isoler le JSON
        clean_text = raw_text
        tags_to_remove = [
            '[TOOL_CALLS]', '<|tool_calls|>', '</|tool_calls|>', 
            '<|tool_response|>', '</|tool_response|>', 
            '<thought>', '</thought>', '<details>', '</details>'
        ]
        for tag in tags_to_remove:
            clean_text = clean_text.replace(tag, '')
        
        # S'assurer que reasoning ne contient pas "None"
        if reasoning.lower() == "none":
            reasoning = ""
        
        clean_text = clean_text.strip()
        
        try:
            # 2. Recherche de blocs JSON (liste ou objet) par regex (plus robuste que find/rfind)
            # On cherche tout ce qui ressemble à un JSON
            potential_blocks = re.findall(r'(\[[\s\S]*\]|\{[\s\S]*\})', clean_text)
            
            json_data = None
            for block in potential_blocks:
                try:
                    # Tenter de parser le bloc
                    # On nettoie d'éventuels backticks markdown
                    block = block.strip()
                    if block.startswith('```json'): block = block[7:]
                    if block.startswith('```'): block = block[3:]
                    if block.endswith('```'): block = block[:-3]
                    
                    data = json.loads(block.strip())
                    if data:
                        json_data = data
                        break # On prend le premier valide
                except:
                    continue
            # 3. Analyser les données JSON
            # Gérer le cas où le modèle retourne explicitement une liste vide []
            if clean_text.strip() == '[]':
                logger.info("Modèle a retourné une liste vide, interprété comme 'unknown'.")
                return FunctionCall(function="unknown", args={}, confidence=0.0, reasoning=reasoning, raw_output=raw_text)

            if json_data:
                # Normaliser en liste
                if isinstance(json_data, dict):
                    json_data = [json_data]
                    
                if isinstance(json_data, list) and len(json_data) > 0:
                    tool_call = json_data[0]
                    
                    # Gérer format OpenAI imbriqué: {"type": "function", "function": {...}}
                    if "function" in tool_call and isinstance(tool_call["function"], dict):
                        tool_call = tool_call["function"]
                    
                    # Store reasoning if found inside the tool call itself (rare but possible)
                    if "reasoning" in tool_call and not reasoning:
                        reasoning = tool_call["reasoning"]
                    
                    func_name = tool_call.get("name") or tool_call.get("action")
                    args = tool_call.get("arguments") or tool_call.get("args") or {}
                    
                    # Si les arguments sont une chaîne JSON, on parse
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except:
                            pass
                    
                    if not func_name:
                        # Fallback si pas de champ 'name' direct
                        # Peut-être que 'tool_call' est juste le nom si c'est un format bizarre
                        if isinstance(tool_call, str):
                            func_name = tool_call
                    
                    if func_name:
                        # Vérifier si le nom est valide, sinon faire du fuzzy matching
                        if func_name in self._functions:
                            logger.info(f"Fonction identifiée: {func_name}")
                            return FunctionCall(
                                function=func_name,
                                args=args if isinstance(args, dict) else {},
                                confidence=0.9,
                                reasoning=reasoning,
                                raw_output=raw_text
                            )
                        else:
                            # Fuzzy matching with cache
                            from difflib import SequenceMatcher

                            func_name_lower = func_name.lower()
                            cache_key = func_name_lower

                            # Check cache first
                            if cache_key in self._function_resolution_cache:
                                cached = self._function_resolution_cache[cache_key]
                                if cached is not None:
                                    resolved_name, conf = cached
                                    logger.info(f"Cache hit: {func_name} -> {resolved_name}")
                                    return FunctionCall(
                                        function=resolved_name,
                                        args=args if isinstance(args, dict) else {},
                                        confidence=conf,
                                        reasoning=reasoning,
                                        raw_output=raw_text
                                    )
                                # None in cache means previously unresolved → skip fuzzy
                            else:
                                logger.warning(f"Fonction inconnue: {func_name}, tentative de fuzzy matching...")

                                # Case-insensitive exact match check first
                                for valid_name in self._functions.keys():
                                    if valid_name.lower() == func_name_lower:
                                        logger.info(f"Case-insensitive match: {func_name} -> {valid_name}")
                                        self._function_resolution_cache[cache_key] = (valid_name, 0.85)
                                        return FunctionCall(
                                            function=valid_name,
                                            args=args if isinstance(args, dict) else {},
                                            confidence=0.85,
                                            reasoning=reasoning,
                                            raw_output=raw_text
                                        )

                                best_match = None
                                best_score = 0

                                ADD_VERBS = {'add', 'create', 'new', 'start', 'enable', 'toggle', 'block', 'insert', 'generate', 'setup', 'install'}
                                DEL_VERBS = {'delete', 'remove', 'stop', 'disable', 'kill', 'unblock', 'cancel', 'drop', 'uninstall', 'purge'}
                                READ_VERBS = {'get', 'list', 'show', 'check', 'find', 'search', 'status', 'view', 'read'}

                                def get_verb_cat(name):
                                    name = name.lower()
                                    if any(name.startswith(v) for v in ADD_VERBS): return 'add'
                                    if any(name.startswith(v) for v in DEL_VERBS): return 'del'
                                    if any(name.startswith(v) for v in READ_VERBS): return 'read'
                                    return None

                                h_verb_cat = get_verb_cat(func_name_lower)

                                for valid_name in self._functions.keys():
                                    score = SequenceMatcher(None, func_name_lower, valid_name.lower()).ratio()
                                    if func_name_lower in valid_name.lower() or valid_name.lower() in func_name_lower:
                                        score += 0.2
                                    v_verb_cat = get_verb_cat(valid_name)
                                    if h_verb_cat and v_verb_cat and h_verb_cat != v_verb_cat:
                                        score -= 0.8
                                    if score > best_score:
                                        best_score = score
                                        best_match = valid_name

                                if best_match and best_score > 0.7:
                                    conf = 0.7 * min(1.0, best_score)
                                    self._function_resolution_cache[cache_key] = (best_match, conf)
                                    logger.info(f"Fuzzy match: {func_name} -> {best_match} (score: {best_score:.2f})")
                                    return FunctionCall(
                                        function=best_match,
                                        args=args if isinstance(args, dict) else {},
                                        confidence=conf,
                                        reasoning=reasoning,
                                        raw_output=raw_text
                                    )
                                else:
                                    # Cache miss, unresolvable
                                    self._function_resolution_cache[cache_key] = None
        except Exception as e:
            logger.warning(f"Erreur lors du parsing tool call: {e}")
        
        # 4. Fallback: Simulation si échec du parsing
        logger.warning(f"Aucune fonction valide identifiée dans la réponse du modèle")
        return FunctionCall(
            function="unknown",
            args={},
            confidence=0.0,
            reasoning=reasoning,
            raw_output=raw_text
        )
    
    async def _infer_with_simulation(self, user_request: str) -> FunctionCall:
        """
        Simulation d'inférence (fallback).
        
        Args:
            user_request: Requête utilisateur
            
        Returns:
            FunctionCall
        """
        request_lower = user_request.lower()
        
        # Chercher une fonction de lecture (get_, list_) qui ne nécessite pas d'arguments obligatoires
        for func_name in self.get_available_functions():
            # Privilégier les fonctions de lecture
            if any(keyword in func_name for keyword in ['get_', 'list_']):
                # Vérifier si c'est une fonction sans arguments obligatoires
                func = self._functions.get(func_name)
                if func:
                    import inspect
                    sig = inspect.signature(func)
                    # Compter les paramètres obligatoires (sans valeur par défaut)
                    required_params = sum(
                        1 for p in sig.parameters.values()
                        if p.default == inspect.Parameter.empty and p.name != 'self'
                    )
                    
                    # Si pas de paramètres obligatoires, utiliser cette fonction
                    if required_params == 0:
                        logger.info(f"Simulation: utilisation de {func_name} (lecture sans arguments)")
                        return FunctionCall(
                            function=func_name,
                            args={},
                            confidence=0.5
                        )
        
        # Fallback : retourner une fonction "unknown" sûre
        return FunctionCall(
            function="unknown",
            args={},
            confidence=0.0
        )

    def get_tool_spec(self) -> Dict:
        """
        Retourne la spécification de l'outil pour le LoRA.
        
        Utilise l'introspection pour générer les schémas de paramètres.

        Returns:
            Spec au format OpenAI function calling
        """
        import inspect
        from typing import get_type_hints

        functions = []
        for name, func in self._functions.items():
            # Extraire la docstring
            doc = func.__doc__ or f"Fonction {name}"
            
            # Introspection des paramètres
            sig = inspect.signature(func)
            type_hints = get_type_hints(func)
            
            properties = {}
            required = []
            
            for param_name, param in sig.parameters.items():
                if param_name == 'self':
                    continue
                
                # Déterminer le type
                param_type = type_hints.get(param_name, str)
                type_str = "string"
                if param_type == int:
                    type_str = "integer"
                elif param_type == bool:
                    type_str = "boolean"
                elif param_type == float:
                    type_str = "number"
                elif param_type == dict or getattr(param_type, "__origin__", None) == dict:
                    type_str = "object"
                elif param_type == list or getattr(param_type, "__origin__", None) == list:
                    type_str = "array"
                
                prop = {
                    "type": type_str,
                    "description": f"Paramètre {param_name}"
                }
                
                # Valeur par défaut
                if param.default != inspect.Parameter.empty:
                    prop["default"] = param.default
                else:
                    required.append(param_name)
                    
                properties[param_name] = prop

            functions.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": doc.strip().split("\n")[0], # Utiliser la première ligne comme résumé
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required
                    }
                }
            })
        
        return {
            "tool_name": self.tool_name,
            "functions": functions
        }
