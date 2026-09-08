"""Exercise the launcher port probe without importing desktop side effects."""
import ast
from pathlib import Path
import socket
import sys


def test_port_probe_skips_running_listener():
    tree = ast.parse((Path(__file__).parents[1] / "app.py").read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "find_available_port")
    namespace = {"socket": socket, "sys": sys}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "app.py", "exec"), namespace)
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        port = occupied.getsockname()[1]
        selected = namespace["find_available_port"](port)
        assert selected != port
        with socket.socket() as server:
            server.bind(("127.0.0.1", selected))
            server.listen()
