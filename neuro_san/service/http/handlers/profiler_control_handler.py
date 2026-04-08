from typing import Any
from typing import Dict
from typing import Optional
import logging

try:
    import yappi
    has_profiler = True
except ImportError:
    has_profiler = False
    print("yappi library is required for profiling. Please install it with 'pip install yappi'")

from http import HTTPStatus
from tornado.web import RequestHandler


class ProfilerControlHandler(RequestHandler):

    # pylint: disable=attribute-defined-outside-init
    def initialize(self,
                   op: str,
                   logging_config: Dict[str, Any],
                   prof_data_path: Optional[str]):
        """
        This method is called by Tornado framework to allow
        injecting service-specific data into local handler context.
        :param op: requested profiler operation:
                   "start" for starting run-time profiler
                   "stop" for stopping profiler
        :param prof_data_path: optional path to save profiler data when stopping profiler;
            if not provided, data will be saved in current working directory with default name "profile.prof"
        """
        self.op: str = op
        self.logging_config: Dict[str, Any] = logging_config
        self.prof_data_path: str = prof_data_path
        if self.prof_data_path is None:
            self.prof_data_path = "profile.prof"
        self.logger = logging.getLogger(self.__class__.__name__)

    def get(self):
        """
        Implementation of GET request handler for profiler control.
        """
        if not has_profiler:
            self.set_status(HTTPStatus.SERVICE_UNAVAILABLE)
            self.write("Profiler library yappi is not available. Please install it with 'pip install yappi'")
            self.logger.info("Profiler library yappi is not available. Please install it with 'pip install yappi'")
            return

        if self.op == "start":
            yappi.set_clock_type("wall")
            yappi.start()
            self.write("profiling started")
            self.logger.info(">>>>>PROFILER STARTED")
        else:
            yappi.stop()
            stats = yappi.get_func_stats()
            stats.save(self.prof_data_path, type="pstat")
            self.write(f"profiling stopped and saved to {self.prof_data_path}")
            self.logger.info(">>>>>PROFILER STOPPED AND SAVED TO %s", self.prof_data_path)
