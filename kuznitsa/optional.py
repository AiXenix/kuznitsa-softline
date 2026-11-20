from importlib import import_module


def optional_module(name):
    try:
        return import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name != name:
            raise
        return None
