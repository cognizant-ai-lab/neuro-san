
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

from neuro_san.internals.graph.activations.abstract_class_activation import AbstractClassActivation

CREATE_RUN_CONTEXT_PATH: str = \
    "neuro_san.internals.graph.activations.abstract_class_activation.RunContextFactory.create_run_context"
GET_FULL_NAME_FROM_ORIGIN_PATH: str = \
    "neuro_san.internals.graph.activations.abstract_class_activation.Origination.get_full_name_from_origin"


class ConcreteClassActivation(AbstractClassActivation):
    """Concrete implementation for testing purposes."""
    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-positional-arguments
    def __init__(self, parent_run_context, factory, args, agent_tool_spec, sly_data, class_ref: str):
        super().__init__(parent_run_context, factory, args, agent_tool_spec, sly_data)
        self._class_ref = class_ref

    def get_full_class_ref(self) -> str:
        return self._class_ref
