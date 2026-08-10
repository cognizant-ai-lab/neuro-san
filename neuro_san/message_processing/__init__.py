from typing import Any
from typing import Type

from neuro_san.internals.utils.deprecation_redirect import DeprecationRedirect

_DEPRECATION_REDIRECT = DeprecationRedirect(
    __name__,
    # A map from old class name to new class name for compatibility
    {
        "MessageProcessor": {
            "old_module": "message_processor",
            "new_class": "neuro_san.message.processors.message_processor.MessageProcessor",
            "warned": False,
        },
        "BasicMessageProcessor": {
            "old_module": "basic_message_processor",
            "new_class": "neuro_san.message.processors.basic_message_processor.BasicMessageProcessor",
            "warned": False,
        },
    }
)


def __getattr__(old_class: str) -> Type[Any]:
    """
    Redirect deprecated classes
    :param old_class: The old class name
    :return: The redirected class
    """
    return _DEPRECATION_REDIRECT.redirect_class(old_class)
