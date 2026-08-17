# SIN Chatbot — AWS EC2 Deployment Guide

Complete checklist for deploying to an AWS EC2 instance running Amazon Linux 2023 (ARM64 / Graviton).

**Target server**: `35.87.248.186` | User: `siemens` | Instance: `t4g.xlarge` (4 vCPU, 16 GiB RAM, 100 GB disk)

---

## 1. Connect to the Server

```bash
# Set correct permissions on the SSH key (required, only once)
chmod 600 siemens_ed25519

# Connect
ssh -i siemens_ed25519 siemens@35.87.248.186
```

---

## 2. Install Prerequisites on Amazon Linux 2023

Run all commands below on the server.

### 2.1 System packages

```bash
# Update system
sudo dnf update -y

# Install Docker
sudo dnf install -y docker

# Start Docker and enable on boot
sudo systemctl enable docker
sudo systemctl start docker

# Add your user to the docker group (avoids needing sudo for docker commands)
sudo usermod -aG docker siemens

# IMPORTANT: Log out and log back in for the group change to take effect
exit
# then SSH back in
```

### 2.2 Docker Compose plugin

```bash
# Install the Docker Compose plugin
sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo curl -SL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-aarch64" \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# Verify
docker compose version
```

### 2.3 Git

```bash
sudo dnf install -y git
```

### 2.4 Python 3 and pip

```bash
# Amazon Linux 2023 includes Python 3.9+ by default
python3 --version

# Install pip if not present
sudo dnf install -y python3-pip

# Upgrade pip
pip3 install --upgrade pip
```

---

## 3. Clone the Repository

```bash
cd ~
git clone https://github.com/aaslanemre/sin-chatbotv1.0.git sin-chatbot
cd sin-chatbot
git checkout v6.0
```

---

## 4. Create the Environment File

**Never commit this file.** It contains secrets (API keys, passwords, access codes).

```bash
cp .env.example .env.v3
nano .env.v3
```

Fill in every variable. At minimum, set these to real values:

```bash
# REQUIRED — your Google Gemini API key
GOOGLE_API_KEY=your_real_api_key_here

# REQUIRED — change from the default
POSTGRES_PASSWORD=a_strong_random_password

# REQUIRED — change these to your own codes
ACCESS_CODE=your_user_access_code
ADMIN_ACCESS_CODE=your_admin_access_code
```

All other variables have sensible defaults. See `.env.example` for the full list with descriptions.

---

## 5. Migrate the Qdrant Vector Database

The Qdrant collection contains your indexed PDF documents. You need to export it from your local machine and import it on the server.

### 5.1 On your LOCAL machine

```bash
cd ~/Desktop/streamlit-rag-v1.0.0/sin_chatbot

# Export the Qdrant volume to a tarball
bash deploy/export_qdrant.sh

# Copy the tarball to the server
scp -i siemens_ed25519 qdrant_backup.tar.gz siemens@35.87.248.186:~/
```

### 5.2 On the SERVER

```bash
cd ~/sin-chatbot

# Import the tarball into the Docker volume
bash deploy/import_qdrant.sh ~/qdrant_backup.tar.gz
```

---

## 6. Copy Source PDFs (Optional)

The source PDFs are not required for the app to run (the vectors are already in Qdrant). However, keeping them on the server allows re-ingestion and admin panel document management.

```bash
# On your LOCAL machine — copy the docs folder
scp -i siemens_ed25519 -r docs/ siemens@35.87.248.186:~/sin-chatbot/docs/
```

---

## 7. Start Docker Services

```bash
cd ~/sin-chatbot

# Start Qdrant and PostgreSQL
docker compose -f docker-compose.prod.yml up -d

# Verify both containers are running and healthy
docker compose -f docker-compose.prod.yml ps
```

Wait 15-20 seconds for healthchecks to pass. You should see both services as `healthy`:

```
NAME                    STATUS              PORTS
sin_chatbot_postgres    Up (healthy)        127.0.0.1:5433->5432/tcp
sin_chatbot_qdrant      Up (healthy)        127.0.0.1:6333->6333/tcp, 127.0.0.1:6334->6334/tcp
```

---

## 8. Install Python Dependencies

```bash
cd ~/sin-chatbot

# Install all Python packages
pip3 install --user -r requirements.txt
```

> **Note**: On ARM64, all packages have pre-built wheels. If any package fails to install, install build tools: `sudo dnf install -y gcc python3-devel`

---

## 9. Install and Enable systemd Services

```bash
# Copy service files to systemd directory
sudo cp deploy/sin-chatbot-user.service /etc/systemd/system/
sudo cp deploy/sin-chatbot-admin.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable services to start on boot
sudo systemctl enable sin-chatbot-user
sudo systemctl enable sin-chatbot-admin

# Start both services
sudo systemctl start sin-chatbot-user
sudo systemctl start sin-chatbot-admin

# Verify they are running
sudo systemctl status sin-chatbot-user
sudo systemctl status sin-chatbot-admin
```

---

## 10. Configure AWS Security Group

In the AWS Console, go to **EC2 > Security Groups** and edit the inbound rules for your instance:

| Type       | Port  | Source        | Description                          |
|------------|-------|---------------|--------------------------------------|
| SSH        | 22    | Your IP /32   | SSH access (restrict to known IPs)   |
| Custom TCP | 8501  | 0.0.0.0/0     | User app (public)                    |

**Port 8503 must NOT be opened.** The admin app binds to `127.0.0.1` and is only accessible via SSH tunnel. Opening port 8503 in the security group would have no effect (the app won't respond on the public interface), but keeping it closed is defense-in-depth.

---

## 11. Access the Admin Panel via SSH Tunnel

The admin app is not exposed to the internet. To access it:

```bash
# On your LOCAL machine — create an SSH tunnel
ssh -i siemens_ed25519 -L 8503:localhost:8503 siemens@35.87.248.186

# Keep this terminal open. Then in your browser, open:
# http://localhost:8503
```

This forwards your local port 8503 to the server's localhost:8503 through the encrypted SSH connection.

---

## 12. Verification Checklist

Run these on the server to confirm everything is working:

```bash
# 1. Qdrant — check collection exists and has vectors
curl -s http://localhost:6333/collections/sin_docs | python3 -m json.tool
# Look for: "points_count" should be > 0

# 2. PostgreSQL — check tables were created
docker exec sin_chatbot_postgres psql -U sinchatbot -d sin_chatbot -c "\dt"
# Should list: users, chat_logs, sessions, documents

# 3. User app — check it responds
curl -s -o /dev/null -w "%{http_code}" http://localhost:8501
# Should return: 200

# 4. Admin app — check it responds on localhost
curl -s -o /dev/null -w "%{http_code}" http://localhost:8503
# Should return: 200

# 5. Admin app — confirm it does NOT respond on public IP
curl -s --connect-timeout 3 -o /dev/null -w "%{http_code}" http://35.87.248.186:8503
# Should timeout or refuse connection

# 6. Test signup — open http://35.87.248.186:8501 in your browser
#    and create a test account using your ACCESS_CODE
```

---

## 13. Deploying Future Updates

```bash
# SSH into the server
ssh -i siemens_ed25519 siemens@35.87.248.186

# Pull latest code
cd ~/sin-chatbot
git pull origin v6.0

# Reinstall dependencies (only if requirements.txt changed)
pip3 install --user -r requirements.txt

# Restart the apps
sudo systemctl restart sin-chatbot-user
sudo systemctl restart sin-chatbot-admin

# If docker-compose.prod.yml changed:
docker compose -f docker-compose.prod.yml up -d
```

---

## 14. Troubleshooting

### View app logs

```bash
# User app logs (live)
sudo journalctl -u sin-chatbot-user -f

# Admin app logs (live)
sudo journalctl -u sin-chatbot-admin -f

# Last 50 lines of user app logs
sudo journalctl -u sin-chatbot-user -n 50

# Docker service logs
docker compose -f docker-compose.prod.yml logs -f
docker compose -f docker-compose.prod.yml logs qdrant
docker compose -f docker-compose.prod.yml logs postgres
```

### App won't start

```bash
# Check service status for error details
sudo systemctl status sin-chatbot-user

# Common causes:
# - .env.v3 missing or misconfigured
# - Docker services not running: docker compose -f docker-compose.prod.yml ps
# - Python packages missing: pip3 install --user -r requirements.txt
# - Wrong branch: git branch (should show v6.0)
```

### Qdrant is empty after migration

```bash
# Check the volume was imported correctly
docker volume ls | grep qdrant

# Re-import if needed
bash deploy/import_qdrant.sh ~/qdrant_backup.tar.gz

# Restart Qdrant
docker compose -f docker-compose.prod.yml restart qdrant
```

### PostgreSQL connection refused

```bash
# Check Postgres is running
docker compose -f docker-compose.prod.yml ps postgres

# Check password matches .env.v3
grep POSTGRES_PASSWORD .env.v3

# Test connection manually
docker exec sin_chatbot_postgres psql -U sinchatbot -d sin_chatbot -c "SELECT 1"
```

### Can't access admin panel

```bash
# Make sure you're using SSH tunnel (NOT the public IP)
ssh -i siemens_ed25519 -L 8503:localhost:8503 siemens@35.87.248.186

# Then open http://localhost:8503 in your browser
# NOT http://35.87.248.186:8503
```

### Restart everything from scratch

```bash
# Stop apps
sudo systemctl stop sin-chatbot-user sin-chatbot-admin

# Restart Docker services
docker compose -f docker-compose.prod.yml down
docker compose -f docker-compose.prod.yml up -d

# Wait for healthy status
sleep 15
docker compose -f docker-compose.prod.yml ps

# Start apps
sudo systemctl start sin-chatbot-user sin-chatbot-admin
```

---

## Architecture Summary

```
Internet
   |
   v
[ AWS Security Group ]
   |
   | Port 8501 (open)        Port 8503 (closed)
   v                              |
+---------------------------+     |
| Streamlit User App        |     |
| (systemd, 0.0.0.0:8501)  |     |
+---------------------------+     |
                                  |
         SSH Tunnel ──────────────+
                                  |
                                  v
                    +---------------------------+
                    | Streamlit Admin App        |
                    | (systemd, 127.0.0.1:8503) |
                    +---------------------------+
                              |
           +------------------+------------------+
           |                                     |
           v                                     v
+---------------------+             +---------------------+
| Qdrant              |             | PostgreSQL          |
| 127.0.0.1:6333      |             | 127.0.0.1:5433      |
| (Docker, arm64)     |             | (Docker, arm64)     |
+---------------------+             +---------------------+
```
