# Backend deployment notes (VPS)

Deployed at ~/pigprices/repo on nexus-do, container `pigprices`,
port 127.0.0.1:8902 (localhost-bound like nestor_app).

## The pig333 403 constraint

pig333/3tres3 Cloudflare blocks the VPS's DigitalOcean ASN outright
(403 with any UA, and with curl_cffi chrome TLS impersonation). Home IPs
work. Therefore: collection runs on the home network (Mac/NAS collector)
and pushes via POST /ingest; the VPS stays the history DB + widget API.

## Public exposure (pending DNS)

pigs.maytek.co does not resolve yet (maytek.co is on Route 53; no AWS
credentials on this machine). Once the A record -> 152.42.164.157 exists:
1. The nginx HTTP block is already live (PIGS_HTTP_START).
2. Issue cert:
   docker run --rm -v /home/lstorino/letsencrypt:/etc/letsencrypt \
     -v /home/lstorino/nexus/docker/nginx/certbot/www:/var/www/certbot \
     certbot/certbot certonly --webroot -w /var/www/certbot \
     -d pigs.maytek.co --email lstorino@maytek.co \
     --agree-tos --no-eff-email --non-interactive
3. Append the PIGS_HTTPS_START block (mirror of NESTOR_HTTPS_START,
   upstream `pigprices`, port 8902) and reload.

Until DNS is up, the widget falls back to the SSH tunnel
(ssh -N -L 18902:127.0.0.1:8902 nexus-do) or scrapes pig333 directly.

## Token

PIG_TOKEN lives in ~/pigprices/repo/backend/.env on the VPS (48 hex chars).
Widget + collector use ?token=... or X-Pig-Token.
