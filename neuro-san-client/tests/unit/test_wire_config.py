
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
"""Unit tests for neuro_san_client.wire_config."""
from __future__ import annotations

import base64
import hashlib
import json
from typing import Any, Dict

import pytest

from neuro_san_client.wire_config import (
    AGENT_NETWORK_MIMETYPE,
    SUPPORTED_PROTOCOL_VERSION,
    WireConfigError,
    extract_wire_config_from_notebook,
    get_network_name,
    get_origin,
    list_tool_names,
    verify_client_side_source_integrity,
    verify_wire_config,
)


# ---------- fixtures ----------


def _minimal_wire(**overrides: Any) -> Dict[str, Any]:
    base = {
        "agent_web": {
            "protocol_version": SUPPORTED_PROTOCOL_VERSION,
            "origin": "http://origin.example:8801",
            "network_name": "flight_finder",
        },
        "llm_config": {"model_name": "claude-haiku"},
        "tools": [],
    }
    base.update(overrides)
    return base


def _notebook_with_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "nbformat": 4,
        "metadata": {},
        "cells": [
            {"cell_type": "markdown", "metadata": {}, "source": "# hi"},
            {
                "cell_type": "raw",
                "metadata": {
                    "format": AGENT_NETWORK_MIMETYPE,
                    "agent_web_role": "network_spec",
                },
                "source": json.dumps(spec),
            },
            {"cell_type": "code", "metadata": {}, "source": "print('hi')"},
        ],
    }


# ---------- extract_wire_config_from_notebook ----------


class TestExtractFromNotebook:
    def test_finds_role_tagged_cell(self):
        spec = _minimal_wire()
        nb = _notebook_with_spec(spec)
        out = extract_wire_config_from_notebook(nb)
        assert out == spec

    def test_finds_mimetype_tagged_cell(self):
        spec = _minimal_wire()
        nb = _notebook_with_spec(spec)
        # Strip the role tag, keep only mimetype.
        nb["cells"][1]["metadata"].pop("agent_web_role")
        out = extract_wire_config_from_notebook(nb)
        assert out == spec

    def test_source_as_list_of_lines(self):
        # nbformat stores source as list of lines preserving newlines.
        spec = _minimal_wire()
        spec_text = json.dumps(spec, indent=2)
        nb = _notebook_with_spec(spec)
        nb["cells"][1]["source"] = spec_text.splitlines(keepends=True)
        out = extract_wire_config_from_notebook(nb)
        assert out == spec

    def test_skips_non_spec_raw_cells(self):
        # A raw cell without the role/mime tag should NOT be picked up.
        spec = _minimal_wire()
        nb = {
            "cells": [
                {
                    "cell_type": "raw",
                    "metadata": {},
                    "source": "not a spec",
                },
                {
                    "cell_type": "raw",
                    "metadata": {"agent_web_role": "network_spec"},
                    "source": json.dumps(spec),
                },
            ],
        }
        out = extract_wire_config_from_notebook(nb)
        assert out == spec

    def test_no_spec_cell_raises(self):
        with pytest.raises(WireConfigError, match="No agent_web network_spec"):
            extract_wire_config_from_notebook({"cells": [
                {"cell_type": "markdown", "metadata": {}, "source": "#"}
            ]})

    def test_invalid_json_raises(self):
        nb = {
            "cells": [{
                "cell_type": "raw",
                "metadata": {"agent_web_role": "network_spec"},
                "source": "{ not valid json",
            }],
        }
        with pytest.raises(WireConfigError, match="does not parse as JSON"):
            extract_wire_config_from_notebook(nb)

    def test_non_dict_notebook_raises(self):
        with pytest.raises(WireConfigError, match="Notebook must be an object"):
            extract_wire_config_from_notebook("not a dict")  # type: ignore[arg-type]

    def test_missing_cells_raises(self):
        with pytest.raises(WireConfigError, match="no 'cells' array"):
            extract_wire_config_from_notebook({"nbformat": 4})

    def test_bad_source_type_raises(self):
        nb = {
            "cells": [{
                "cell_type": "raw",
                "metadata": {"agent_web_role": "network_spec"},
                "source": 123,
            }],
        }
        with pytest.raises(WireConfigError, match="must be string or list"):
            extract_wire_config_from_notebook(nb)


# ---------- verify_wire_config ----------


class TestVerifyWireConfig:
    def test_minimal_wire_passes(self):
        verify_wire_config(_minimal_wire())  # raises on failure

    def test_protocol_version_mismatch_raises(self):
        w = _minimal_wire()
        w["agent_web"]["protocol_version"] = "9.9"
        with pytest.raises(WireConfigError, match="protocol version mismatch"):
            verify_wire_config(w)

    def test_missing_origin_raises(self):
        w = _minimal_wire()
        w["agent_web"].pop("origin")
        with pytest.raises(WireConfigError, match="missing agent_web.origin"):
            verify_wire_config(w)

    def test_origin_must_be_fully_qualified(self):
        w = _minimal_wire()
        w["agent_web"]["origin"] = "not-a-url"
        with pytest.raises(WireConfigError, match="not a fully-qualified URL"):
            verify_wire_config(w)

    def test_same_origin_coded_tool_url_passes(self):
        w = _minimal_wire()
        w["tools"] = [
            {
                "name": "search_flights",
                "coded_tool_url": "http://origin.example:8801/api/v1/x/tool/y",
            },
        ]
        verify_wire_config(w)

    def test_cross_origin_coded_tool_url_raises(self):
        w = _minimal_wire()
        w["tools"] = [
            {
                "name": "search_flights",
                "coded_tool_url": "http://evil.example/api/v1/x/tool/y",
            },
        ]
        with pytest.raises(WireConfigError, match="not same-origin"):
            verify_wire_config(w)

    def test_https_vs_http_is_a_mismatch(self):
        w = _minimal_wire()
        w["agent_web"]["origin"] = "https://origin.example"
        w["tools"] = [
            {
                "name": "x",
                "coded_tool_url": "http://origin.example/tool/x",
            },
        ]
        with pytest.raises(WireConfigError, match="not same-origin"):
            verify_wire_config(w)

    def test_different_port_is_a_mismatch(self):
        w = _minimal_wire()
        w["tools"] = [
            {
                "name": "x",
                "coded_tool_url": "http://origin.example:9999/tool/x",
            },
        ]
        with pytest.raises(WireConfigError, match="not same-origin"):
            verify_wire_config(w)

    def test_leftover_class_field_raises(self):
        w = _minimal_wire()
        w["tools"] = [{"name": "x", "class": "should.have.been.stripped"}]
        with pytest.raises(WireConfigError, match="still has 'class'"):
            verify_wire_config(w)

    def test_leftover_toolbox_field_raises(self):
        w = _minimal_wire()
        w["tools"] = [{"name": "x", "toolbox": "should.have.been.stripped"}]
        with pytest.raises(WireConfigError, match="still has 'toolbox'"):
            verify_wire_config(w)

    def test_client_side_missing_source_raises(self):
        w = _minimal_wire()
        w["tools"] = [{"name": "calc", "client_side": True, "integrity": "sha256-abc"}]
        with pytest.raises(WireConfigError, match="missing client_side_source"):
            verify_wire_config(w)

    def test_client_side_missing_integrity_raises(self):
        w = _minimal_wire()
        w["tools"] = [{"name": "calc", "client_side": True,
                       "client_side_source": "Zm9v"}]
        with pytest.raises(WireConfigError, match="missing a valid sha256"):
            verify_wire_config(w)

    def test_client_side_bad_integrity_prefix_raises(self):
        w = _minimal_wire()
        w["tools"] = [{"name": "calc", "client_side": True,
                       "client_side_source": "Zm9v",
                       "integrity": "md5-abc"}]
        with pytest.raises(WireConfigError, match="missing a valid sha256"):
            verify_wire_config(w)

    def test_non_dict_wire_raises(self):
        with pytest.raises(WireConfigError, match="must be an object"):
            verify_wire_config([])  # type: ignore[arg-type]

    def test_tools_not_list_raises(self):
        w = _minimal_wire()
        w["tools"] = "not a list"
        with pytest.raises(WireConfigError, match="must be an array"):
            verify_wire_config(w)


# ---------- verify_client_side_source_integrity ----------


class TestVerifyIntegrity:
    def test_matching_hash_passes(self):
        src = b"class Calc:\n    pass\n"
        b64 = base64.b64encode(src).decode("ascii")
        digest = hashlib.sha256(src).hexdigest()
        out = verify_client_side_source_integrity(b64, f"sha256-{digest}")
        assert out == src

    def test_mismatched_hash_raises(self):
        src = b"class Calc:\n    pass\n"
        b64 = base64.b64encode(src).decode("ascii")
        with pytest.raises(WireConfigError, match="integrity check failed"):
            verify_client_side_source_integrity(b64, "sha256-" + "0" * 64)

    def test_bad_base64_raises(self):
        with pytest.raises(WireConfigError, match="bad base64"):
            verify_client_side_source_integrity("this is not base64!", "sha256-x")

    def test_empty_source_raises(self):
        with pytest.raises(WireConfigError, match="is empty"):
            verify_client_side_source_integrity("", "sha256-x")

    def test_missing_integrity_prefix_raises(self):
        with pytest.raises(WireConfigError, match="sha256-<hex>"):
            verify_client_side_source_integrity("Zm9v", "md5-abc")


# ---------- accessors ----------


class TestAccessors:
    def test_get_origin(self):
        assert get_origin(_minimal_wire()) == "http://origin.example:8801"
        assert get_origin({}) == ""

    def test_get_network_name(self):
        assert get_network_name(_minimal_wire()) == "flight_finder"
        assert get_network_name({}) == ""

    def test_list_tool_names(self):
        w = _minimal_wire()
        w["tools"] = [
            {"name": "a"},
            {"name": "b"},
            {"no_name": "x"},
            "not a dict",
        ]
        assert list_tool_names(w) == ["a", "b"]

    def test_list_tool_names_empty(self):
        assert list_tool_names({}) == []
