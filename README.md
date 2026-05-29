# all-dev-nextcloud

A complete Nextcloud server snap package providing secure file storage, calendar, contacts, and collaboration features with Apache, MySQL, PHP-FPM, and Redis.

## Quick Start

```bash
# Install the snap
sudo snap install all-dev-nextcloud

# Configure admin credentials
sudo snap set all-dev-nextcloud admin-username="admin"
sudo snap set all-dev-nextcloud admin-password="your-secure-password"

# Set trusted domain
sudo snap set all-dev-nextcloud trusted-domains="your-domain.com"

# Access Nextcloud
# Open browser to http://your-server-ip
```

## Features

- **Complete Nextcloud Server** (v32.0.9) - Full-featured cloud storage and collaboration
- **Apache 2.4.67** - High-performance web server
- **MySQL 8.4.9** - Reliable database backend
- **PHP 8.3.31 with FPM** - Fast PHP processing
- **Redis 8.2.6** - Memory caching for performance
- **HTTPS Support** - Built-in Let's Encrypt integration
- **Auto Certificate Renewal** - Automatic HTTPS certificate management
- **Data Import/Export** - Easy backup and migration
- **Cron Jobs** - Background task processing
- **Log Rotation** - Automatic log management

## Services

The snap runs multiple services:
- `apache` - Web server
- `mysql` - Database server
- `php-fpm` - PHP processor
- `redis-server` - Cache server
- `nextcloud-cron` - Background jobs
- `nextcloud-fixer` - Maintenance tasks
- `renew-certs` - Certificate renewal
- `logrotate` - Log management

## Configuration

### Basic Setup

```bash
# Set admin credentials
sudo snap set all-dev-nextcloud admin-username="admin"
sudo snap set all-dev-nextcloud admin-password="SecurePass123"

# Configure trusted domains
sudo snap set all-dev-nextcloud trusted-domains="example.com,192.168.1.100"

# Set custom ports (optional)
sudo snap set all-dev-nextcloud http-port=8080
sudo snap set all-dev-nextcloud https-port=8443
```

### Enable HTTPS

```bash
# With Let's Encrypt
sudo all-dev-nextcloud.enable-https lets-encrypt cloud.example.com admin@example.com

# With self-signed certificate
sudo all-dev-nextcloud.enable-https self-signed cloud.example.com

# Disable HTTPS
sudo all-dev-nextcloud.disable-https
```

## Common Commands

### Administrative

```bash
# Run occ commands
sudo all-dev-nextcloud.occ <command>

# List users
sudo all-dev-nextcloud.occ user:list

# Add user
sudo all-dev-nextcloud.occ user:add username

# Enable app
sudo all-dev-nextcloud.occ app:enable calendar

# System status
sudo all-dev-nextcloud.occ status
```

### Database

```bash
# Access MySQL
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

## Monitoring

```bash
# Check service status
sudo snap services all-dev-nextcloud

# View logs
sudo snap logs all-dev-nextcloud.apache
sudo snap logs all-dev-nextcloud.mysql
sudo snap logs all-dev-nextcloud.php-fpm

# System check
sudo all-dev-nextcloud.occ check
```

## Troubleshooting

### Cannot Access Web Interface

```bash
# Restart services
sudo snap restart all-dev-nextcloud

# Check firewall
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
```

### Database Issues

```bash
# Restart MySQL
sudo snap restart all-dev-nextcloud.mysql

# Check logs
sudo snap logs all-dev-nextcloud.mysql
```

### Trusted Domain Error

```bash
# Add trusted domain
sudo snap set all-dev-nextcloud trusted-domains="example.com,192.168.1.100"

# Or use occ
sudo all-dev-nextcloud.occ config:system:set trusted_domains 1 --value=example.com
```

## Documentation

For detailed deployment instructions, configuration options, and troubleshooting, see:
- [Deployment Guide](docs/deployment-guide.md)
- [Nextcloud Documentation](https://docs.nextcloud.com/)

## Security

- Use strong passwords (minimum 12 characters)
- Enable HTTPS for production
- Configure trusted domains
- Keep snap updated: `sudo snap refresh all-dev-nextcloud`
- Enable two-factor authentication
- Regular backups

## Support

For issues and support, please refer to the ALL platform documentation and support channels.

## License

This snap package bundles multiple open-source components. See individual component licenses for details.
