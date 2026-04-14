# XuanWu

This guide describes how to deploy XuanWu in your own environment using pre-built Docker images.

## Prerequisites

### System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU | 2 cores | 4+ cores |
| RAM | 4 GB | 8+ GB |
| Disk | 20 GB SSD | 100+ GB SSD |
| OS | Linux (CentOS Stream 9+, RHEL 8+, Ubuntu 22.04+, Debian 12+) | Latest LTS |

### Required Software

- **Docker Engine** 24.0 or higher
- **Docker Compose** 2.0 or higher (included as Docker plugin)

### Install Docker

**CentOS Stream 9 / RHEL 8+ / RHEL 9:**
```bash
sudo dnf -y install dnf-plugins-core

# CentOS Stream 9:
sudo dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
# RHEL 8 / RHEL 9:
# sudo dnf config-manager --add-repo https://download.docker.com/linux/rhel/docker-ce.repo

sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
```

**Ubuntu 22.04+ / Debian 12+:**
```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

# For Debian, replace "ubuntu" with "debian" in the URLs above and below
sudo tee /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

**Verify Installation:**
```bash
docker --version
docker compose version
```

---

## Quick Start

### 1. Create Deployment Directory

```bash
mkdir -p /opt/xuanwu/{workspace,data}
cd /opt/xuanwu
```

**Directory Structure:**

```
/opt/xuanwu/
├── docker-compose.yml      # Docker Compose orchestration file
├── workspace/              # Configuration, logs, user data
│   └── xuanwu.json      # Main configuration file
├── data/                   # SQLite database and runtime data
```

### 2. Download Compose File

```bash
curl -o docker-compose.yml https://raw.githubusercontent.com/CloudChef/xuanwu/main/build/docker-compose.yml
```

### 3. Skills Strategy (Built-In + Downloaded)

No external providers repository is required.

XuanWu uses a hybrid strategy:

- Built-in skills/channels/providers shipped in image:
  - `/app/app/xuanwu/skills`
  - `/app/app/xuanwu/channels`
  - `/app/app/xuanwu/providers` (optional provider template root)
- User-downloaded skills/channels loaded from workspace paths:
  - `/app/workspace/skills`
  - `/app/workspace/channels`

### 4. Configure LLM Model (Required)

**⚠️ You MUST configure at least one LLM token before starting XuanWu.**

The service will fail to start without a valid model configuration. Tokens can be added via:
- Configuration file (xuanwu.json) - for initial setup
- Web UI (Admin Panel) - for runtime management via CRUD

#### Supported LLM Providers

| Provider | Model Example | base_url | api_type |
|----------|---------------|----------|----------|
| DeepSeek | deepseek-chat | https://api.deepseek.com | openai |
| OpenAI | gpt-4 | https://api.openai.com/v1 | openai |
| Moonshot (Kimi) | kimi-k2.5 | https://api.moonshot.cn/v1 | openai |

### 5. Create Configuration

Create `/opt/xuanwu/workspace/xuanwu.json`:

```json
{
  "workspace": {
    "path": "/app/workspace"
  },
  "database": {
    "type": "sqlite",
    "sqlite": {
      "path": "/app/data/xuanwu.db"
    }
  },
  "skills_root": "/app/workspace/skills",
  "channels_root": "/app/workspace/channels",
  "model": {
    "primary": "deepseek-main",
    "fallbacks": [],
    "temperature": 0.2,
    "tokens": [
      {
        "id": "deepseek-main",
        "provider": "deepseek",
        "model": "deepseek-chat",
        "base_url": "https://api.deepseek.com",
        "api_key": "YOUR_API_KEY_HERE",
        "api_type": "openai"
      }
    ]
  },
  "auth": {
    "provider": "local",
    "local": {
      "enabled": true,
      "default_admin_username": "admin",
      "default_admin_password": "admin"
    },
    "jwt": {
      "secret_key": "xuanwu-docker-secret-CHANGE-ME",
      "expires_minutes": 480
    }
  }
}
```

**⚠️ Critical Configuration Requirements:**

1. **You MUST replace `YOUR_API_KEY_HERE`** with your actual LLM API key (e.g., DeepSeek, OpenAI)
2. **`model.tokens` cannot be empty** - At least one token entry is **required** for startup
3. **`skills_root`** and **`channels_root`** should point to writable workspace paths for user-downloaded content: `/app/workspace/skills`, `/app/workspace/channels`
4. Database path uses container path `/app/data/xuanwu.db`
5. `workspace.path` should use container path `/app/workspace`

**Example with real API key:**
```json
{
  "model": {
    "primary": "deepseek-main",
    "tokens": [
      {
        "id": "deepseek-main",
        "provider": "deepseek",
        "model": "deepseek-chat",
        "base_url": "https://api.deepseek.com",
        "api_key": "sk-abc123xyz...",
        "api_type": "openai"
      }
    ]
  }
}
```

Set proper permissions:
```bash
chmod 600 /opt/xuanwu/workspace/xuanwu.json
```

### 6. Start XuanWu

```bash
cd /opt/xuanwu
docker compose up -d
```

### 7. Verify Deployment

```bash
curl http://localhost:9000/api/health
```

Expected response:
```json
{"status": "healthy", "timestamp": "2026-03-23T10:00:00+00:00"}
```

Access the web UI at: `http://your-server-ip:9000`

---

## Optional: Skills & Channels Configuration

Built-in skills/channels are auto-loaded from `/app/app/xuanwu/*`.
User-downloaded skills/channels are loaded from `/app/workspace/*` by default.
You can still override `skills_root` / `channels_root` in `xuanwu.json`.

### Skill Structure

**Markdown Skill:**
```
/opt/xuanwu/workspace/skills/
└── deployment/
    ├── SKILL.md             # Skill definition
    ├── requirements.txt     # Dependencies (optional)
    └── scripts/
        └── deploy.sh        # Helper scripts (optional)
```

**Executable Skill:**
```
/opt/xuanwu/workspace/skills/
└── monitoring/
    ├── __init__.py
    ├── skill.py             # Python implementation
    ├── requirements.txt     # Dependencies
    └── config.json
```

### Channel Configuration

Add to `/opt/xuanwu/workspace/xuanwu.json`:

```json
{
  "channels": {
    "slack-bot": {
      "type": "slack",
      "config": {
        "token": "xoxb-your-bot-token",
        "signing_secret": "your-signing-secret"
      }
    }
  }
}
```

### Reload Skills/Channels

```bash
docker compose restart xuanwu
```

---

## Operations

### View Logs

```bash
docker compose logs -f xuanwu
```

### Stop Services

```bash
docker compose down
```

### Update to Latest Version

```bash
docker compose pull
docker compose up -d
```

### Backup

```bash
# Backup data and config
tar -czf xuanwu-backup-$(date +%Y%m%d).tar.gz /opt/xuanwu/data /opt/xuanwu/workspace
```

---

## Configuration Reference

### LLM Provider

```json
{
  "model": {
    "primary": "deepseek-main",
    "tokens": [
      {
        "id": "deepseek-main",
        "provider": "deepseek",
        "model": "deepseek-chat",
        "base_url": "https://api.deepseek.com",
        "api_key": "your-api-key"
      }
    ]
  }
}
```

### Authentication (Local Username/Password)

```json
{
  "auth": {
    "provider": "local",
    "local": {
      "enabled": true,
      "default_admin_username": "admin",
      "default_admin_password": "admin"
    },
    "jwt": {
      "secret_key": "xuanwu-docker-secret-CHANGE-ME",
      "expires_minutes": 480
    }
  }
}
```

---

## Troubleshooting

### Container Won't Start

```bash
# Check logs
docker compose logs xuanwu

# Verify config syntax
docker run --rm -v /opt/xuanwu/workspace/xuanwu.json:/app/xuanwu.json:ro registry.cn-shanghai.aliyuncs.com/xuanwu/xuanwu:latest python -c "import json; json.load(open('/app/xuanwu.json'))"
```

### Built-In Roots Verification

```bash
cat /opt/xuanwu/workspace/xuanwu.json | grep -E "skills_root|channels_root"
ls -la /opt/xuanwu/workspace/skills/
ls -la /opt/xuanwu/workspace/channels/
ls -la /app/app/xuanwu/skills/
```

### Port Already in Use

Edit `docker-compose.yml`:

```yaml
ports:
  - "8080:9000"  # Change 8080 to your preferred port
```

### Permission Denied

```bash
chmod 600 /opt/xuanwu/workspace/xuanwu.json
chown -R $(id -u):$(id -g) /opt/xuanwu/data
```

---

## Support

For technical support, contact your XuanWu representative or refer to the full documentation at [docs link].
