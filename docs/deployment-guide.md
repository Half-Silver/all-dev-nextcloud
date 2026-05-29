# all-dev-nextcloud Deployment Guide

## Overview

**all-dev-nextcloud** is a snap package that provides a complete Nextcloud server with Apache, MySQL, PHP-FPM, and Redis. It offers a safe home for all your data with file storage, calendar, contacts, and collaboration features.

## Snap Information

- **Snap Name**: `all-dev-nextcloud`
- **Version**: git (auto-versioned)
- **Base**: core24
- **Confinement**: strict
- **Supported Architectures**: amd64, arm64, ppc64el

## Key Features

- Complete Nextcloud server (v32.0.9)
- Apache 2.4.67 web server
- MySQL 8.4.9 database
- PHP 8.3.31 with FPM
- Redis 8.2.6 for caching
- Built-in HTTPS support with Let's Encrypt
- Automatic certificate renewal
- Data import/export capabilities
- Cron job management
- Log rotation

## Services

The snap includes multiple services:
- `apache` - Web server daemon
- `mysql` - Database server
- `php-fpm` - PHP FastCGI Process Manager
- `redis-server` - Redis cache server
- `nextcloud-cron` - Background job processor
- `nextcloud-fixer` - Automatic maintenance
- `renew-certs` - Certificate renewal daemon
- `logrotate` - Log management

## Input Configuration Schema

```json
{
  "type": "object",
  "title": "Nextcloud Configuration",
  "required": [
    "admin-username",
    "admin-password"
  ],
  "properties": {
    "admin-username": {
      "type": "string",
      "title": "Admin Username",
      "default": "admin",
      "description": "Administrator username for Nextcloud"
    },
    "admin-password": {
      "type": "string",
      "title": "Admin Password",
      "default": "",
      "description": "Administrator password (minimum 8 characters)"
    },
    "trusted-domains": {
      "type": "string",
      "title": "Trusted Domains",
      "default": "",
      "description": "Comma-separated list of trusted domains"
    },
    "http-port": {
      "type": "number",
      "title": "HTTP Port",
      "default": 80,
      "description": "HTTP port for web access"
    },
    "https-port": {
      "type": "number",
      "title": "HTTPS Port",
      "default": 443,
      "description": "HTTPS port for secure web access"
    },
    "enable-https": {
      "type": "boolean",
      "title": "Enable HTTPS",
      "default": false,
      "description": "Enable HTTPS with Let's Encrypt"
    },
    "domain": {
      "type": "string",
      "title": "Domain Name",
      "default": "",
      "description": "Domain name for HTTPS certificate (required if HTTPS enabled)"
    },
    "email": {
      "type": "string",
      "title": "Admin Email",
      "default": "",
      "description": "Email for Let's Encrypt notifications"
    }
  },
  "description": "Configure Nextcloud server with admin credentials, ports, and HTTPS settings.",
  "dependencies": {
    "enable-https": {
      "oneOf": [
        {
          "properties": {
            "enable-https": {
              "const": false
            }
          }
        },
        {
          "properties": {
            "enable-https": {
              "const": true
            },
            "domain": {
              "type": "string",
              "minLength": 1
            },
            "email": {
              "type": "string",
              "format": "email"
            }
          },
          "required": ["domain", "email"]
        }
      ]
    }
  }
}
```

## CT Deployment Payload Template

```json
{
  "snaps": [
    {
      "name": "all-dev-nextcloud",
      "refresh": true
    }
  ],
  "snap_config": [
    {
      "snap": "all-dev-nextcloud",
      "settings": {
        "admin-username": "<ADMIN_USERNAME_FROM_FORM>",
        "admin-password": "<ADMIN_PASSWORD_FROM_FORM>",
        "trusted-domains": "<TRUSTED_DOMAINS_FROM_FORM>",
        "http-port": 80,
        "https-port": 443,
        "enable-https": false,
        "domain": "<DOMAIN_FROM_FORM>",
        "email": "<EMAIL_FROM_FORM>",
        "ct-node-id": "<ALL_APP_NODE_ID>",
        "ct-callback-url": "<ALL_APP_CALLBACK_URL>",
        "ct-deployment-id": "<ALL_APP_DEPLOYMENT_ID>"
      }
    }
  ],
  "ignore_failures": false,
  "pre_service_actions": [],
  "post_service_actions": [
    {
      "names": [
        "all-dev-nextcloud"
      ],
      "action": "restart"
    }
  ],
  "interface_connections": [
    {
      "plug": "all-dev-nextcloud:network",
      "slot": ":network",
      "action": "connect"
    },
    {
      "plug": "all-dev-nextcloud:network-bind",
      "slot": ":network-bind",
      "action": "connect"
    },
    {
      "plug": "all-dev-nextcloud:network-observe",
      "slot": ":network-observe",
      "action": "connect"
    },
    {
      "plug": "all-dev-nextcloud:removable-media",
      "slot": ":removable-media",
      "action": "connect"
    }
  ]
}
```

## Required Snap Interface Connections

The snap requires the following interface connections:

| Interface | Purpose |
|-----------|---------|
| `network` | Network access for web server and database |
| `network-bind` | Bind to network ports (80, 443) |
| `network-observe` | Monitor network status (optional) |
| `removable-media` | Access external storage for data |

## Post-Installation Setup

### 1. Initial Configuration

After installation, configure the snap:

```bash
# Set admin credentials
sudo snap set all-dev-nextcloud admin-username="admin"
sudo snap set all-dev-nextcloud admin-password="your-secure-password"

# Set trusted domains
sudo snap set all-dev-nextcloud trusted-domains="example.com,192.168.1.100"
```

### 2. Manual Installation (Alternative)

Instead of web-based setup, use the manual install command:

```bash
sudo all-dev-nextcloud.manual-install admin your-secure-password
```

### 3. Enable HTTPS (Optional)

To enable HTTPS with Let's Encrypt:

```bash
sudo all-dev-nextcloud.enable-https lets-encrypt example.com admin@example.com
```

Or with self-signed certificate:

```bash
sudo all-dev-nextcloud.enable-https self-signed example.com
```

### 4. Access Nextcloud

Open your browser and navigate to:
- HTTP: `http://<server-ip>` or `http://<domain>`
- HTTPS: `https://<domain>` (after enabling HTTPS)

## Configuration Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `admin-username` | string | admin | Administrator username |
| `admin-password` | string | - | Administrator password |
| `trusted-domains` | string | - | Comma-separated trusted domains |
| `http-port` | number | 80 | HTTP port |
| `https-port` | number | 443 | HTTPS port |
| `enable-https` | boolean | false | Enable HTTPS |
| `domain` | string | - | Domain for HTTPS certificate |
| `email` | string | - | Email for Let's Encrypt |

## Available Commands

### Administrative Commands

```bash
# Run occ commands
sudo all-dev-nextcloud.occ <command>

# Example: List users
sudo all-dev-nextcloud.occ user:list

# Example: Add user
sudo all-dev-nextcloud.occ user:add username

# Example: Enable app
sudo all-dev-nextcloud.occ app:enable calendar
```

### Database Management

```bash
# Access MySQL client
sudo all-dev-nextcloud.mysql-client

# Backup database
sudo all-dev-nextcloud.mysqldump nextcloud > backup.sql
```

### Data Management

```bash
# Export data
sudo all-dev-nextcloud.export

# Import data
sudo all-dev-nextcloud.import
```

### HTTPS Management

```bash
# Enable HTTPS
sudo all-dev-nextcloud.enable-https lets-encrypt example.com admin@example.com

# Disable HTTPS
sudo all-dev-nextcloud.disable-https

# Manually renew certificates
sudo all-dev-nextcloud.renew-certs
```

## Usage Examples

### Example 1: Basic Setup

```bash
# Install snap
sudo snap install all-dev-nextcloud

# Configure admin
sudo snap set all-dev-nextcloud admin-username="admin"
sudo snap set all-dev-nextcloud admin-password="SecurePass123"

# Set trusted domain
sudo snap set all-dev-nextcloud trusted-domains="192.168.1.100"

# Access at http://192.168.1.100
```

### Example 2: Production Setup with HTTPS

```bash
# Install snap
sudo snap install all-dev-nextcloud

# Manual installation
sudo all-dev-nextcloud.manual-install admin SecurePass123

# Set trusted domain
sudo snap set all-dev-nextcloud trusted-domains="cloud.example.com"

# Enable HTTPS
sudo all-dev-nextcloud.enable-https lets-encrypt cloud.example.com admin@example.com

# Access at https://cloud.example.com
```

### Example 3: Install Apps

```bash
# Enable calendar app
sudo all-dev-nextcloud.occ app:enable calendar

# Enable contacts app
sudo all-dev-nextcloud.occ app:enable contacts

# Enable mail app
sudo all-dev-nextcloud.occ app:enable mail

# List installed apps
sudo all-dev-nextcloud.occ app:list
```

## Monitoring and Logs

### View Service Status

```bash
# Check all services
sudo snap services all-dev-nextcloud

# View Apache logs
sudo snap logs all-dev-nextcloud.apache

# View MySQL logs
sudo snap logs all-dev-nextcloud.mysql

# View PHP-FPM logs
sudo snap logs all-dev-nextcloud.php-fpm
```

### Check System Status

```bash
# System status
sudo all-dev-nextcloud.occ status

# Check for issues
sudo all-dev-nextcloud.occ check
```

## Troubleshooting

### Issue: Cannot Access Web Interface

**Solution:**
```bash
# Check if services are running
sudo snap services all-dev-nextcloud

# Restart services
sudo snap restart all-dev-nextcloud

# Check firewall
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
```

### Issue: Database Connection Error

**Solution:**
```bash
# Restart MySQL
sudo snap restart all-dev-nextcloud.mysql

# Check MySQL status
sudo snap logs all-dev-nextcloud.mysql

# Verify database
sudo all-dev-nextcloud.mysql-client -e "SHOW DATABASES;"
```

### Issue: HTTPS Certificate Problems

**Solution:**
```bash
# Check certificate status
sudo all-dev-nextcloud.occ security:certificates

# Manually renew
sudo all-dev-nextcloud.renew-certs

# Check logs
sudo snap logs all-dev-nextcloud.renew-certs
```

### Issue: Storage Permission Denied

**Solution:**
```bash
# Connect removable-media interface
sudo snap connect all-dev-nextcloud:removable-media

# Verify connection
sudo snap connections all-dev-nextcloud
```

### Issue: Trusted Domain Error

**Solution:**
```bash
# Add trusted domain
sudo snap set all-dev-nextcloud trusted-domains="example.com,192.168.1.100"

# Or use occ
sudo all-dev-nextcloud.occ config:system:set trusted_domains 1 --value=example.com
```

## Data Backup and Restore

### Backup

```bash
# Export all data
sudo all-dev-nextcloud.export

# Backup database
sudo all-dev-nextcloud.mysqldump nextcloud > nextcloud-backup.sql

# Backup data directory
sudo tar -czf nextcloud-data-backup.tar.gz /var/snap/all-dev-nextcloud/common/nextcloud/data
```

### Restore

```bash
# Import data
sudo all-dev-nextcloud.import

# Restore database
sudo all-dev-nextcloud.mysql-client nextcloud < nextcloud-backup.sql

# Restore data directory
sudo tar -xzf nextcloud-data-backup.tar.gz -C /
```

## Performance Tuning

### Enable Redis Caching

Redis is enabled by default. Verify configuration:

```bash
sudo all-dev-nextcloud.occ config:system:get redis
```

### Adjust PHP Memory

```bash
sudo snap set all-dev-nextcloud php-memory-limit=512M
```

### Enable Cron Jobs

Cron is enabled by default. Verify:

```bash
sudo snap services all-dev-nextcloud.nextcloud-cron
```

## Security Considerations

1. **Strong Passwords**: Use strong admin passwords (minimum 12 characters)
2. **HTTPS**: Always enable HTTPS for production deployments
3. **Trusted Domains**: Configure trusted domains to prevent host header attacks
4. **Regular Updates**: Keep the snap updated with `sudo snap refresh all-dev-nextcloud`
5. **Firewall**: Configure firewall to allow only necessary ports
6. **Backups**: Implement regular backup strategy
7. **Two-Factor Authentication**: Enable 2FA for admin accounts

## Additional Resources

- [Nextcloud Documentation](https://docs.nextcloud.com/)
- [Nextcloud Admin Manual](https://docs.nextcloud.com/server/latest/admin_manual/)
- [Snap Documentation](https://snapcraft.io/docs)
- [Let's Encrypt Documentation](https://letsencrypt.org/docs/)

## Support

For issues specific to this snap package, please report them through the appropriate channels for the ALL platform.