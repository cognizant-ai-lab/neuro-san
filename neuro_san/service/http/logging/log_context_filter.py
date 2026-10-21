
# Copyright © 2023-2026 Cognizant Technology Solutions Corp, www.cognizant.com.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# END COPYRIGHT

import contextvars
import logging


class LogContextFilter(logging.Filter):
    """
    Custom logging filter for Http server.
    """

    def filter(self, record):
        """
        Logging filter: add key-value pairs from log_context
        to logging record to be used.
        """
        ctx = LogContextFilter.log_context.get()
        for key, value in ctx.items():
            setattr(record, key, value)
        return True

    @classmethod
    def set_log_context(cls):
        """
        Create log context class instance.
        """
        cls.log_context = contextvars.ContextVar("http_server_context", default={})
