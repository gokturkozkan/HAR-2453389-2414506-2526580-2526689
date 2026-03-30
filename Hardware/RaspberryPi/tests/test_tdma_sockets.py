import socket

from tdma_wifi_transport import broadcast_socket, listening_socket


def test_broadcast_socket_sets_broadcast_and_reuseaddr():
    sock = broadcast_socket()
    try:
        assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST) == 1
        assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR) == 1
    finally:
        sock.close()


def test_listening_socket_binds_requested_port_and_is_nonblocking():
    sock = listening_socket(0)
    try:
        host, port = sock.getsockname()
        assert host == "0.0.0.0"
        assert port > 0
        assert sock.getblocking() is False
        assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR) == 1
    finally:
        sock.close()
