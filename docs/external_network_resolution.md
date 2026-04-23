# External Network Resolution

> **TL;DR:**  
> If you're using the **library/API** in **direct mode without a server**, make sure external
> networks are resolved with `use_direct=True` (or the equivalent setting). The CLI already
> defaults to direct external resolution unless you override it. If `use_direct=False` and no
> server is running, the request will **hang silently** (no error, just timeout).

> **⚠️ Common Pitfall:**  
> In direct mode, if `use_direct=False` and no server is running,  
> the system will **wait indefinitely for an HTTP server that doesn’t exist**.

---

## What are external networks?

External networks are agent networks referenced via `/`-prefixed tool names  
(e.g. `/agent_network_editor`).

For example, if your main agent calls `/agent_network_editor`, that editor  
is an **external network**. It must be resolved either:

- via **HTTP (through a server)**, or  
- **in-process (direct execution)**

For full details on how to define them in HOCON, see:  
[External Agents in the agent HOCON reference](agent_hocon_reference.md#external-agents)

---

## Connection type vs `use_direct`

These control **different parts** of the system:

- **Connection type** (`direct` / `http` / `mcp`)  
  → how the **client connects to the top-level agent network**

- **`use_direct`** (`True` / `False`)  
  → how the **top-level agent resolves external networks**

---

## Quick decision guide

| Scenario                        | Setting                | Server needed |
|--------------------------------|------------------------|---------------|
| Direct mode, no server         | `use_direct=True`      | ❌ No         |
| Direct mode, with server       | `use_direct=False`     | ✅ Yes        |
| HTTP / MCP connection          | Ignored (always False) | ✅ Yes        |

---

## How external networks are resolved

### HTTP & MCP connections

```
client → server → use_direct=False (hardcoded) → HTTP → external network
```

- The server **forces `use_direct=False`**
- The client setting is ignored
- External networks are always resolved via HTTP

---

### Direct connection

Direct mode runs the agent **in-process**, but external resolution depends on `use_direct`:

```
client → in-process → use_direct=True  → in-process → external network
client → in-process → use_direct=False → HTTP → external network (requires server)
```

#### `use_direct=True` (recommended for local use)

- Everything runs **in the same Python process**
- No server required
- External networks are loaded from local manifests

#### `use_direct=False` (hybrid mode)

- Top-level agent runs in-process
- External networks are resolved via HTTP
- **Requires a running server**

If no server is running, it will:

- ❌ Not throw an error  
- ❌ Not fail fast  
- ⏳ Just hang until timeout  

---

## How to avoid the silent hang

- ✅ Use `use_direct=True` when running in direct mode without a server  
- ✅ Or start the server before running:

```bash
python -m neuro_san.service.main_loop.server_main_loop
```

---

## How to set `use_direct`

### CLI (`agent_cli`)

The `--local_externals_direct` flag controls `use_direct` (default: `True`):

```bash
# use_direct=True (default) — no server needed
python -m neuro_san.client.agent_cli --agent agent_network_designer

# use_direct=False — requires a running server
python -m neuro_san.client.agent_cli \
  --agent agent_network_designer \
  --local_externals_service
```

---

### Library API (`AgentSessionFactory`)

Pass `use_direct` to `create_session()`:

```python
from neuro_san.client.agent_session_factory import AgentSessionFactory

# use_direct=True — in-process execution (no server needed)
session = AgentSessionFactory().create_session(
    "direct",
    "agent_network_designer",
    use_direct=True
)

# use_direct=False — requires server
session = AgentSessionFactory().create_session(
    "direct",
    "agent_network_designer",
    use_direct=False
)
```

> Same behavior as CLI:
> - `use_direct=True` → in-process  
> - `use_direct=False` → requires server  

> **Note:** The library API currently defaults `use_direct` to `False`.  
> This will change to `True` in a future release.  
> Until then, **always pass `use_direct=True` explicitly** for local direct usage.

---

### HOCON test fixtures

See the [`use_direct` section in test_case_hocon_reference.md](test_case_hocon_reference.md#use_direct)  
for configuration in data-driven test fixtures.

---

## Troubleshooting

**Symptom:** CLI hangs with no output  

**Likely cause:**  
- Running in direct mode  
- `use_direct=False`  
- No server running  

**Fix:**

- Set:
  ```python
  use_direct=True
  ```
- Or start the server:
  ```bash
  python -m run --server-only
  ```
