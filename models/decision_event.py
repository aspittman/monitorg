"""Versioned, strategy-neutral snapshots. No strategy is evaluated here."""
import json
from datetime import timezone
from models.records import parse_datetime

EVENT_TYPES = frozenset('MARKET_EVALUATION SIGNAL_GENERATED SIGNAL_REJECTED ENTRY_DECISION ORDER_SUBMITTED ORDER_ACCEPTED ORDER_REJECTED ORDER_CANCELLED ORDER_EXPIRED ORDER_FILLED POSITION_OPENED POSITION_UPDATED STOP_UPDATED EXIT_SIGNAL EXIT_DECISION EXIT_ORDER_SUBMITTED EXIT_FILLED POSITION_CLOSED CONTRACT_SELECTION'.split())
MAX_EVENT_BYTES = 65536


def validate_event(value, bot_id):
    if not isinstance(value, dict):
        raise ValueError('Event must be an object')
    e = json.loads(json.dumps(value, allow_nan=False))
    if len(json.dumps(e).encode()) > MAX_EVENT_BYTES:
        raise ValueError('Event exceeds 64 KiB')
    if e.get('schema_version') != 1 or e.get('bot_id') != bot_id:
        raise ValueError('Schema version or bot identity mismatch')
    for key in ('event_id', 'timestamp', 'symbol', 'strategy'):
        if not isinstance(e.get(key), str) or not e[key] or len(e[key]) > 256:
            raise ValueError('Missing/invalid '+key)
    for key in ('trade_id', 'decision_id', 'order_id'):
        if key in e and (not isinstance(e[key], str) or not e[key] or len(e[key]) > 256):
            raise ValueError('Invalid '+key)
    if e.get('event_type') not in EVENT_TYPES:
        raise ValueError('Unknown event type')
    stamp = parse_datetime(e['timestamp'])
    if stamp.tzinfo is None:
        raise ValueError('Timestamp must include timezone')
    e['timestamp'] = stamp.astimezone(timezone.utc).isoformat()
    e.setdefault('provenance', 'RECORDED')
    if e['provenance'] not in ('RECORDED', 'RECONSTRUCTED'):
        raise ValueError('Invalid provenance')
    if e['provenance'] == 'RECONSTRUCTED' and not e.get('source'):
        raise ValueError('Reconstruction requires source')
    conditions = e.get('conditions', [])
    if not isinstance(conditions, list) or len(conditions) > 100:
        raise ValueError('Invalid conditions')
    for c in conditions:
        if not isinstance(c, dict) or not isinstance(c.get('name'), str) or not c['name']:
            raise ValueError('Invalid condition')
        for key in ('required', 'passed'):
            if c.get(key) is not None and type(c[key]) is not bool:
                raise ValueError('Condition states must be boolean or null')
    for key in ('market', 'risk', 'option', 'contract_selection', 'position', 'pipeline', 'indicators'):
        if key in e and not isinstance(e[key], dict):
            raise ValueError(key+' must be an object')
    if 'conditions_complete' in e and type(e['conditions_complete']) is not bool:
        raise ValueError('Invalid completeness flag')
    return e
