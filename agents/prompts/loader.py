"""
Prompt Loader - Utility for loading and rendering external prompts.

This module provides a centralized way to load prompts from YAML files
and render them using Jinja2 templates. This allows for:
- Easy prompt iteration without code changes
- Version control of prompts
- Separation of concerns (code vs. prompts)
- Hot reloading of prompts in development
"""
import yaml
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from jinja2 import Template, TemplateError
from functools import lru_cache

logger = logging.getLogger(__name__)


class PromptLoader:
    """
    Loads and renders prompts from YAML files.
    
    Prompts are stored in agents/prompts/{agent_name}/ directory.
    Each YAML file contains:
    - description: Purpose of the prompt
    - variables: List of required template variables
    - template: Jinja2 template string
    
    Example:
        loader = PromptLoader(agent_name="investigator")
        prompt = loader.render("investigation", task_name="Test", alert_id="123")
    """
    
    def __init__(self, agent_name: str, prompts_dir: Optional[Path] = None):
        """
        Initialize the prompt loader.
        
        Args:
            agent_name: Name of the agent (e.g., "investigator", "analyst")
            prompts_dir: Optional custom prompts directory (for testing)
        """
        self.agent_name = agent_name
        
        if prompts_dir is None:
            # Default to agents/prompts/{agent_name}/
            self.prompts_dir = Path(__file__).parent / agent_name
        else:
            self.prompts_dir = prompts_dir
        
        # Cache for loaded prompts
        self._cache: Dict[str, dict] = {}
        
        logger.debug(f"PromptLoader initialized for '{agent_name}' at {self.prompts_dir}")
    
    def load(self, prompt_name: str, use_cache: bool = True) -> dict:
        """
        Load a prompt definition from YAML.
        
        Args:
            prompt_name: Name of the prompt file (without .yaml extension)
            use_cache: Whether to use cached prompts
        
        Returns:
            Dictionary with 'description', 'variables', and 'template'
        
        Raises:
            FileNotFoundError: If prompt file doesn't exist
            yaml.YAMLError: If YAML is invalid
        """
        # Check cache first
        if use_cache and prompt_name in self._cache:
            logger.debug(f"Using cached prompt: {prompt_name}")
            return self._cache[prompt_name]
        
        # Load from file
        prompt_file = self.prompts_dir / f"{prompt_name}.yaml"
        
        if not prompt_file.exists():
            raise FileNotFoundError(
                f"Prompt file not found: {prompt_file}\n"
                f"Expected location: agents/prompts/{self.agent_name}/{prompt_name}.yaml"
            )
        
        try:
            with open(prompt_file, 'r', encoding='utf-8') as f:
                prompt_data = yaml.safe_load(f)
            
            # Validate structure
            required_keys = ['template']
            for key in required_keys:
                if key not in prompt_data:
                    raise ValueError(f"Prompt '{prompt_name}' missing required key: {key}")
            
            # Cache it
            if use_cache:
                self._cache[prompt_name] = prompt_data
            
            logger.debug(f"Loaded prompt: {prompt_name}")
            return prompt_data
        
        except yaml.YAMLError as e:
            logger.error(f"Invalid YAML in {prompt_file}: {e}")
            raise
    
    def render(self, prompt_name: str, **variables) -> str:
        """
        Load and render a prompt with the given variables.
        
        Args:
            prompt_name: Name of the prompt to render
            **variables: Template variables to inject
        
        Returns:
            Rendered prompt string
        
        Raises:
            FileNotFoundError: If prompt doesn't exist
            TemplateError: If template rendering fails
            ValueError: If required variables are missing
        
        Example:
            prompt = loader.render(
                "investigation",
                task_name="Analyze alert",
                alert_id="WAZUH-123"
            )
        """
        # Load the prompt
        prompt_data = self.load(prompt_name)
        
        # Check required variables
        required_vars = prompt_data.get('variables', [])
        missing_vars = [v for v in required_vars if v not in variables]
        
        if missing_vars:
            logger.warning(
                f"Missing variables for prompt '{prompt_name}': {missing_vars}. "
                f"Will use empty strings as defaults."
            )
            # Add empty defaults for missing vars
            for var in missing_vars:
                variables[var] = "N/A"
        
        # Render the template
        try:
            template = Template(prompt_data['template'])
            rendered = template.render(**variables)
            
            logger.debug(f"Rendered prompt '{prompt_name}' ({len(rendered)} chars)")
            return rendered
        
        except TemplateError as e:
            logger.error(f"Template rendering failed for '{prompt_name}': {e}")
            raise
    
    def clear_cache(self) -> None:
        """Clear the prompt cache (useful for hot reloading)."""
        self._cache.clear()
        logger.debug("Prompt cache cleared")
    
    def list_prompts(self) -> list[str]:
        """List all available prompts for this agent."""
        if not self.prompts_dir.exists():
            return []
        
        return [
            p.stem for p in self.prompts_dir.glob("*.yaml")
        ]


# Convenience function for one-off prompt loading
@lru_cache(maxsize=128)
def load_prompt(agent_name: str, prompt_name: str, **variables) -> str:
    """
    Convenience function to load and render a prompt in one call.
    
    This is cached for performance.
    
    Args:
        agent_name: Name of the agent
        prompt_name: Name of the prompt
        **variables: Template variables
    
    Returns:
        Rendered prompt string
    """
    loader = PromptLoader(agent_name)
    return loader.render(prompt_name, **variables)
