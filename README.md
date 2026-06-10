# AI Content Agent (Website + Tailscale)

He thong nay da chuyen sang workflow website. Telegram chi dung tuy chon de nhan thong bao done/error.

## Tong quan

- Tao noi dung voi local LLM qua Ollama
- Gemini precheck/refine (tuy chon)
- Clone giong (XTTS)
- Dung video ban tu quay (upload qua web)
- Auto publish social (YouTube/Facebook/Webhook, tuy chon)
- Truy cap an toan qua Tailscale

## 1) Yeu cau

- Ubuntu 24.04
- Docker Engine + Docker Compose plugin
- NVIDIA driver + NVIDIA Container Toolkit
- Tailscale tren may host

## 2) Cai dat Docker + GPU

```bash
sudo apt update
sudo apt install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
```

```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt update
sudo apt install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

## 3) Cau hinh

```bash
cp .env.example .env
```

Bat buoc sua:

- WEB_ADMIN_TOKEN
- GEMINI_API_KEY (neu dung)
- YOUTUBE/FACEBOOK env (neu auto publish)

Telegram notify (tuy chon):

- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID

## 4) Chay he thong

```bash
docker compose up -d --build
```

```bash
docker compose exec ollama ollama pull qwen2.5:3b
```

## 5) Truy cap Web Console

Mo trinh duyet:

- http://localhost:8000/web

Dang nhap bang WEB_ADMIN_TOKEN trong form dau trang.

Chuc nang web:

1. Upload video goc (khong nen)
2. Suggest topic
3. Tao job voi lua chon nguon video: internet hoac tu minh quay
4. Xem danh sach video
5. Xem trang thai job (queued/running/completed/failed)
6. Bat thong bao Telegram khi job hoan tat/that bai ngay luc tao job

## 6) Workflow khuyen nghi

1. AI de xuat script/chu de
2. Ban quay video theo script
3. Upload video goc vao web (neu chon nguon tu quay)
4. Chon nguon video:
  - self: dung video ban upload
  - internet: tim clip stock theo keyword
5. Chon topic + run job
6. Theo doi ket qua tren web

## 7) Toi uu chat luong video

- VIDEO_PRESERVE_QUALITY=true
- VIDEO_TEXT_OVERLAY=false
- VIDEO_REENCODE_CRF=18
- VIDEO_REENCODE_PRESET=medium

Neu chi thay audio va khong overlay text, pipeline uu tien copy stream video de giam mat chat luong.

## 8) Tailscale (khong public internet)

Cai Tailscale tren host Ubuntu:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

Lay tailscale IP:

```bash
tailscale ip -4
```

Truy cap tu may khac cung tailnet:

- http://<tailscale-ip-host>:8000/web

Khuyen nghi bao mat:

1. Khong mo port 8000 ra internet cong khai
2. Dung tailnet ACL de gioi han thiet bi duoc truy cap
3. Dat WEB_ADMIN_TOKEN manh

## 9) Auto publish (tuy chon)

- AUTO_PUBLISH_ENABLED=true
- AUTO_PUBLISH_PLATFORMS=youtube,facebook,webhook

YouTube:

- YOUTUBE_CLIENT_ID
- YOUTUBE_CLIENT_SECRET
- YOUTUBE_REFRESH_TOKEN

Facebook:

- FACEBOOK_PAGE_ID
- FACEBOOK_PAGE_ACCESS_TOKEN

Webhook:

- SOCIAL_WEBHOOK_URL

## 10) Dau ra

- Markdown: /app/data/jobs/<job_id>.md
- Audio: /app/data/outputs/<job_id>.wav
- Video: /app/data/outputs/<job_id>.mp4
- Upload goc: /app/data/uploads/

## 11) CI/CD voi GitHub Actions

Repo da co san 2 workflow:

- .github/workflows/ci.yml
- .github/workflows/cd.yml

CI se chay khi push/pull request:

1. Cai dependencies Python
2. Compile source de bat loi syntax
3. Build 2 Docker images (app + voice)

CD se chay khi push nhanh main hoac trigger thu cong:

1. SSH vao server
2. cd den thu muc deploy
3. git pull origin main
4. docker compose up -d --build (neu khong co, fallback sang docker-compose up -d --build)

Can tao GitHub Actions secrets (Settings -> Secrets and variables -> Actions):

- SSH_HOST: IP hoac domain server
- SSH_USER: user SSH
- SSH_KEY: private key (PEM) de dang nhap server
- DEPLOY_PATH: duong dan tren server, vi du /opt/content-agent

Luu y:

1. Server can cai docker + docker compose plugin
2. Thu muc DEPLOY_PATH phai la git repo da clone san
3. Nen tao .env tren server truoc, khong commit .env vao git

## 12) Server chua cai Docker thi lam gi

SSH vao server, chay:

sudo apt update
sudo apt install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker $USER

Dang xuat roi dang nhap lai SSH de nhan group docker.

Kiem tra:

docker --version
docker compose version

Sau do vao thu muc deploy va chay:

docker compose up -d --build

Luu y: docker-compose v1 (goi apt: docker-compose) da cu va co the loi tren Python 3.12 (ModuleNotFoundError: distutils). Nen dung Compose v2 (docker compose plugin).
