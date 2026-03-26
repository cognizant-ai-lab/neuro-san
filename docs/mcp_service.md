# Neuro-san MCP service

Neuro-san server runs MCP (Model Context Protocol) service.
To enable this, you should specify

--mcp_enable=true in the server command line or set environment variable AGENT_MCP_ENABLE=true;
in this case the server will provide both MCP and native neuro-san API simultaneously.

Another option is to specify:

--mcp_only=true in the server command line or set environment variable AGENT_MCP_ONLY=true;
in this case the server will only provide MCP API endpoint, native neuro-san API will be disabled.

## MCP service version

Neuro-san implements MCP protocol version 2025-06-18
by JSON-RPC 2.0 HTTP transport.
For the full MCP protocol specification, please see:
[MCP protocol](https://modelcontextprotocol.io/specification/2025-06-18/)

Streaming HTTP transport is not used, MCP service response is always a single JSON-RPC payload.
For this reason, MCP server does not force maintaining client-server sessions.
This operating mode is allowed by MCP specification and provides
easy scalability of neuro-san/MCP deployment.

## Agent networks as MCP tools

In the scope of MCP protocol, each public neuro-san agent network is represented by an MCP tool
(see [MCP tools](https://modelcontextprotocol.io/specification/2025-06-18/server/tools))
with the name of a tool being the same as the network name.
Chat request to an agent network becomes a tool call, with the following json schema,
replicated from neuro-san OpenAPI specification:

    ```json
    {
            "name": agent_name,
            "description": tool_description,
            "inputSchema": {
              "components": {
                  "schemas": {
                    "ChatContext": {
                      "type": "object",
                      "properties": {
                        "chat_histories": {
                          "type": "array",
                          "items": {
                            "$ref": "#/components/schemas/ChatHistory"
                          },
                          "description": "A potentially full list of chat histories that pertain to the node. "
                        }
                      },
                      "description": "Message for holding the state of play for any chat session"
                    },
                    "ChatFilter": {
                      "type": "object",
                      "properties": {
                        "chat_filter_type": {
                          "enum": [
                            "UNKNOWN",
                            "MINIMAL",
                            "MAXIMAL"
                          ],
                          "type": "string",
                          "description": "For now allow for an enum to describe how we want chat messages streamed. ",
                          "format": "enum"
                        }
                      },
                      "description": "Allows for controlling the messages that get streamed via StreamingChat."
                    },
                    "ChatHistory": {
                      "type": "object",
                      "properties": {
                        "origin": {
                          "type": "array",
                          "items": {
                            "$ref": "#/components/schemas/Origin"
                          }
                        },
                        "messages": {
                          "type": "array",
                          "items": {
                            "$ref": "#/components/schemas/ChatMessage"
                          }
                        }
                      },
                      "description": "A structure for storing chat history for a given node in the graph described by the origin."
                    },
                    "ChatMessage": {
                      "type": "object",
                      "properties": {
                        "type": {
                          "enum": [
                            "UNKNOWN",
                            "SYSTEM",
                            "HUMAN",
                            "AI",
                            "AGENT",
                            "AGENT_FRAMEWORK",
                            "AGENT_TOOL_RESULT",
                            "AGENT_PROGRESS"
                          ],
                          "type": "string",
                          "description": "The type of chat message",
                          "format": "enum"
                        },
                        "text": {
                          "type": "string",
                          "description": "String contents of any chat message"
                        },
                        "mime_data": {
                          "type": "array",
                          "items": {
                            "$ref": "#/components/schemas/MimeData"
                          },
                          "description": "Optional bytes for any non-text media referenced by this message. "
                        },
                        "origin": {
                          "type": "array",
                          "items": {
                            "$ref": "#/components/schemas/Origin"
                          },
                          "description": "Optional list of Origin structures (see above) describing the origin of the chat message."
                        },
                        "structure": {
                          "type": "object",
                          "description": "Optional structure for a message whose contents are parsed JSON."
                        },
                        "chat_context": {
                          "$ref": "#/components/schemas/ChatContext"
                        },
                        "tool_result_origin": {
                          "type": "array",
                          "items": {
                            "$ref": "#/components/schemas/Origin"
                          },
                          "description": "Optional list of Origin structures (see above) describing the origin of a tool result."
                        },
                        "sly_data": {
                          "type": "object",
                          "description": "This is an entirely optional map whose keys refer to data that is better left out of the LLM chat stream."
                        }
                      },
                      "description": "Structure describing a single chat message."
                    },
                    "ChatRequest": {
                      "type": "object",
                      "properties": {
                        "sly_data": {
                          "type": "object",
                          "description": "This is an entirely optional map whose keys refer to data that is better left out of the LLM chat stream."
                        },
                        "user_message": {
                          "$ref": "#/components/schemas/ChatMessage"
                        },
                        "chat_context": {
                          "$ref": "#/components/schemas/ChatContext"
                        },
                        "chat_filter": {
                          "$ref": "#/components/schemas/ChatFilter"
                        }
                      },
                      "description": "Request structure for Chat gRPC method",
                      "required": [
                        "user_message"
                      ],
                      "additionalProperties": false
                    },
                    "MimeData": {
                      "type": "object",
                      "properties": {
                        "mime_type": {
                          "type": "string",
                          "description": "MIME type of the image data"
                        },
                        "mime_bytes": {
                          "type": "string",
                          "description": "Raw bytes of the image",
                          "format": "byte"
                        }
                      },
                      "description": "A Message identifying image data"
                    },
                    "Origin": {
                      "type": "object",
                      "properties": {
                        "tool": {
                          "type": "string",
                          "description": "String name of the originating tool, as per the agent spec."
                        },
                        "instantiation_index": {
                          "type": "integer",
                          "description": "Some tools can be called more than once by one or more different paths. Allow for an instantiation index to distinguish these in the chat stream. Index counting starts at 0.",
                          "format": "int32"
                        }
                      }
                    }
                  }
              },                
              "$ref": "#/components/schemas/ChatRequest"
            }
    }
    ```
where tool name is a name of an agent network,
and tool description is what is returned by "function" neuro-san API call.
See [Infrastructure](../README.md#infrastructure)

## MCP tool call example

Here is an example of using a simple hello_world agent by means of MCP service,
showing several clent-server transactions:

### Initialize connection handshake

   Note that in current non-streaming mode MCP server will not create a session;
    still, this handshake step is mandatory by protocol:

curl example:

    ```shell
    curl -v -X POST http://localhost:8080/mcp \
      -H "Content-Type: application/json" \
      -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
    ```

Server response (example body):

    ```json
    {
      "jsonrpc": "2.0",
      "id": 1,
      "result": {
        "protocolVersion": "2025-06-18",
        "capabilities": { "logging": {}, "prompts": {}, "resources": {}, "tools": { "listChanged": false } },
        "serverInfo": { "name":"Neuro-san-MCPServer","title":"Neuro-san MCP Server","version":"1.0.0" },
        "instructions": ""
      }
    }
    ```

Note that the protocol version (if accepted by a client) must now be set as a request header
in all subsequent client messages.

### Acknowledge initialization (activate the current client-server connection)

    ```shell
    curl -v -X POST http://localhost:8080/mcp \
    -H "Content-Type: application/json" \
    -H "MCP-Protocol-Version: 2025-06-18" \
    -d '{"jsonrpc":"2.0","id":2,"method":"notifications/initialized","params":{}}'
    ```

Server response: HTTP 202 if connection activated successfully.

### List tools

    ```shell
    curl -X POST http://localhost:8080/mcp \
      -H "Content-Type: application/json" \
      -H "MCP-Protocol-Version: 2025-06-18" \
      -d '{"jsonrpc":"2.0","id":3,"method":"tools/list","params":{}}'
    ```

Server response body:

    ```json
    {
      "jsonrpc": "2.0",
      "id": 1,
      "result": {
        "tools": [
          {
            "name": "hello_world",
            "description": "\nI can help you to make a terse announcement.\nTell me what your target audience is, and what sentiment you would like to relate.\n",
            "inputSchema": {
              "type": "object",
              "properties": {
                "input": {
                  "type": "string",
                  "description": "text input for chat request"
                }
              },
              "required": [
                "input"
              ]
            }
          }
        ]
      }
    }
    ```

### Call a "hello_world" tool

    ```shell
    curl -X POST http://localhost:8080/mcp \
      -H "Content-Type: application/json" \
      -H "MCP-Protocol-Version: 2025-06-18" \
      -d '{
        "jsonrpc":"2.0",
        "id":4,
        "method":"tools/call",
        "params": {
          "name": "hello_world",
          "arguments": {
              "user_message": {
                "text": "Say hello in two words"
              }
          }
        }
      }'
    ```

Server response body:

    ```json
    {
      "jsonrpc": "2.0",
      "id": 1,
      "result": {
        "content":
          [{"type": "text", "text": "Hails there"}],
        "isError": false
      }
    }
    ```
