# Arkadaş Puanlama

FastAPI ve SQLite ile küçük, mobil öncelikli arkadaş oylaması. Katılımcılar kendileri dışındaki herkesi her başlıkta 1–10 puanlar. Sonuçlar yalnızca herkes tamamlayınca açıklanır. Kişi bazında oy durumu veya tekil puanlar web üzerinden gösterilmez. Gönderilen oy değiştirilemez. Küçük gruplarda ortalamalardan çıkarım yapılabileceği için mutlak anonimlik sözü verilmez.

## Debian 13 üzerinde yerel başlatma

Python 3, venv ve Git kurulu olmalı. Depoyu GitHub'a yükledikten sonra:

```sh
sudo apt update
sudo apt install -y python3 python3-venv git
git clone https://github.com/KULLANICI/REPO.git rate-friends
cd rate-friends
sh scripts/setup.sh
sh scripts/run-dev.sh
```

Kurulum parolayı ekranda göstermez. `.env` ve `data/` Git dışında kalır. Tarayıcıda `http://127.0.0.1:8000` açın; VM'den uzaktan yerel deneme gerekiyorsa SSH tüneli kullanın: `ssh -L 8000:127.0.0.1:8000 USER@VM_IP`. Geliştirme komutu otomatik yeniden yükleme kullanır; internete açmak için değildir.

## Üretim

Önce alan adının A kaydını VM'nin public IP adresine yönlendirin. Azure NSG içinde TCP 80 ve 443 girişine izin verin. VM güvenlik duvarında da bu portları açın. Bu adımlar için Azure erişimi ve alan adı gerekir.

Uygulama kullanıcısını ve servisi hazırlayın (`KULLANICI/REPO` kendi GitHub adresiniz):

```sh
sudo useradd --system --user-group --home-dir /opt/rate-friends --shell /usr/sbin/nologin ratefriends
sudo install -d -o ratefriends -g ratefriends -m 700 /opt/rate-friends
sudo -u ratefriends git clone https://github.com/KULLANICI/REPO.git /opt/rate-friends
sudo -u ratefriends sh /opt/rate-friends/scripts/setup.sh
sudo -u ratefriends sed -i 's/^COOKIE_SECURE=0$/COOKIE_SECURE=1/' /opt/rate-friends/.env
sudo cp /opt/rate-friends/deploy/rate-friends.service /etc/systemd/system/rate-friends.service
sudo systemctl daemon-reload
sudo systemctl enable --now rate-friends
sudo systemctl status rate-friends
```

`setup.sh` parola girişini terminalde gizler. `.env` ve `data/` yalnızca servis kullanıcısına açık olmalı. Uygulama tek worker ile yalnızca `127.0.0.1:8000` dinler. `sudo systemctl is-active rate-friends` ile yeniden başlatma sonrası durumu kontrol edin.

Reverse proxy öncesi port sahiplerini görün:

```sh
sudo ss -ltnp '( sport = :80 or sport = :443 )'
```

Nginx veya başka bir sunucu bu portları kullanıyorsa onu körlemesine durdurmayın; mevcut reverse proxy'ye `127.0.0.1:8000` upstream ekleyin ya da geçiş planlayın. Portlar boşsa Caddy kurup örnekteki alan adını değiştirerek yapılandırabilirsiniz:

```sh
sudo apt install -y caddy
sudoedit /etc/caddy/Caddyfile
# deploy/Caddyfile.example içeriğini kendi alan adınızla buraya uyarlayın.
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
curl -I https://ALAN_ADI/
```

DNS ve 80/443 erişimi çalışıyorsa Caddy HTTPS sertifikasını yönetir. HTTP üzerinden üretim oturum çerezi kullanılmamalıdır.

Üretim servisinde erişim logu kapalıdır; kodlar URL'ye yazılmaz. Başlangıç kodlarını yönetici yalnızca oluşturma ekranında bir kez görür; güvenli kanaldan ayrı ayrı iletmelidir. Kod kaybolursa mevcut katılımcı için kurtarma yoktur. Aktif oylama bitip sonuçlar açıklandıktan sonra yeni oylama oluşturulabilir; eski sonuçlar SQLite'ta kalır, web arayüzü yalnızca aktif oylamayı gösterir.

## Yedek

Çalışan veritabanının tutarlı yedeği için, `.env` yüklüyken ve depo dışı güvenli dizin seçerek:

```sh
set -a; . ./.env; set +a
.venv/bin/python scripts/backup.py /var/backups/rate-friends
```

Yedek dizini yalnızca yetkili kullanıcıya açık tutun ve ayrı diske/konuma kopyalayın. `.env`, veritabanı, yedekler ve kod listesi Git'e eklenmemelidir.

## Test

```sh
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q
```
