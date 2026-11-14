import paramiko

def update_vps():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect('125.253.125.12', port=63379, username='nhanhd', password='H@neynet.vn', timeout=15)

    nginx_conf = """server {
    listen 80 default_server;
    listen [::]:80 default_server;
    listen 3000 default_server;
    listen [::]:3000 default_server;
    server_name _;

    root /opt/ai-agent-workspace/apps/desktop/out;
    index index.html;

    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript image/svg+xml;

    location / {
        try_files $uri $uri.html $uri/ /index.html =404;
    }

    location /_next/ {
        expires 1y;
        add_header Cache-Control "public, max-age=31536000, immutable";
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8765/api/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /ws/ {
        proxy_pass http://127.0.0.1:8765/ws/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }
}
"""

    sftp = ssh.open_sftp()
    with sftp.file('/tmp/ai-workspace.conf', 'w') as f:
        f.write(nginx_conf)
    sftp.close()

    cmd = """
echo H@neynet.vn | sudo -S rm -f /etc/nginx/sites-enabled/default
echo H@neynet.vn | sudo -S cp /tmp/ai-workspace.conf /etc/nginx/sites-available/ai-workspace
echo H@neynet.vn | sudo -S ln -sf /etc/nginx/sites-available/ai-workspace /etc/nginx/sites-enabled/ai-workspace
echo H@neynet.vn | sudo -S chmod -R 755 /opt/ai-agent-workspace/apps/desktop/out
echo H@neynet.vn | sudo -S nginx -t
echo H@neynet.vn | sudo -S systemctl reload nginx
echo H@neynet.vn | sudo -S systemctl restart ai-agent-backend.service
echo '=== DEPLOY DONE ==='
"""
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode('utf-8', errors='ignore')
    err = stderr.read().decode('utf-8', errors='ignore')
    print('OUTPUT:\n', out)
    if err:
        print('STDERR:\n', err)
    ssh.close()

if __name__ == '__main__':
    update_vps()
