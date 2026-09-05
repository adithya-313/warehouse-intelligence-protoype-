"""
Get Google OAuth Refresh Token for Automated Backups

WHAT THIS SCRIPT DOES:
    This script helps you obtain a Google OAuth refresh token that allows
    the Sentinel-Flow backup system to automatically upload database backups
    to your Google Drive without requiring you to log in each time.

WHY THIS IS A ONE-TIME MANUAL STEP:
    Google requires you to manually authorize the application once. After
    that, the refresh token allows automatic re-authorization forever.
    This script only needs to be run once to get that initial token.

IMPORTANT: DO NOT RUN THIS INSIDE DOCKER!
    This script needs to open a real web browser for you to log in to
    your Google account. Docker containers don't have browsers, so you
    MUST run this script directly on your host machine (your laptop/desktop).

HOW TO RUN:
    1. Make sure you have Python installed on your host machine
    2. Install the required package:
       pip install google-auth-oauthlib
    3. Run this script:
       python sentinel_flow_mvp/scripts/get_google_refresh_token.py
    4. Follow the instructions in your browser
    5. Copy the refresh token from the terminal output
    6. Paste it into sentinel_flow_mvp/.secrets.json as GOOGLE_OAUTH_REFRESH_TOKEN

WHAT TO EXPECT:
    - The script will open your default web browser
    - You'll see a Google login page
    - After logging in, you'll see a permissions screen
    - Click "Allow" to grant access
    - You'll be redirected to localhost (this is normal)
    - The terminal will display your refresh token
"""

import json
import os
import sys

# Check if google-auth-oauthlib is installed
try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    print("ERROR: google-auth-oauthlib is not installed.")
    print("Please install it by running: pip install google-auth-oauthlib")
    sys.exit(1)

# =============================================================================
# CONFIGURATION
# =============================================================================

# Path to the secrets file (relative to where this script is run)
SECRETS_PATH = os.path.join(os.path.dirname(__file__), "..", ".secrets.json")

# Google Drive file upload scope (minimal permissions needed for backups)
# This scope allows uploading files but NOT reading/deleting other files
SCOPES = ["https://www.googleapis.com/auth/drive.file"]

# OAuth2 flow settings
# "offline" access_type ensures we get a refresh token
# "consent" prompt forces the consent screen even if previously approved
CLIENT_CONFIG = {
    "web": {
        "client_id": None,  # Will be loaded from .secrets.json
        "client_secret": None,  # Will be loaded from .secrets.json
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }
}


def load_secrets():
    """Load OAuth credentials from .secrets.json"""
    secrets_path = os.path.abspath(SECRETS_PATH)

    if not os.path.exists(secrets_path):
        print(f"ERROR: Secrets file not found at {secrets_path}")
        print("Please create .secrets.json with your Google OAuth credentials first.")
        print("See .secrets.example.json for the required format.")
        sys.exit(1)

    with open(secrets_path, "r") as f:
        secrets = json.load(f)

    client_id = secrets.get("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = secrets.get("GOOGLE_OAUTH_CLIENT_SECRET")

    if not client_id or not client_secret:
        print("ERROR: GOOGLE_OAUTH_CLIENT_ID or GOOGLE_OAUTH_CLIENT_SECRET not found in .secrets.json")
        print("Please add these values first.")
        sys.exit(1)

    # Don't print the actual secret - just confirm it's loaded
    print(f"Loaded client ID: {client_id[:20]}...")
    print("Loaded client secret: [REDACTED]")

    return client_id, client_secret


def main():
    """Main function to get the refresh token"""
    print("=" * 70)
    print("GOOGLE OAUTH REFRESH TOKEN SETUP")
    print("=" * 70)
    print()
    print("This script will help you get a refresh token for automated backups.")
    print()
    print("INSTRUCTIONS:")
    print("1. A browser window will open (or a URL will be printed)")
    print("2. Log in to your Google account")
    print("3. Click 'Allow' to grant backup permissions")
    print("4. Copy the refresh token from this terminal")
    print("5. Paste it into sentinel_flow_mvp/.secrets.json")
    print()
    print("=" * 70)
    print()

    # Load credentials from .secrets.json
    client_id, client_secret = load_secrets()
    print()

    # Update the client config with loaded credentials
    CLIENT_CONFIG["web"]["client_id"] = client_id
    CLIENT_CONFIG["web"]["client_secret"] = client_secret

    # Create the OAuth2 flow
    flow = InstalledAppFlow.from_client_config(
        client_config=CLIENT_CONFIG,
        scopes=SCOPES,
    )

    # Run the local server flow
    # port=0 lets the OS pick an available port
    # If running in a container without a browser, this will print a URL
    print("Starting OAuth2 flow...")
    print()

    try:
        credentials = flow.run_local_server(
            port=0,
            prompt="consent",  # Force consent screen to get refresh token
            access_type="offline",  # Request offline access for refresh token
        )

        print()
        print("=" * 70)
        print("SUCCESS! Your refresh token has been generated.")
        print("=" * 70)
        print()
        print("YOUR REFRESH TOKEN:")
        print()
        print(f"  {credentials.refresh_token}")
        print()
        print("=" * 70)
        print()
        print("NEXT STEPS:")
        print("1. Copy the refresh token above")
        print("2. Open sentinel_flow_mvp/.secrets.json")
        print("3. Replace 'YOUR_REFRESH_TOKEN_HERE' with the token above")
        print("4. You can delete this script after copying the token")
        print()
        print("NOTE: This token will not expire. Keep it secure!")
        print()

    except Exception as e:
        print()
        print("ERROR: Failed to complete OAuth flow")
        print(f"Error details: {e}")
        print()
        print("TROUBLESHOOTING:")
        print("- Make sure you're running this on your host machine (not Docker)")
        print("- Make sure port 8080 is available")
        print("- Try running: pip install --upgrade google-auth-oauthlib")
        print()
        sys.exit(1)


if __name__ == "__main__":
    main()
