import threading
from remote_controller import UnityRemoteClient

remote_client = None
remote_lock = threading.Lock()


def init_remote_client():
    global remote_client
    with remote_lock:
        if remote_client is None:
            remote_client = UnityRemoteClient()
    return remote_client


def get_remote_client():
    global remote_client
    return remote_client


def get_remote_status():
    global remote_client

    if remote_client is None:
        return {
            "initialized": False,
            "connected": False,
            "host": None,
            "port": None
        }

    return {
        "initialized": True,
        "connected": remote_client.is_connected(),
        "host": remote_client.host,
        "port": remote_client.port
    }
