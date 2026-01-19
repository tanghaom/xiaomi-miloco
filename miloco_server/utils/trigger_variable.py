# Copyright (C) 2025 Xiaomi Corporation
# This software may be used and distributed according to the terms of the Xiaomi Miloco License Agreement.

"""
Trigger variable substitution utility
Provides variable replacement for trigger rule action parameters
"""

import copy
import logging
import re
from datetime import datetime
from typing import Any, Optional

from miloco_server.config.normal_config import SERVER_CONFIG
from miloco_server.controller.public_controller import get_public_image_url
from miloco_server.schema.miot_schema import CameraImgInfoPath

logger = logging.getLogger(__name__)


class TriggerVariableContext:
    """Context for trigger variable substitution"""

    def __init__(
        self,
        rule_name: str,
        trigger_time: datetime,
        trigger_images: Optional[list[CameraImgInfoPath]] = None,
        condition: Optional[str] = None,
    ):
        self.rule_name = rule_name
        self.trigger_time = trigger_time
        self.trigger_images = trigger_images or []
        self.condition = condition or ""
        self._public_url = SERVER_CONFIG.get("public_url", "")

    def _get_public_image_urls(self) -> list[str]:
        """Get list of public image URLs"""
        if not self._public_url:
            logger.warning(
                "public_url is not configured. Image URLs will not be available. "
                "Please set 'public_url' in server_config.yaml or environment variable MILOCO_PUBLIC_URL"
            )
            return []

        if not self.trigger_images:
            logger.info("No trigger images available for URL generation")
            return []

        urls = []
        for img_info in self.trigger_images:
            url = get_public_image_url(img_info.data, self._public_url)
            if url:
                urls.append(url)
                logger.debug("Generated public image URL: %s", url)

        logger.info("Generated %d public image URLs", len(urls))
        return urls

    def get_variables(self) -> dict[str, str]:
        """
        Get all available variables for substitution

        Returns:
            dict: Variable name to value mapping
        """
        image_urls = self._get_public_image_urls()

        # Provide helpful message if no images available
        no_image_hint = ""
        if not image_urls:
            if not self._public_url:
                no_image_hint = "(请配置 public_url 以启用图片链接)"
            elif not self.trigger_images:
                no_image_hint = "(无触发图片)"

        variables = {
            # Rule info
            "rule_name": self.rule_name,
            "condition": self.condition,

            # Time info
            "trigger_time": self.trigger_time.strftime("%Y-%m-%d %H:%M:%S"),
            "trigger_date": self.trigger_time.strftime("%Y-%m-%d"),
            "trigger_time_only": self.trigger_time.strftime("%H:%M:%S"),

            # Image info
            "trigger_image": image_urls[0] if image_urls else no_image_hint,
            "trigger_images": "\n".join(image_urls) if image_urls else no_image_hint,
            "trigger_images_markdown": "\n".join([f"![image]({url})" for url in image_urls]) if image_urls else no_image_hint,
            "trigger_images_html": "\n".join([f'<img src="{url}" />' for url in image_urls]) if image_urls else no_image_hint,
            "trigger_image_count": str(len(self.trigger_images)),  # Use actual image count, not URL count
        }

        logger.info(
            "Variable context - rule: %s, images: %d, public_url configured: %s",
            self.rule_name, len(self.trigger_images), bool(self._public_url)
        )

        return variables


def substitute_variables(value: Any, context: TriggerVariableContext) -> Any:
    """
    Recursively substitute variables in a value

    Supported variable format: {variable_name}
    Available variables:
        - {rule_name}: Rule name
        - {condition}: Trigger condition
        - {trigger_time}: Full trigger time (YYYY-MM-DD HH:MM:SS)
        - {trigger_date}: Trigger date (YYYY-MM-DD)
        - {trigger_time_only}: Trigger time only (HH:MM:SS)
        - {trigger_image}: First image URL (if available)
        - {trigger_images}: All image URLs, one per line
        - {trigger_images_markdown}: All images in markdown format
        - {trigger_images_html}: All images in HTML img tags
        - {trigger_image_count}: Number of trigger images

    Args:
        value: Value to substitute (can be str, dict, list, or other)
        context: Variable context

    Returns:
        Value with variables substituted
    """
    if isinstance(value, str):
        return _substitute_string(value, context.get_variables())
    elif isinstance(value, dict):
        return {k: substitute_variables(v, context) for k, v in value.items()}
    elif isinstance(value, list):
        return [substitute_variables(item, context) for item in value]
    else:
        return value


def _substitute_string(text: str, variables: dict[str, str]) -> str:
    """
    Substitute variables in a string

    Args:
        text: String with variable placeholders
        variables: Variable name to value mapping

    Returns:
        String with variables replaced
    """
    # Pattern matches {variable_name}
    pattern = re.compile(r'\{(\w+)\}')

    def replace_match(match):
        var_name = match.group(1)
        if var_name in variables:
            return variables[var_name]
        # Keep original if variable not found
        return match.group(0)

    return pattern.sub(replace_match, text)


def substitute_action_input(
    action_input: dict[str, Any],
    context: TriggerVariableContext
) -> dict[str, Any]:
    """
    Substitute variables in action input

    Args:
        action_input: Original action input dictionary
        context: Variable context

    Returns:
        New dictionary with variables substituted
    """
    # Deep copy to avoid modifying original
    new_input = copy.deepcopy(action_input)
    return substitute_variables(new_input, context)

