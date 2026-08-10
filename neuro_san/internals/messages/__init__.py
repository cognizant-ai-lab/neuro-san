from typing import Any
from typing import Type

from neuro_san.internals.utils.deprecation_redirect import DeprecationRedirect

DEPRECATION_REDIRECT = DeprecationRedirect(
    __name__,
    # A map from old class name to new class name for compatibility
    {
        "ChatMessageType": {
            "old_module": "chat_message_type",
            "new_class": "neuro_san.message.types.chat_message_type.ChatMessageType",
            "warned": False,
        }
    }
)


def __getattr__(old_class: str) -> Type[Any]:
    """
    Redirect deprecated classes
    :param old_class: The old class name
    :return: The redirected class
    """
    return DEPRECATION_REDIRECT.redirect_class(old_class)
