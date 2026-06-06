# Ouroboros Cloud + iPhone Runbook

This runbook keeps the bot and Streamlit dashboard running on a cloud VM
so your PC can stay offline.

## 1. Recommended baseline (cost-aware)

- VM: Linux instance (Ubuntu 22.04+)
- Python: 3.10+
- Runtime manager: `systemd`
- Reverse proxy / TLS: optional (`nginx` or cloud LB)

Free tiers change often by provider policy. Check current terms before use.

## 2. Install dependencies

```bash
cd ~/trading_bot/trading_bot/MAIN
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install streamlit pandas numpy plotly
```

### Ubuntu quick setup (safe, one-shot)

```bash
cd ~/trading_bot/trading_bot/MAIN
chmod +x ./tools/cloud_ubuntu_setup.sh
./tools/cloud_ubuntu_setup.sh --with-secrets
```

Notes:
- This setup also installs the git `post-commit` hook for dashboard change-log auto-record.
- To skip hook install: `./tools/cloud_ubuntu_setup.sh --with-secrets --skip-git-hook`
- To include ngrok service: `./tools/cloud_ubuntu_setup.sh --with-secrets --with-ngrok-service`
- To include trade notifier timer: `./tools/cloud_ubuntu_setup.sh --with-secrets --with-trade-notifier-service`
- To include weekly report -> AI auto-feedback timer: `./tools/cloud_ubuntu_setup.sh --with-secrets --with-weekly-autotrain-service`

## 3. Service files

Copy these templates (adjust paths):

- `deploy/systemd/ouroboros-bot.service`
- `deploy/systemd/ouroboros-dashboard.service`
- (optional) `deploy/systemd/ouroboros-ngrok.service`
- (optional) `deploy/systemd/ouroboros-trade-notifier.service` + `.timer`
- (optional) `deploy/systemd/ouroboros-weekly-autotrain.service` + `.timer`

Then:

```bash
sudo cp deploy/systemd/ouroboros-bot.service /etc/systemd/system/
sudo cp deploy/systemd/ouroboros-dashboard.service /etc/systemd/system/
# optional: create secrets file (outside repo, 600 permission)
sudo ./tools/register_cloud_secrets_env.sh /etc/ouroboros/secrets.env
sudo systemctl daemon-reload
sudo systemctl enable --now ouroboros-bot.service
sudo systemctl enable --now ouroboros-dashboard.service

# health check
./tools/cloud_systemd_healthcheck.sh
# include API preflight
./tools/cloud_systemd_healthcheck.sh --run-preflight
```

## 4. iPhone access

- Preferred (local HTTPS): run `tools/start_dashboard_https.sh`.
- Then open `https://<your-domain-or-ip>:8501` in Safari.
- Use "Add to Home Screen" to create an app-like icon.
- Keep dashboard behind auth/reverse-proxy if exposed to internet.

### Local HTTPS quick start

```bash
cd ~/trading_bot/trading_bot/MAIN
./tools/start_dashboard_https.sh
```

- If `mkcert` is installed, the script creates a locally trusted cert.
- If `mkcert` is missing, it falls back to a self-signed cert.
- For self-signed certs, Safari may warn; trust/install the cert or use mkcert.

### Recommended: mkcert for trusted local HTTPS

```bash
brew install mkcert
mkcert -install
cd ~/trading_bot/trading_bot/MAIN
./tools/start_dashboard_https.sh
```

If iPhone still warns:

1. Export/install mkcert root CA to iPhone (via AirDrop or Files).
2. iPhone Settings -> General -> VPN & Device Management -> install profile.
3. iPhone Settings -> General -> About -> Certificate Trust Settings -> enable full trust.

If you see "server connection failed":

1. Confirm Streamlit binds to `0.0.0.0`:
   - `python -m streamlit run dashboard.py --server.address 0.0.0.0 --server.port 8501`
2. Check port listening on host:
   - `lsof -iTCP:8501 -sTCP:LISTEN`
3. Check firewall/security-group allows TCP 8501.
4. From iPhone (same Wi-Fi), open `https://<host-lan-ip>:8501`.
5. If using cloud, prefer HTTPS via reverse proxy (nginx/Caddy).

### Free option: ngrok HTTPS (for iPhone + Google login test)

1. Install ngrok and authenticate agent:

```bash
brew install ngrok
ngrok config add-authtoken <YOUR_NGROK_AUTHTOKEN>
```

2. Start dashboard + ngrok in one command:

```bash
cd ~/trading_bot/trading_bot/MAIN
./tools/start_dashboard_ngrok.sh
```

3. The script prints:
- `public url` (open this on iPhone)
- `redirect_uri` (`<public-url>/oauth2callback`)
- and updates `MAIN/.streamlit/secrets.toml` `redirect_uri` automatically.

4. For Google OIDC, set the same redirect URI in Google Cloud OAuth client.

Notes:
- ngrok free shows a browser warning page once per browser/endpoint every 7 days.
- free plan limits are small (request/data/month, domains/users/OIDC MAU). Verify current limits in ngrok docs before production use.
- if your ngrok URL changes, update both:
  - `MAIN/.streamlit/secrets.toml` `redirect_uri`
  - Google OAuth "Authorized redirect URIs"

## 5. Operational notes

- Run `tools/live_preflight.py` after key changes.
- Keep `safety_hard_block=1` as emergency stop.
- Use dashboard "Tool" actions for `run_check.sh` and `ci_check.py`.
- Dashboard login user setup (required):

```bash
cd ~/trading_bot/trading_bot/MAIN
python3 tools/create_dashboard_user.py --username admin
```

- To rotate password, run the same command again with the same username.

### bitFlyer API key (recommended secure registration)

Use Keychain and avoid plain text in shell history:

```bash
cd ~/trading_bot/trading_bot/MAIN
./tools/register_bitflyer_keychain.sh
python3 tools/live_preflight.py
```

Cloud/Linux (`systemd`) recommended:

```bash
cd ~/trading_bot/trading_bot/MAIN
sudo ./tools/register_cloud_secrets_env.sh /etc/ouroboros/secrets.env
sudo systemctl restart ouroboros-bot.service
sudo systemctl restart ouroboros-dashboard.service
python3 tools/live_preflight.py
```

Alternative (GUI):
- Keychain Access.app -> login -> Passwords
- Add item 1:
  - Name: `ouroboros.bitflyer`
  - Account: `api_key`
  - Password: `<BITFLYER_API_KEY>`
- Add item 2:
  - Name: `ouroboros.bitflyer`
  - Account: `api_secret`
  - Password: `<BITFLYER_API_SECRET>`

Security notes:
- Never store exchange API keys in repo files (`secrets.toml`, `.env`, source files, git).
- Cloud is allowed to use `/etc/ouroboros/secrets.env` only (outside repo, `chmod 600`).
- If you pasted keys into chat/terminal/history before, revoke and reissue keys immediately.
- Prefer Keychain Access Control = "Confirm before allowing access". Avoid "Always Allow".

### Apple Account login (OIDC) + login notifications

1. Install auth dependency:

```bash
cd ~/trading_bot/trading_bot/MAIN
pip install streamlit[auth]
```

2. Create `MAIN/.streamlit/secrets.toml`:

```toml
[auth]
redirect_uri = "https://<YOUR_HOST>:8501/oauth2callback"
cookie_secret = "<RANDOM_32+_BYTES>"

[auth.apple]
client_id = "<APPLE_SERVICE_ID>"
client_secret = "<APPLE_CLIENT_SECRET_JWT>"
server_metadata_url = "https://appleid.apple.com/.well-known/openid-configuration"

[dashboard_security]
login_notify_enabled = true
ntfy_topic_url = "https://ntfy.sh/<PRIVATE_TOPIC>"
# Optional generic webhook:
# login_notify_webhook_url = "https://example.com/your/webhook"
# login_notify_bearer_token = "<TOKEN>"
```

3. Set dashboard auth mode to OIDC (Apple only):

```bash
cd ~/trading_bot/trading_bot/MAIN
python3 tools/create_dashboard_user.py --username breakglass --mode OIDC --oidc-provider apple
```

Notes:
- Keep one local `breakglass` user for emergency recovery.
- If OIDC fails temporarily, set `mode` to `AUTO` or `LOCAL`.
- `redirect_uri` must exactly match Apple developer settings.

## 6. One-shot canary auto-start (macOS launchd)

Schedule exactly one canary live test for a specific date/time.

Install for tomorrow 10:05:

```bash
cd ~/trading_bot/trading_bot/MAIN
chmod +x tools/canary_live_window_test.sh \
         tools/canary_live_once_wrapper.sh \
         tools/install_canary_launchagent_once.sh \
         tools/uninstall_canary_launchagent_once.sh

./tools/install_canary_launchagent_once.sh \
  --date "$(date -v+1d +%Y-%m-%d)" \
  --hour 10 \
  --minute 5 \
  --duration-sec 600 \
  --interval-sec 60 \
  --lot 0.001
```

Behavior:
- Wrapper starts `tools/canary_live_window_test.sh`.
- `CONTROL.csv` is restored automatically after run.
- LaunchAgent unloads itself and deletes plist after execution.

Logs:
- `MAIN/ci_logs/canary_once_YYYYMMDD.log`
- `MAIN/ci_logs/launchd_canary_once_out.log`
- `MAIN/ci_logs/launchd_canary_once_err.log`

Remove scheduled job manually:

```bash
cd ~/trading_bot/trading_bot/MAIN
./tools/uninstall_canary_launchagent_once.sh
```
