# Nginx Configuration for LLM RPG Engine

This directory contains nginx configuration files for production deployment with SSL/TLS.

## Files

| File | Purpose |
|------|---------|
| `nginx.conf` | Main nginx configuration (worker processes, gzip, rate limiting) |
| `sites-available/llm-rpg` | Virtual host configuration for the application |
| `ssl-params.conf` | SSL hardening parameters (TLS 1.2+, HSTS, OCSP stapling) |

## Deployment Steps

### 1. Install nginx

```bash
sudo apt update
sudo apt install nginx
```

### 2. Place Configuration Files

```bash
# Copy main config (optional, if customizing global settings)
sudo cp nginx.conf /etc/nginx/nginx.conf

# Copy site configuration
sudo cp sites-available/llm-rpg /etc/nginx/sites-available/llm-rpg

# Copy SSL parameters
sudo cp ssl-params.conf /etc/nginx/ssl-params.conf

# Enable the site
sudo ln -sf /etc/nginx/sites-available/llm-rpg /etc/nginx/sites-enabled/llm-rpg

# Remove default site (optional)
sudo rm -f /etc/nginx/sites-enabled/default
```

### 3. Update Domain Name

Edit `/etc/nginx/sites-available/llm-rpg` and replace `your-domain.com` with your actual domain:

```bash
sudo sed -i 's/your-domain.com/your-actual-domain.com/g' /etc/nginx/sites-available/llm-rpg
```

### 4. Obtain SSL Certificate with Let's Encrypt

```bash
# Install certbot
sudo apt install certbot python3-certbot-nginx

# Obtain certificate (replace with your domain and email)
sudo certbot --nginx -d your-actual-domain.com -d www.your-actual-domain.com

# Or use standalone mode if nginx is not running yet
sudo certbot certonly --standalone -d your-actual-domain.com
```

The certbot will automatically:
- Obtain SSL certificates from Let's Encrypt
- Modify nginx config to use the certificates
- Set up automatic renewal

### 5. Test and Restart nginx

```bash
# Test configuration syntax
sudo nginx -t

# Restart nginx
sudo systemctl restart nginx

# Enable nginx to start on boot
sudo systemctl enable nginx
```

### 6. Verify SSL

```bash
# Check SSL certificate
sudo certbot certificates

# Test SSL configuration (optional)
curl -vI https://your-actual-domain.com
```

## Certificate Renewal

Let's Encrypt certificates are valid for 90 days. Certbot sets up automatic renewal via systemd timer or cron:

```bash
# Test renewal (dry run)
sudo certbot renew --dry-run

# Force renewal if needed
sudo certbot renew --force-renewal
```

## Troubleshooting

### Check nginx logs

```bash
sudo tail -f /var/log/nginx/error.log
sudo tail -f /var/log/nginx/llm-rpg.error.log
```

### Check certificate paths

Ensure the certificate paths in `sites-available/llm-rpg` match your actual certificate location:

```bash
# List certificates
sudo ls -la /etc/letsencrypt/live/
```

### Common issues

1. **Permission denied**: Ensure nginx user (`www-data`) can read certificate files
2. **Port 80/443 blocked**: Check firewall (`sudo ufw status`) and ensure ports are open
3. **Certificate not found**: Run `sudo certbot certificates` to verify certificate issuance

## Backend and Frontend

Ensure the application services are running before enabling the site:

- **Backend**: FastAPI on `127.0.0.1:8000`
- **Frontend**: Next.js on `127.0.0.1:3005`

See project root `docker-compose.prod.yml` and `docs/deployment.md` for full production setup.
