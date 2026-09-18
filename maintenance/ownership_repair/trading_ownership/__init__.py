"""Independent execution ownership guard. Does not import or contact BotMonitor."""
from .guard import GuardedClient, OwnershipError

def guarded_client(client, trader_id):
    return GuardedClient(client, trader_id)
