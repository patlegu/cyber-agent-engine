"""
Response validation utilities for agents.

This module provides helpers to:
- Parse and validate LLM JSON responses
- Convert raw responses to Pydantic models
- Handle validation errors gracefully
- Provide fallback values
"""
import json
import logging
from typing import TypeVar, Type, Optional, Dict, Any
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=BaseModel)


def parse_and_validate(
    response: str,
    model_class: Type[T],
    fallback: Optional[T] = None
) -> T:
    """
    Parse JSON response and validate against Pydantic model.
    
    Args:
        response: Raw string response from LLM
        model_class: Pydantic model class to validate against
        fallback: Optional fallback value if validation fails
        
    Returns:
        Validated model instance
        
    Raises:
        ValidationError: If validation fails and no fallback provided
    """
    try:
        # Try to parse JSON
        data = json.loads(response)
        
        # Validate with Pydantic
        return model_class(**data)
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON response: {e}")
        logger.debug(f"Raw response: {response[:500]}")
        
        if fallback is not None:
            logger.warning(f"Using fallback value for {model_class.__name__}")
            return fallback
        raise
        
    except ValidationError as e:
        logger.error(f"Validation failed for {model_class.__name__}: {e}")
        logger.debug(f"Data: {data}")
        
        if fallback is not None:
            logger.warning(f"Using fallback value for {model_class.__name__}")
            return fallback
        raise


def safe_parse(
    response: str,
    model_class: Type[T],
    default_factory: Optional[callable] = None
) -> Optional[T]:
    """
    Safely parse and validate response, returning None on failure.
    
    Args:
        response: Raw string response from LLM
        model_class: Pydantic model class to validate against
        default_factory: Optional callable to create default value
        
    Returns:
        Validated model instance or None/default
    """
    try:
        return parse_and_validate(response, model_class)
    except (json.JSONDecodeError, ValidationError) as e:
        logger.warning(f"Failed to parse {model_class.__name__}: {e}")
        
        if default_factory:
            return default_factory()
        return None


def extract_json_from_text(text: str) -> Optional[str]:
    """
    Extract JSON from text that may contain additional content.
    
    Handles cases where LLM adds explanatory text before/after JSON.
    
    Args:
        text: Text potentially containing JSON
        
    Returns:
        Extracted JSON string or None
    """
    # Try to find JSON object
    start = text.find('{')
    end = text.rfind('}')
    
    if start != -1 and end != -1 and end > start:
        return text[start:end+1]
    
    # Try to find JSON array
    start = text.find('[')
    end = text.rfind(']')
    
    if start != -1 and end != -1 and end > start:
        return text[start:end+1]
    
    return None


def parse_with_extraction(
    response: str,
    model_class: Type[T],
    fallback: Optional[T] = None
) -> T:
    """
    Parse response with JSON extraction fallback.
    
    First tries direct parsing, then attempts to extract JSON from text.
    
    Args:
        response: Raw string response from LLM
        model_class: Pydantic model class to validate against
        fallback: Optional fallback value if all parsing fails
        
    Returns:
        Validated model instance
    """
    try:
        # Try direct parsing first
        return parse_and_validate(response, model_class)
    except (json.JSONDecodeError, ValidationError):
        # Try extracting JSON from text
        logger.info("Direct parsing failed, attempting JSON extraction")
        
        json_str = extract_json_from_text(response)
        if json_str:
            try:
                return parse_and_validate(json_str, model_class)
            except (json.JSONDecodeError, ValidationError) as e:
                logger.error(f"Extraction parsing also failed: {e}")
        
        if fallback is not None:
            logger.warning(f"Using fallback value for {model_class.__name__}")
            return fallback
        
        raise ValidationError(f"Could not parse response as {model_class.__name__}")


def validate_dict(data: Dict[str, Any], model_class: Type[T]) -> T:
    """
    Validate a dictionary against a Pydantic model.
    
    Args:
        data: Dictionary to validate
        model_class: Pydantic model class
        
    Returns:
        Validated model instance
        
    Raises:
        ValidationError: If validation fails
    """
    return model_class(**data)


def to_dict_safe(model: BaseModel) -> Dict[str, Any]:
    """
    Safely convert Pydantic model to dict.
    
    Args:
        model: Pydantic model instance
        
    Returns:
        Dictionary representation
    """
    try:
        return model.model_dump()
    except Exception as e:
        logger.error(f"Failed to convert model to dict: {e}")
        return {}


def merge_partial_results(
    existing: Optional[T],
    new_data: Dict[str, Any],
    model_class: Type[T]
) -> T:
    """
    Merge new data into existing model, useful for partial updates.
    
    Args:
        existing: Existing model instance or None
        new_data: New data to merge
        model_class: Model class
        
    Returns:
        Updated model instance
    """
    if existing is None:
        return model_class(**new_data)
    
    # Convert existing to dict and update
    existing_dict = to_dict_safe(existing)
    existing_dict.update(new_data)
    
    return model_class(**existing_dict)
