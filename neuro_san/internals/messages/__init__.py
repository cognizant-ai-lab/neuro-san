from typing import Any
from typing import Type

from neuro_san.internals.utils.deprecation_redirect import DeprecationRedirect

_DEPRECATION_REDIRECT = DeprecationRedirect(
    __name__,
    # A map from old class name to new class name for compatibility
    {
        "chat_message_type.ChatMessageType": "neuro_san.message.types.chat_message_type.ChatMessageType",
        "origination.Origination": "neuro_san.message.utils.origination.Origination",
    }
)


def __getattr__(old_class: str) -> Type[Any]:
    """
    Redirect deprecated classes
    :param old_class: The old class name
    :return: The redirected class
    """
    return _DEPRECATION_REDIRECT.redirect_class(old_class)
