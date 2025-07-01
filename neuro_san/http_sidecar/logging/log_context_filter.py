
# Copyright (C) 2023-2025 Cognizant Digital Business, Evolutionary AI.
# All Rights Reserved.
# Issued under the Academic Public License.
#
# You can be released from the terms, and requirements of the Academic Public
# License by purchasing a commercial license.
# Purchase of a commercial license is mandatory for any use of the
# neuro-san SDK Software in commercial settings.
#
# END COPYRIGHT
from neuro_san.service.http.logging.log_context_filter import LogContextFilter as ParentLogContextFilter

print("""
WARNING: The class:
     neuro_san.http_sidecar.logging.log_context_filter.LogContextFilter
... has moved to be ...
    neuro_san.service.http.logging.log_context_filter.LogContextFilter.
Please update the logging.json file associated with your Neuro SAN agent server accordingly.
""")

class LogContextFilter(ParentLogContextFilter):
    """
    Compatibility class for logging.json entries that haven't quite converted yet.
    """
