from pathlib import Path

import requests

from app.config import settings


class SocialPublishService:
    def __init__(self) -> None:
        self.enabled = settings.auto_publish_enabled

    def publish_video(self, job_id: str, title: str, description: str, video_path: str) -> list[str]:
        if not self.enabled:
            return []

        results: list[str] = []
        for platform in settings.auto_publish_platforms:
            platform_name = platform.strip().lower()
            if not platform_name:
                continue

            try:
                if platform_name == "youtube":
                    video_id = self._publish_youtube(title=title, description=description, video_path=video_path)
                    results.append(f"youtube:ok:{video_id}")
                elif platform_name == "facebook":
                    post_id = self._publish_facebook(description=description, video_path=video_path)
                    results.append(f"facebook:ok:{post_id}")
                elif platform_name == "webhook":
                    code = self._publish_webhook(job_id=job_id, title=title, description=description, video_path=video_path)
                    results.append(f"webhook:ok:{code}")
                else:
                    results.append(f"{platform_name}:skip:unsupported")
            except Exception as exc:
                results.append(f"{platform_name}:fail:{exc}")

        return results

    def _publish_youtube(self, title: str, description: str, video_path: str) -> str:
        if not (
            settings.youtube_client_id
            and settings.youtube_client_secret
            and settings.youtube_refresh_token
        ):
            raise RuntimeError("missing youtube oauth env")

        token_res = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": settings.youtube_client_id,
                "client_secret": settings.youtube_client_secret,
                "refresh_token": settings.youtube_refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        token_res.raise_for_status()
        access_token = token_res.json().get("access_token")
        if not access_token:
            raise RuntimeError("youtube access token missing")

        path = Path(video_path)
        if not path.exists():
            raise RuntimeError(f"video file not found: {video_path}")

        metadata = {
            "snippet": {
                "title": title[:100],
                "description": description[:4900],
                "categoryId": "22",
            },
            "status": {
                "privacyStatus": settings.youtube_privacy_status,
                "selfDeclaredMadeForKids": False,
            },
        }

        init_res = requests.post(
            "https://www.googleapis.com/upload/youtube/v3/videos?part=snippet,status&uploadType=resumable",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Length": str(path.stat().st_size),
                "X-Upload-Content-Type": "video/mp4",
            },
            json=metadata,
            timeout=60,
        )
        init_res.raise_for_status()
        upload_url = init_res.headers.get("Location")
        if not upload_url:
            raise RuntimeError("youtube upload session missing")

        with path.open("rb") as file_handle:
            upload_res = requests.put(
                upload_url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "video/mp4",
                },
                data=file_handle,
                timeout=900,
            )
        upload_res.raise_for_status()
        video_id = upload_res.json().get("id")
        if not video_id:
            raise RuntimeError("youtube video id missing")
        return str(video_id)

    def _publish_facebook(self, description: str, video_path: str) -> str:
        if not (settings.facebook_page_id and settings.facebook_page_access_token):
            raise RuntimeError("missing facebook page env")

        path = Path(video_path)
        if not path.exists():
            raise RuntimeError(f"video file not found: {video_path}")

        endpoint = f"https://graph-video.facebook.com/v21.0/{settings.facebook_page_id}/videos"
        with path.open("rb") as file_handle:
            response = requests.post(
                endpoint,
                data={
                    "access_token": settings.facebook_page_access_token,
                    "description": description[:2000],
                    "published": "true",
                },
                files={"source": file_handle},
                timeout=900,
            )
        response.raise_for_status()

        data = response.json()
        post_id = data.get("id") or data.get("video_id")
        if not post_id:
            raise RuntimeError("facebook post id missing")
        return str(post_id)

    def _publish_webhook(self, job_id: str, title: str, description: str, video_path: str) -> int:
        if not settings.social_webhook_url:
            raise RuntimeError("SOCIAL_WEBHOOK_URL missing")

        path = Path(video_path)
        if not path.exists():
            raise RuntimeError(f"video file not found: {video_path}")

        with path.open("rb") as file_handle:
            response = requests.post(
                settings.social_webhook_url,
                data={
                    "job_id": job_id,
                    "title": title[:120],
                    "description": description[:2500],
                },
                files={"video": file_handle},
                timeout=900,
            )
        response.raise_for_status()
        return response.status_code
