"""Archipelago Server UI: the server service.

Its main process is a supervisor: it will start and stop Archipelago's MultiServer as a
child process, pass admin commands to its stdin and stream its output (#24). The web
service talks to it over a Unix socket on a volume only the two of them share (#70):
no listening port, and filesystem permissions are the authentication.

Standard library only, and it never imports Archipelago: the only Archipelago code in
this service runs inside MultiServer itself.
"""
