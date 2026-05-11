"""Cloud Tasks helper for async video processing."""

import json

from config import (
    CLOUD_TASKS_QUEUE,
    CLOUD_TASKS_LOCATION,
    GOOGLE_CLOUD_PROJECT,
    BACKEND_INTERNAL_URL,
    CLOUD_TASKS_SECRET,
)


def enqueue_video_processing(video_uuid: str) -> None:
    """Enqueue a Cloud Tasks HTTP task to process a video after upload."""
    from google.cloud import tasks_v2

    client = tasks_v2.CloudTasksClient()
    parent = client.queue_path(GOOGLE_CLOUD_PROJECT, CLOUD_TASKS_LOCATION, CLOUD_TASKS_QUEUE)

    url = f"{BACKEND_INTERNAL_URL}/internal/videos/{video_uuid}/process"
    task = tasks_v2.Task(
        http_request=tasks_v2.HttpRequest(
            http_method=tasks_v2.HttpMethod.POST,
            url=url,
            headers={
                "Content-Type": "application/json",
                "X-Internal-Secret": CLOUD_TASKS_SECRET,
            },
            body=json.dumps({"video_uuid": video_uuid}).encode(),
        )
    )
    client.create_task(request={"parent": parent, "task": task})
