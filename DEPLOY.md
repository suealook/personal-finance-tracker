# Deploying to Oracle Cloud (Always Free)

Two systemd services (bot + web) behind a Caddy reverse proxy that terminates
HTTPS, on an Oracle Cloud "Always Free" VM. No domain required — Caddy
self-signs a certificate for the VM's IP, same one-time "trust this
certificate" step per device as any self-signed setup. If you get a free
domain later (e.g. from [DuckDNS](https://www.duckdns.org/)), see the note
at the bottom to upgrade to a real, browser-trusted certificate for free.

## 1. Create the VM

1. Sign up at [cloud.oracle.com](https://www.oracle.com/cloud/free/) (free tier, no charge unless you explicitly upgrade).
2. **Compute → Instances → Create Instance.**
3. **Image and shape** → Edit → choose **Ampere (ARM) → VM.Standard.A1.Flex**, 2-4 OCPUs / 12-24 GB RAM (still within the Always Free allowance, comfortably more than this app needs). Image: **Ubuntu 24.04** (or 22.04).
4. **Networking**: use the default VCN, and tick **"Assign a public IPv4 address."**
5. **Add SSH keys**: let Oracle generate a key pair and download the private key (or paste your own public key if you already have one).
6. Create the instance. Note its **public IP address** once it's running.

## 2. Open the firewall (two layers — both need it)

Oracle VMs have **two** independent firewalls; a port closed on either one blocks traffic.

**a) Cloud-level (Security List / Network Security Group):**
Networking → Virtual Cloud Networks → your VCN → your subnet → Security Lists → Default Security List → **Add Ingress Rules**:
- Source CIDR `0.0.0.0/0`, IP Protocol TCP, Destination Port `443` (HTTPS)
- (Port 22/SSH is already open by default)

**b) OS-level firewall (Ubuntu's `iptables`, pre-configured restrictively on Oracle's images):**
```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

## 3. Connect and install dependencies

```bash
ssh -i /path/to/downloaded/key.pem ubuntu@<your-vm-ip>
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

Copy your Google service account key to `data/credentials/service_account.json`
(e.g. `scp` it from your own machine), and set up `.env`:

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

Copy the two unit files from `deploy/` into place:
```bash
sudo cp deploy/finance-web.service deploy/finance-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now finance-web finance-bot
sudo systemctl status finance-web finance-bot
```

Both files assume the repo lives at `/home/ubuntu/personal-finance` and run as
the `ubuntu` user — edit `User=`/`WorkingDirectory=`/`ExecStart=` in both
files first if yours differs.

## 7. Caddy (HTTPS reverse proxy)

```bash
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
sudo systemctl restart caddy
```

## 8. Visit it

```
https://<your-vm-ip>
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
record at the VM's public IP, replace `deploy/Caddyfile`'s `:443` block with:

```
yourname.duckdns.org {
	reverse_proxy 127.0.0.1:5000
}
```

Caddy will automatically get and renew a real Let's Encrypt certificate —
no more "not private" warnings on any device, ever, and nothing else about
the deployment changes.
