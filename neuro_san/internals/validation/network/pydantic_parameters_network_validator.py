
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

from logging import getLogger
from logging import Logger
from typing import Any
from typing import Dict
from typing import List

from neuro_san.internals.run_context.langchain.core.base_model_dictionary_converter import \
    BaseModelDictionaryConverter
from neuro_san.internals.validation.network.abstract_network_validator import AbstractNetworkValidator


class PydanticParametersNetworkValidator(AbstractNetworkValidator):
    """
    AbstractNetworkValidator that validates each tool's
    function.parameters block by running the same pydantic
    BaseModelDictionaryConverter pipeline used at tool-creation time.

    Catches unrecognized type strings, malformed structures, and anything
    that would crash at runtime.  Also reports null and non-dict
    parameters blocks as structural errors.

    Expects a fully-resolved config: ParametersSchemaNetworkValidator,
    the composite that owns this validator, applies NetworkConfigFilterChain
    (commondefs, defaults, name-correction) once before running both phases.
    """

    def __init__(self, network_name: str = None):
        """
        Constructor

        :param network_name: The agent network name for diagnostic log lines
        """
        self.logger: Logger = getLogger(self.__class__.__name__)
        self.network_name: str = network_name

    # --- Override ---

    # Overrides AbstractNetworkValidator.validate_name_to_spec_dict
    def validate_name_to_spec_dict(self, name_to_spec: Dict[str, Any]) -> List[str]:
        """
        :param name_to_spec: The name -> agent spec dictionary to validate
        :return: A list of error messages describing pydantic conversion problems.
        """
        errors: List[str] = []

        self.logger.debug("Validating %s parameters via pydantic...", self.network_name)

        # The converter is stateless, so one instance serves every agent.
        converter = BaseModelDictionaryConverter("parameters")

        for agent_name, agent_spec in name_to_spec.items():
            params: Any = self._locate_parameters(agent_spec)

            if params is self._PARAMS_NOT_FOUND:
                # No parameters block at all - nothing to validate.
                continue
            if params is None:
                errors.append(
                    f"{agent_name}: 'parameters' is null - use {{}} or remove the key"
                )
                continue
            if not isinstance(params, dict):
                errors.append(
                    f"{agent_name}: 'parameters' must be object, "
                    f"got {type(params).__name__}"
                )
                continue

            properties: Any = params.get("properties")
            if not isinstance(properties, dict) or not properties:
                # No properties to convert - valid for zero-arg functions and
                # flat param maps. Pydantic expects properties.items(), so skip.
                continue

            try:
                converter.from_dict(params)
            except (AttributeError, KeyError, TypeError, ValueError) as exc:
                detail: str = " ".join(str(exc).split())
                errors.append(f"{agent_name}: pydantic model conversion failed - {detail}")
            except Exception as exc:  # pylint: disable=broad-exception-caught
                # from_dict() delegates to pydantic's create_model() and
                # recursive type resolution, which can raise unexpected
                # exception types on severely malformed input.
                detail = " ".join(str(exc).split())
                errors.append(f"{agent_name}: pydantic model conversion failed - {detail}")

        return errors
