# SPDX-License-Identifier: AGPL-3.0-or-later

import logging
import os
import time
import gc
import torch
from typing import Dict, List, Optional, Any
from pathlib import Path
from vllm import LLM, SamplingParams
from vllm.lora.request import LoRARequest
try:
    from vllm.sampling_params import StructuredOutputsParams
    _STRUCTURED_OUTPUT_AVAILABLE = True
except ImportError:
    _STRUCTURED_OUTPUT_AVAILABLE = False

from clients.tool_call_schema import TOOL_CALL_SCHEMA  # ré-export rétro-compatible

logger = logging.getLogger(__name__)

class NativeVLLMClient:
    """
    Client for native vLLM engine (Local Inference).
    Optimized for multi-LoRA switching on constrained VRAM (8GB).
    Requires 'bitsandbytes' quantization.
    """
    
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(NativeVLLMClient, cls).__new__(cls)
        return cls._instance

    def __init__(self, model_path: str, lora_adapters: Dict[str, str] = None, gpu_utilization: float = 0.8, max_model_len: int = 2048):
        """
        Initializes the vLLM engine.
        
        Args:
            model_path: Path/Name of the base model (e.g. unsloth/Phi-3...)
            lora_adapters: Dict mapping adapter_name -> path (e.g. {'wireguard': '/path/to/adapter'})
            gpu_utilization: VRAM limit (0.8 recommended for 8GB GPU with 8-bit quantization)
            max_model_len: Maximum sequence length (tokens). Increase if prompts are very long.
        """
        if hasattr(self, "llm"):
            return

        logger.info(f"🚀 Initializing vLLM Engine (Base: {model_path})")
        logger.info(f"   - GPU Util: {gpu_utilization}")
        logger.info(f"   - Max Len: {max_model_len}")
        logger.info(f"   - Adapters: {list(lora_adapters.keys()) if lora_adapters else 'None'}")

        self.lora_adapters = lora_adapters or {}
        self.sampling_params = SamplingParams(temperature=0.1, max_tokens=512)
        
        try:
            self.llm = LLM(
                model=model_path,
                enable_lora=True,
                max_lora_rank=64,
                gpu_memory_utilization=gpu_utilization,
                max_model_len=max_model_len,
                quantization="bitsandbytes",  # 8-bit enforcement
                load_format="bitsandbytes",
                enforce_eager=True            # bitsandbytes incompatible avec CUDA graphs
            )
            logger.info("✅ vLLM Engine Ready")
        except Exception as e:
            logger.critical(f"❌ Failed to initialize vLLM: {e}")
            raise e

    def complete(
        self,
        prompt: str,
        adapter_name: Optional[str] = None,
        json_schema: Optional[dict] = None,
    ) -> str:
        """
        Generates text completion.

        Args:
            prompt:       Input text (already formatted with special tokens)
            adapter_name: Key from lora_adapters dict to use specific LoRA
            json_schema:  Optional JSON schema for structured output (Outlines/vLLM v1).
                          When provided, the output is guaranteed to be valid JSON matching
                          the schema. Falls back to unconstrained generation if the feature
                          is unavailable or incompatible (bitsandbytes + enforce_eager).
        """
        lora_request = None

        if adapter_name and adapter_name in self.lora_adapters:
            adapter_path = self.lora_adapters[adapter_name]
            adapter_id = abs(hash(adapter_name)) % 10000
            lora_request = LoRARequest(
                lora_name=adapter_name,
                lora_int_id=adapter_id,
                lora_path=adapter_path,
            )

        # Construit les SamplingParams — avec décodage contraint si demandé
        if json_schema and _STRUCTURED_OUTPUT_AVAILABLE:
            try:
                sampling = SamplingParams(
                    temperature=0.1,
                    max_tokens=512,
                    structured_outputs=StructuredOutputsParams(json=json_schema),
                )
            except Exception as e:
                logger.debug("StructuredOutputsParams construction failed, fallback: %s", e)
                sampling = self.sampling_params
        else:
            sampling = self.sampling_params

        try:
            outputs = self.llm.generate(
                prompt,
                sampling,
                lora_request=lora_request,
                use_tqdm=False,
            )
        except Exception as e:
            # Décodage contraint non supporté par cette config vLLM (ex: bitsandbytes + enforce_eager)
            # → retry sans contrainte
            if json_schema:
                logger.warning(
                    "Structured output failed (%s), retrying without schema constraint", e
                )
                outputs = self.llm.generate(
                    prompt,
                    self.sampling_params,
                    lora_request=lora_request,
                    use_tqdm=False,
                )
            else:
                raise

        if outputs and len(outputs) > 0:
            return outputs[0].outputs[0].text
        return ""

    def shutdown(self):
        """
        Explicitly shuts down the vLLM engine and releases resources.
        """
        if hasattr(self, "llm"):
            logger.info("Shutting down vLLM engine...")
            try:
                from vllm.distributed.parallel_state import destroy_model_parallel
                destroy_model_parallel()
            except ImportError:
                pass
            except Exception as e:
                logger.warning("Error during vLLM parallel cleanup: %s", e)

            try:
                import torch.distributed as dist
                if dist.is_available() and dist.is_initialized():
                    dist.destroy_process_group()
            except Exception as e:
                logger.warning("Error during torch.distributed cleanup: %s", e)

            del self.llm
            NativeVLLMClient._instance = None
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            logger.info("vLLM engine resources released.")
