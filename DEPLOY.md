# Deploying to Google Cloud (Always Free e2-micro)

Two systemd services (bot + web) behind a Caddy reverse proxy that terminates
HTTPS, on a GCP "Always Free" VM. No domain required — Caddy self-signs a
certificate for the VM's IP, same one-time "trust this certificate" step per
device as any self-signed setup. If you get a free domain later (e.g. from
[DuckDNS](https://www.duckdns.org/)), see the note at the bottom to upgrade
to a real, browser-trusted certificate for free.

## 1. Create the VM

1. Sign up at [console.cloud.google.com](https://console.cloud.google.com/) and create a project. GCP requires a credit card on file even for the free tier — you won't be charged unless you exceed the free allowance or explicitly upgrade.
2. **Compute Engine → VM instances → Create Instance.**
3. **Name**: anything, e.g. `personal-finance`.
4. **Region**: must be one of `us-west1`, `us-central1`, or `us-east1` — these are the only regions the Always Free e2-micro applies to. Pick whichever is closest to you.
5. **Machine type**: `e2-micro` (2 shared vCPU, 1 GB RAM) — the free-tier shape. This app is lightweight (mostly waiting on network calls), so this is plenty.
6. **Boot disk** → Change → **Ubuntu 24.04 LTS**, standard persistent disk, 30 GB or less (30 GB-months/month is the free allowance).
7. Leave the rest at defaults and **Create**. Note the VM's **external IP** once it's running.

## 2. Open the firewall

**VPC firewall rule** (GCP's equivalent of a security group):
VPC Network → Firewall → **Create Firewall Rule**:
- Name: `allow-https`
- Targets: All instances in the network (or tag your VM and target by tag)
- Source IPv4 range: `0.0.0.0/0`
- Protocols/ports: tcp, port `443`

SSH (port 22) is open to GCP's Identity-Aware Proxy range by default — the
**SSH button in the Cloud Console** (browser-based, no key setup needed) just
works out of the box. GCP's stock Ubuntu image has no extra OS-level firewall
blocking things by default, unlike some other providers — this one rule is
normally all you need.

## 3. Connect and install dependencies

Click the **SSH** button next to your VM in the Cloud Console (opens a
browser-based terminal, no key file to manage), then:

```bash
sudo apt update && sudo apt install -y python3 python3-venv python3-pip git curl
```

## 4. Install Caddy

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy
```

## 5. Get the app onto the VM

```bash
git clone https://github.com/<you>/<your-repo>.git ~/personal-finance
cd ~/personal-finance
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

Copy your Google service account key to `data/credentials/service_account.json`.
The Cloud Console's SSH window has an upload button (gear icon → **Upload
file**) — easiest way to get it onto the VM without dealing with `scp` keys.

Set up `.env`:
```bash
cp .env.example .env
nano .env
```

Fill in the same values as local dev, plus:
```
WEB_BIND_HOST=127.0.0.1
DASHBOARD_PASSWORD=<pick a real password>
```
(`WEB_BIND_HOST` stays loopback-only — Caddy is what's actually reachable
from the internet, forwarding to Flask internally. `DASHBOARD_PASSWORD` is
required as soon as anything's reachable beyond loopback, and Caddy makes
that true here.)

Initialize the sheet's tabs once, if you haven't already:
```bash
venv/bin/python scripts/init_sheet.py
```

## 6. systemd services

First, replace every `CHANGE_ME` in both files with your actual login
username (check with `whoami` — on GCP this is usually your Google
account's local username, not `ubuntu`) and confirm the repo path matches
where you cloned it in step 5:

```bash
cd ~/personal-finance
sed -i "s/CHANGE_ME/$(whoami)/g" deploy/finance-web.service deploy/finance-bot.service
sudo cp deploy/finance-web.service deploy/finance-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now finance-web finance-bot
sudo systemctl status finance-web finance-bot
```

## 7. Caddy (HTTPS reverse proxy)

```bash
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
sudo systemctl restart caddy
```

## 8. Visit it

```
https://<your-vm-external-ip>
```

First visit on each device: you'll get a "connection isn't private" warning
— expected for a self-signed certificate. Click through it (Chrome:
"Advanced" → "Proceed"; Safari: "Show Details" → "visit this website"), then
sign in with the `dashboard_password`/`dashboard_username` you set in `.env`.

## Updating later

```bash
cd ~/personal-finance
git pull
venv/bin/pip install -r requirements.txt  # only if requirements.txt changed
sudo systemctl restart finance-web finance-bot
```

## Checking logs

```bash
sudo journalctl -u finance-web -f     # web service, live
sudo journalctl -u finance-bot -f     # bot service, live
sudo journalctl -u caddy -f           # reverse proxy, live
```

## Upgrading to a real (browser-trusted) certificate later

If you get a free domain (e.g. `yourname.duckdns.org`) and point its DNS A
record at the VM's external IP, replace `deploy/Caddyfile`'s `:443` block with:

```
yourname.duckdns.org {
	reverse_proxy 127.0.0.1:5000
}
```

Caddy will automatically get and renew a real Let's Encrypt certificate —
no more "not private" warnings on any device, ever, and nothing else about
the deployment changes.
