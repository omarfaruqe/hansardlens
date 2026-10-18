# Deploying HansardLens next to another app

Target: `http://103.99.176.180/hansardlens/`, on a server that already runs
MapleMetrics at `/maplemetrics/` with Docker. The two apps are independent and get
separate addresses.

How it stays out of MapleMetrics' way:

- **Separate stack.** `docker-compose.prod.yml` has its own project name (`hansardlens`),
  so its containers, network and database volume are new and separate. Nothing of
  MapleMetrics is stopped, rebuilt or shared.
- **No public port.** HansardLens listens only on the server's loopback,
  `127.0.0.1:8010`. It becomes visible only when the gateway (Caddy) forwards to it.
- **One added proxy block.** The server's gateway is Caddy (container `gateway-caddy-1`,
  host network, config `/home/faruqe/gateway/Caddyfile`). `/hansardlens/` and
  `/maplemetrics/` do not overlap, so Caddy sends each path to its own app and the new
  block cannot affect MapleMetrics. Removing the block undoes it.
- **Own cookies.** HansardLens cookie names start with `hansardlens_` and are scoped to
  its path, so logins and settings never mix with MapleMetrics.

Run every command below on the server, unless marked **(Mac)**.

## 1. Check the server

```bash
docker compose version          # needs v2.20 or newer
free -h                         # 4 GB RAM or more is comfortable (topic model fitting)
df -h /                         # about 5 GB free for the database and images
sudo ss -ltnp | grep -E ':(80|443|8010) '
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}'
```

The `ss` line shows what serves port 80. On this server it is `caddy`, from the
`gateway-caddy-1` container in host network mode, which step 6 uses. (If a server uses
nginx instead, `deploy/nginx-hansardlens.conf` has the equivalent location blocks.)

HansardLens needs about 4 GB to install (2 GB database, 1.5 GB image and build cache,
0.5 GB temporary database copy). Keep at least 10 GB free so the disk never fills;
`sudo apt-get clean`, `sudo journalctl --vacuum-size=300M` and `docker builder prune -f`
free space without touching running apps.

Port 8010 must not be listed. If it is, choose another port and set `HANSARD_PORT` in
step 2 and in the nginx block.

## 2. Get the code and configure it

```bash
cd ~
git clone https://github.com/omarfaruqe/hansardlens.git
cd hansardlens
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(50))"    # copy the output
nano .env
```

Set these lines in `.env` (replace the two placeholders):

```
DJANGO_SECRET_KEY=<the long random value printed above>
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=103.99.176.180,localhost
DJANGO_CSRF_TRUSTED_ORIGINS=http://103.99.176.180
DJANGO_SCRIPT_NAME=/hansardlens
HANSARD_CACHE=file
POSTGRES_PASSWORD=<a strong password, letters and digits only>
HANSARD_PORT=8010
```

The container runs as an unprivileged user (uid 1000), so give it the data folder:

```bash
mkdir -p data
sudo chown -R 1000:1000 data
```

## 3. Bring the database across

Copying your local database is fastest: minutes instead of an hour of downloads, and the
topics and term shifts come with it.

**(Mac)** in `~/Desktop/hansardlens`, with the local stack running:

```bash
docker compose exec -T db pg_dump -U hansardlens -d hansardlens -Fc > hansardlens.dump
ls -lh hansardlens.dump
scp hansardlens.dump <your-user>@103.99.176.180:~/hansardlens/
```

On the server:

```bash
cd ~/hansardlens
docker compose -f docker-compose.prod.yml up -d db
docker compose -f docker-compose.prod.yml exec -T db \
  pg_restore -U hansardlens -d hansardlens --no-owner --clean --if-exists < hansardlens.dump
rm hansardlens.dump
```

*Alternative, without the Mac:* skip the restore and load everything on the server after
step 4 (about an hour, then a few minutes for the analysis):

```bash
docker compose -f docker-compose.prod.yml run --rm web python manage.py load_hansard --parliament 44 --session 1
docker compose -f docker-compose.prod.yml run --rm web python manage.py load_hansard --parliament 45 --session 1
docker compose -f docker-compose.prod.yml run --rm web python manage.py build_topics
docker compose -f docker-compose.prod.yml run --rm web python manage.py build_term_shifts
```

## 4. Start HansardLens

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps
curl -s http://127.0.0.1:8010/health/
```

`ps` should show `db`, `web` (healthy after about 30 seconds) and `scheduler`. The
health check should answer `"status": "ok"`. The scheduler does a first catch-up run
straight away, which loads any sittings published since your copy:

```bash
docker compose -f docker-compose.prod.yml logs -f scheduler      # Ctrl+C to stop following
```

MapleMetrics is untouched up to this point. Check it still answers:
`curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1/maplemetrics/`

## 5. Back up the Caddy configuration

```bash
cd ~/gateway
cp Caddyfile Caddyfile.bak-$(date +%F)
```

## 6. Add HansardLens to Caddy

Open the Caddyfile:

```bash
nano ~/gateway/Caddyfile
```

Add these two pieces inside the `:80 { ... }` block (the full result is in
`deploy/Caddyfile.example`): the redirect next to the existing `redir` line, and the
`handle_path` block after the MapleMetrics one.

```caddyfile
	redir /hansardlens /hansardlens/ permanent

	handle_path /hansardlens/* {
		reverse_proxy 127.0.0.1:8010
	}
```

Save with Ctrl+O, Enter, then Ctrl+X. Check that the container sees the new file and
that it is valid, then reload. A reload keeps current connections and does not
restart Caddy or MapleMetrics:

```bash
docker exec gateway-caddy-1 cat /etc/caddy/Caddyfile
docker exec gateway-caddy-1 caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
docker exec -w /etc/caddy gateway-caddy-1 caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
```

If `validate` reports an error, nothing has changed yet: fix the typo, or restore the
backup with `cp ~/gateway/Caddyfile.bak-<date> ~/gateway/Caddyfile`.

## 7. Check it

- http://103.99.176.180/hansardlens/ shows HansardLens with its styling.
- http://103.99.176.180/maplemetrics/ shows MapleMetrics as before.
- http://103.99.176.180/hansardlens/health/ includes the last refresh.

## Everyday operations

| Task | Command (in `~/hansardlens`) |
| ---- | ---------------------------- |
| Status | `docker compose -f docker-compose.prod.yml ps` |
| Logs | `docker compose -f docker-compose.prod.yml logs --tail 100 web scheduler` |
| Refresh now | `docker compose -f docker-compose.prod.yml run --rm web python manage.py refresh_data` |
| Update the code | `git pull && docker compose -f docker-compose.prod.yml up -d --build` |
| Back up the database | `docker compose -f docker-compose.prod.yml exec -T db pg_dump -U hansardlens -d hansardlens -Fc > backup-$(date +%F).dump` |
| Admin account | `docker compose -f docker-compose.prod.yml run --rm web python manage.py createsuperuser` |

The stack restarts by itself after a server reboot (`restart: unless-stopped`).

## Removing it again

1. Remove the HansardLens `redir` line and `handle_path` block from
   `~/gateway/Caddyfile`, then reload Caddy as in step 6.
2. `docker compose -f docker-compose.prod.yml down` (add `-v` to delete its database too).

MapleMetrics is not affected by either step.
