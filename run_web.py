#!/usr/bin/env python3
"""
Entry point for VNU-UET Research Hours Web Application.

Usage:
    python run_web.py

The application will be available at http://127.0.0.1:5000
"""

import os
import sys

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from app import create_app

app = create_app()


if __name__ == "__main__":
    # Development server
    port = int(os.environ.get("PORT", 5050))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"

    print(
        f"""
================================================================================
    VNU-UET Research Hours Web Application
    Quy che QD 2706/QD-DHCN ngay 21/11/2024
================================================================================

    Server running at: http://127.0.0.1:{port}

    Press Ctrl+C to stop the server.
================================================================================
    """
    )

    app.run(
        host="127.0.0.1",
        port=port,
        debug=debug,
    )
