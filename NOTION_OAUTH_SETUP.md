# Notion OAuth Setup

This app now uses Notion OAuth instead of pasting a Notion API key.

## 1) Create a Notion OAuth integration

1. Go to Notion integrations and create a public OAuth integration.
2. Copy your `Client ID` and `Client Secret`.
3. Add this redirect URI in Notion settings:
   - `http://127.0.0.1:8765/notion/oauth/callback`

Note:
- Default callback port is `8765`.
- You can change it with environment variable `NOTION_OAUTH_CALLBACK_PORT`.
- If you change that port, add the exact matching URI in Notion integration settings.

## 2) Connect from the app

1. Open `Integrations` tab.
2. In `Notion`, enter `Notion OAuth Client ID` and `Notion OAuth Client Secret`.
3. Optional: add `Parent Page ID` if you want all meeting pages under a specific template/root page.
4. Click `Connect Notion OAuth`.
5. Approve access in your browser and return to the app.
6. Click `Save Integrations`.

## 3) Recommended template flow

1. Create a Notion template page (for example `Meeting Hub`) with any nested databases you want.
2. During OAuth approval, grant access to that page.
3. Save that template page ID in `Parent Page ID`.

With this, the app can keep creating meeting pages under your approved area without asking users for raw API keys.
