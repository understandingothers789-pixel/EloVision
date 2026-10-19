import socket

from elovision.__main__ import bind_local_server_socket


def test_launcher_falls_forward_to_free_local_port_when_preferred_is_busy():
    occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupied.bind(("127.0.0.1", 0))
    occupied.listen(1)
    preferred_port = occupied.getsockname()[1]
    server_socket = None
    try:
        server_socket, selected_port = bind_local_server_socket(preferred_port)
        assert selected_port != preferred_port
        assert server_socket.getsockname() == ("127.0.0.1", selected_port)
    finally:
        occupied.close()
        if server_socket is not None:
            server_socket.close()


def test_launcher_reports_the_assigned_port_for_ephemeral_bind():
    server_socket, selected_port = bind_local_server_socket(0)
    try:
        assert selected_port == server_socket.getsockname()[1]
        assert selected_port > 0
    finally:
        server_socket.close()
