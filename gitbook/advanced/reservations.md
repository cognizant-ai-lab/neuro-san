# Reservations

**Reservations** are temporary agent networks with a limited lifetime. They are created
programmatically and automatically cleaned up after expiration.

## Use Cases

- **Agent Network Designer** -- Test networks before committing them permanently
- **Copy Cat** -- Create modified copies of existing networks for experimentation
- **Dynamic workflows** -- Spin up task-specific networks on demand

## How It Works

1. A reservation is created with a network definition and lifetime
2. The server loads the temporary network and assigns it a unique reservation ID
3. Clients interact with the network using the reservation ID as the agent name
4. After the lifetime expires, the network is automatically removed

## Configuration

Enable temporary network processing on the server:

```bash
export AGENT_TEMPORARY_NETWORK_UPDATE_PERIOD_SECONDS=300
```

This controls how frequently the server checks for new and expired temporary networks.
Set to `0` to disable.

## Reservation Metadata

Reservation information is passed through sly\_data:

```json
{
    "agent_reservations": [
        {
            "reservation_id": "abc-123-def",
            "lifetime_in_seconds": 3600,
            "expiration_time_in_seconds": 1700000000
        }
    ]
}
```

## Copy Cat Example

The Copy Cat experimental agent creates temporary copies of existing networks:

```
User: "Create a copy of coffee_finder and modify it to find tea instead."

Copy Cat:
  1. Reads the original coffee_finder HOCON
  2. Modifies the configuration
  3. Creates a temporary network via Reservations
  4. Returns the reservation ID for testing
```

## Next Steps

- [Agent Network Designer](agent-network-designer.md) -- Create networks from descriptions
- [Architecture Overview](architecture.md) -- System internals
