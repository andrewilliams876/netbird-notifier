"""Expire the synthetic health record for the Docker healthcheck smoke test."""
import sqlite3

with sqlite3.connect("/data/state.sqlite3") as connection:
    connection.execute("UPDATE health SET success_at = 0")
