"""Supervisor package init."""

__all__ = ["main"]


def main():
    from .supervisor import main as supervisor_main

    return supervisor_main()
