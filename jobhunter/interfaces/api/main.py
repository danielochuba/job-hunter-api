"""ASGI entry point: `uvicorn jobhunter.interfaces.api.main:app --reload`"""
import logging

from .app import create_app

logging.basicConfig(level=logging.INFO)
app = create_app()
